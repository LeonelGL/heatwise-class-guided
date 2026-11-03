"""Dependency configuration contract: one pinned Python 3.11 requirements file."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
OBSOLETE = (
    "requirements-dev.txt",
    "requirements-lock-python311.txt",
    "requirements-runtime-lock-python311.txt",
)


def test_single_requirements_file_is_tracked():
    names = set(subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines())
    assert "requirements.txt" in names
    assert {p for p in names if p.startswith("requirements") and p.endswith(".txt")} == {
        "requirements.txt"
    }
    assert not any((ROOT / name).exists() for name in OBSOLETE)


def test_every_dependency_is_pinned_and_unique():
    found = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._+!-]*)", item)
        assert match, f"Unpinned/unsupported requirement: {item}"
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        assert name not in found, f"Duplicate package requirement: {name}"
        found[name] = match.group(2)
    for name in ("numpy", "scipy", "pandas", "rasterio", "pystac", "openpyxl",
                 "scikit-learn", "shapely", "pyyaml", "pytest", "cwltool",
                 "rio-cogeo", "jsonschema"):
        assert name in found, f"Missing runtime/test dependency: {name}"


def test_docker_and_both_workflows_install_the_same_requirements():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY requirements.txt /app/" in dockerfile
    assert "pip install --no-cache-dir -r requirements.txt && python -m pip check" in dockerfile
    for workflow in (".github/workflows/validate.yml", ".github/workflows/release.yml"):
        text = (ROOT / workflow).read_text(encoding="utf-8")
        assert "python -m pip install -r requirements.txt" in text
    for name in OBSOLETE:
        assert name not in dockerfile
        assert not any(name in (ROOT / p).read_text(encoding="utf-8")
                       for p in (".github/workflows/validate.yml",
                                 ".github/workflows/release.yml",
                                 "README.md", "docs/EOAP.md", "docs/RELEASE.md"))
