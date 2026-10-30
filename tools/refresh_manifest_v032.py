#!/usr/bin/env python3
"""Create or validate a SHA-256 manifest for version-controlled code/documents.

The manifest intentionally excludes external real datasets, generated science
outputs, binary fixtures and itself. Binary test fixtures are checked through
functional CI; their individual input digests can be recorded separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "MANIFEST_SHA256.json"


def source_file(path: str) -> bool:
    if path == "MANIFEST_SHA256.json":
        return False
    if path.startswith(("examples/output", "examples/resources/", "examples/sepolia/", "validation/")):
        return False
    if path.startswith("examples/"):
        return (
            path.endswith((".json", ".yml", ".yaml", ".py"))
            or path == "examples/job_synthetic.yml"
        ) and not path.startswith(("examples/synthetic/", "examples/synthetic_250/"))
    if path.startswith(".github/workflows/"):
        return path.endswith((".yml", ".yaml"))
    if path.startswith(("cwl/", "docs/", "reference/", "tests/", "tools/")):
        return path.endswith((".py", ".md", ".json", ".cwl", ".yml", ".yaml"))
    return path in {
        ".gitignore", ".dockerignore", "Dockerfile", "NOTICE.md",
        "LICENSE", "README.md", "VALIDATION_REPORT.md",
        "class_guided_processor.py", "config.json", "requirements.txt",
        "requirements-dev.txt", "requirements-lock-python311.txt",
    }


def compute() -> dict[str, str]:
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    manifest = {}
    for filename in sorted(filter(source_file, files)):
        path = ROOT / filename
        if not path.is_file():
            raise FileNotFoundError(f"Tracked source missing: {filename}")
        manifest[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not manifest or "class_guided_processor.py" not in manifest:
        raise RuntimeError("No scientific sources found in manifest selection")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail on missing/stale/unexpected manifest entries")
    args = parser.parse_args()
    expected = compute()
    if args.check:
        if not OUTPUT.is_file():
            raise SystemExit("MANIFEST_SHA256.json missing")
        actual = json.loads(OUTPUT.read_text(encoding="utf-8"))
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        wrong = sorted(p for p in expected.keys() & actual.keys() if actual[p] != expected[p])
        if missing or extra or wrong:
            raise SystemExit(
                f"Manifest mismatch: missing={missing}, extra={extra}, sha_changed={wrong}. "
                "Regenerate by running python tools/refresh_manifest_v032.py and commit the updated manifest."
            )
        print(f"Verified {len(expected)} SHA256 source checksums")
    else:
        OUTPUT.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote {len(expected)} SHA256 source checksums")


if __name__ == "__main__":
    main()
