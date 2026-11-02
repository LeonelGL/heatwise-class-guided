"""Release packaging checks (no GHCR push or Git tag required)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import zipfile

import yaml

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_release", ROOT / "tools" / "prepare_release.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_fixed_version_release_cwls_preserve_original_sources(tmp_path):
    src_main = (ROOT / "cwl" / "workflow.cwl").read_bytes()
    src_tool = (ROOT / "cwl" / "preprocess.cwl").read_bytes()
    src_material_workflow = (ROOT / "cwl" / "material_workflow.cwl").read_bytes()
    src_material_tool = (ROOT / "cwl" / "material_postprocess.cwl").read_bytes()
    assets = module.create_release_cwls(
        ROOT, tmp_path / "release", "v0.3.2",
        "ghcr.io/esa-heatwise/heatwise-class-guided:0.3.2",
        "https://github.com/ESA-Heatwise/heatwise-class-guided",
    )
    workflow = assets["workflow.cwl"].read_text(encoding="utf-8")
    processor = assets["preprocess.cwl"].read_text(encoding="utf-8")
    material_workflow = assets["material_workflow.cwl"].read_text(encoding="utf-8")
    material_tool = assets["material_postprocess.cwl"].read_text(encoding="utf-8")
    assert "run: preprocess.cwl" in workflow
    assert 's:version: "0.3.2"' in workflow
    assert 's:softwareVersion: "0.3.2"' in processor
    assert "dockerPull: ghcr.io/esa-heatwise/heatwise-class-guided:0.3.2" in processor
    assert "https://github.com/ESA-Heatwise/heatwise-class-guided" in workflow
    assert "heatwise/class-guided:0.3.2" not in processor
    assert "/app/class_guided_processor.py" in processor
    assert (ROOT / "cwl" / "workflow.cwl").read_bytes() == src_main
    assert "run: material_postprocess.cwl" in material_workflow
    assert "/app/aggregate_fcls_classes.py" in material_tool
    assert "dockerPull: ghcr.io/esa-heatwise/heatwise-class-guided:0.3.2" in material_tool
    assert 's:version: "0.3.2"' in material_workflow
    assert (ROOT / "cwl" / "preprocess.cwl").read_bytes() == src_tool
    assert (ROOT / "cwl" / "material_workflow.cwl").read_bytes() == src_material_workflow
    assert (ROOT / "cwl" / "material_postprocess.cwl").read_bytes() == src_material_tool
    with zipfile.ZipFile(assets["archive"]) as z:
        assert sorted(z.namelist()) == [
            "cwl/material_postprocess.cwl", "cwl/material_workflow.cwl",
            "cwl/preprocess.cwl", "cwl/workflow.cwl",
        ]
        assert z.read("cwl/preprocess.cwl").decode("utf-8") == processor
        assert z.read("cwl/material_postprocess.cwl").decode("utf-8") == material_tool


@pytest.mark.parametrize(
    "version,image",
    [
        ("latest", "ghcr.io/esa-heatwise/heatwise-class-guided:latest"),
        ("v0.3.2", "ghcr.io/esa-heatwise/heatwise-class-guided:latest"),
        ("v0.3.2", "ghcr.io/esa-heatwise/heatwise-class-guided:0.3.3"),
    ],
)
def test_rejects_unversioned_and_mismatched_images(tmp_path, version, image):
    with pytest.raises(ValueError):
        module.create_release_cwls(
            ROOT, tmp_path, version, image,
            "https://github.com/ESA-Heatwise/heatwise-class-guided",
        )


def test_release_workflow_executes_one_packed_cwl_per_step():
    """The license-gated release workflow is not exercised by PR CI.

    Check its shell command and assets to catch accidental broken edits.
    """
    path = ROOT / ".github" / "workflows" / "release.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = data["jobs"]["release"]["steps"]
    preprocessing = next(step for step in steps if step.get("name") == "Smoke-test release CWL inside its release Docker image")
    run = preprocessing["run"]
    assert "release_dist/heatwise_class_guided.cwl \\\n" in run
    assert "            examples/job_synthetic.yml" in run or "examples/job_synthetic.yml" in run
    assert "release_dist/heatwise_material_top1.cwl" not in run
    # There should be a distinct synthetic test for material classification.
    separate = next(step for step in steps if step.get("name") == "Smoke-test material postprocessor with synthetic FCLS-shaped STAC input")
    assert "release_dist/heatwise_material_top1.cwl" in separate["run"]
    assert "results/material-fixture/job_material_synthetic.yml" in separate["run"]
    release = next(step for step in steps if step.get("name") == "Create GitHub release with fixed CWL assets")
    assets = set(release["with"]["files"].split())
    assert {
        "release_dist/heatwise_class_guided.cwl",
        "release_dist/heatwise_material_top1.cwl",
        "release_dist/workflow.cwl",
        "release_dist/preprocess.cwl",
        "release_dist/material_workflow.cwl",
        "release_dist/material_postprocess.cwl",
        "README.md", "NOTICE.md", "LICENSE",
    }.issubset(assets)


def test_bundled_reference_data_and_no_tracked_credentials():
    """Sepolia/GUSL are intentionally bundled; credentials still forbidden."""
    names = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT,
    ).decode("utf-8").split("\\0")
    required = {
        "examples/resources/GUSL_spectra_by_material_headers.xlsx",
        "examples/sepolia/Sepolia_CHIME_Thermopolis_v2_COG.tif",
        "examples/sepolia/item.json",
        "examples/sepolia/catalog.json",
        "examples/job_sepolia.yml",
    }
    assert required.issubset(set(names)), "Bundled reference inputs missing"
    forbidden = [
        name for name in names if name and (
            Path(name).name in {"credentials.json", "secrets.json"}
            or Path(name).name.startswith(".env")
            or Path(name).suffix.lower() in {".pem", ".p12", ".pfx", ".key"}
        )
    ]
    assert not forbidden, f"Credential file tracked: {forbidden}"
