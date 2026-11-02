"""Check that published documentation describes existing repository files."""
from __future__ import annotations

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REMOVED_DOCS = {
    "docs/DUAL_SELECTION_V032.md",
    "docs/GENERAL_CLASS_FALLBACK.md",
    "docs/EOAP_READINESS.md",
    "docs/CHANGES.md",
}


def tracked() -> set[str]:
    return set(
        subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        .decode("utf-8").strip("\0").split("\0")
    )


def test_markdown_relative_links_exist():
    """All local Markdown links must resolve to tracked files."""
    paths = tracked()
    for name in sorted(x for x in paths if x.endswith(".md")):
        body = (ROOT / name).read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", body):
            if target.startswith(("https://", "http://", "#", "mailto:")):
                continue
            local = target.split("#", 1)[0]
            if not local:
                continue
            resolved = (ROOT / name).parent.joinpath(local).resolve()
            assert resolved.is_relative_to(ROOT), (name, target)
            assert resolved.is_file(), f"Broken Markdown link in {name}: {target}"
            assert resolved.relative_to(ROOT).as_posix() in paths, (name, target)


def test_no_refs_to_removed_docs():
    names = tracked()
    assert not (REMOVED_DOCS & names)
    prose = [x for x in names if x.endswith((".md", ".cwl"))]
    prose += ["class_guided_processor.py"]
    for name in prose:
        text = (ROOT / name).read_text(encoding="utf-8")
        for deleted in REMOVED_DOCS:
            assert deleted not in text, f"Stale reference to {deleted} in {name}"


def test_bundled_example_paths_appear_in_readme():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for path in (
        "examples/sepolia/Sepolia_CHIME_Thermopolis_v2_COG.tif",
        "examples/resources/GUSL_spectra_by_material_headers.xlsx",
        "examples/job_sepolia.yml",
        "cwl/material_workflow.cwl",
    ):
        assert path in text
        assert (ROOT / path).is_file()
