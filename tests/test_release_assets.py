"""Release packaging checks (no GHCR push or Git tag required)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_release", ROOT / "tools" / "prepare_release.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_fixed_version_release_cwls_preserve_original_sources(tmp_path):
    src_main = (ROOT / "cwl" / "workflow.cwl").read_bytes()
    src_tool = (ROOT / "cwl" / "preprocess.cwl").read_bytes()
    assets = module.create_release_cwls(
        ROOT, tmp_path / "release", "v0.3.2",
        "ghcr.io/esa-heatwise/heatwise-class-guided:0.3.2",
        "https://github.com/ESA-Heatwise/heatwise-class-guided",
    )
    workflow = assets["workflow.cwl"].read_text(encoding="utf-8")
    processor = assets["preprocess.cwl"].read_text(encoding="utf-8")
    assert "run: preprocess.cwl" in workflow
    assert 's:version: "0.3.2"' in workflow
    assert 's:softwareVersion: "0.3.2"' in processor
    assert "dockerPull: ghcr.io/esa-heatwise/heatwise-class-guided:0.3.2" in processor
    assert "https://github.com/ESA-Heatwise/heatwise-class-guided" in workflow
    assert "heatwise/class-guided:0.3.2" not in processor
    assert "/app/class_guided_processor.py" in processor
    assert (ROOT / "cwl" / "workflow.cwl").read_bytes() == src_main
    assert (ROOT / "cwl" / "preprocess.cwl").read_bytes() == src_tool
    with zipfile.ZipFile(assets["archive"]) as z:
        assert sorted(z.namelist()) == ["cwl/preprocess.cwl", "cwl/workflow.cwl"]
        assert z.read("cwl/preprocess.cwl").decode("utf-8") == processor


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
