#!/usr/bin/env python3
"""Build version-locked EOAP CWL assets without editing tracked source CWLs.

For a formal GitHub release, the workflow also uses cwltool --pack to produce
one independently downloadable, self-contained CWL from the versioned pair.
"""
from __future__ import annotations

import argparse
import re
import shutil
import zipfile
from pathlib import Path

SEMVER = re.compile(r"^v?([0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?)$")
IMAGE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+:[a-z0-9][a-z0-9_.-]*$")
REPOSITORY = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _replace_one(source: str, pattern: str, replacement: str, name: str) -> str:
    result, count = re.subn(pattern, lambda _: replacement, source, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"{name}: expected 1 occurrence of {pattern!r}, found {count}")
    return result


def create_release_cwls(
    repository_root: Path,
    output_dir: Path,
    version: str,
    image: str,
    repository_url: str,
) -> dict[str, Path]:
    """Create paired CWL, downloadable copies, and a versioned ZIP archive."""
    match = SEMVER.fullmatch(version)
    if not match:
        raise ValueError("Version must be vMAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH")
    normalized = match.group(1)
    if not IMAGE.fullmatch(image) or image.rsplit(":", 1)[-1] != normalized:
        raise ValueError("Docker image must be ghcr.io/owner/name:<exact-release-version>")
    if not REPOSITORY.fullmatch(repository_url):
        raise ValueError("Repository URL must be https://github.com/owner/repo")

    source = Path(repository_root) / "cwl"
    destination = Path(output_dir) / "cwl"
    destination.mkdir(parents=True, exist_ok=True)

    result: dict[str, Path] = {}
    for filename in ("workflow.cwl", "preprocess.cwl"):
        contents = (source / filename).read_text(encoding="utf-8")
        contents = _replace_one(contents, r"^s:softwareVersion:.*$", f's:softwareVersion: "{normalized}"', filename)
        contents = _replace_one(contents, r"^s:version:.*$", f's:version: "{normalized}"', filename)
        contents = _replace_one(contents, r"^s:codeRepository:.*$", f"s:codeRepository: {repository_url}", filename)

        count = len(re.findall(r"^\s*dockerPull:", contents, flags=re.MULTILINE))
        if filename == "preprocess.cwl":
            if count != 1:
                raise ValueError(f"{filename}: expected exactly one dockerPull, found {count}")
            contents = _replace_one(contents, r"^    dockerPull:.*$", f"    dockerPull: {image}", filename)
            if "/app/class_guided_processor.py" not in contents:
                raise ValueError("The release tool must call the processor packed in Docker")
        elif count != 0 or "run: preprocess.cwl" not in contents:
            raise ValueError("workflow.cwl must reference sibling preprocess.cwl and no direct DockerRequirement")

        (destination / filename).write_text(contents, encoding="utf-8")
        # These individual assets can be downloaded together into the same
        # directory. The ZIP preserves their original cwl/ directory layout.
        (Path(output_dir) / filename).write_text(contents, encoding="utf-8")
        result[filename] = destination / filename

    archive = Path(output_dir) / f"heatwise-class-guided-cwl-v{normalized}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in ("workflow.cwl", "preprocess.cwl"):
            z.write(destination / name, arcname=f"cwl/{name}")
    result["archive"] = archive
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--repository-url", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    outputs = create_release_cwls(
        Path(__file__).resolve().parents[1],
        args.output_dir,
        args.version,
        args.image,
        args.repository_url,
    )
    for name, path in outputs.items():
        print(f"[RELEASE CWL] {name}: {path}")


if __name__ == "__main__":
    main()
