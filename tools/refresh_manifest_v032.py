#!/usr/bin/env python3
"""Refresh current SHA256 entries plus v0.3.2 files, keeping legacy scope."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[1]
manifest_path = root / 'MANIFEST_SHA256.json'
if not manifest_path.is_file():
    raise SystemExit('Execute this tool in the FULL repository, where MANIFEST_SHA256.json exists.')
existing = json.loads(manifest_path.read_text(encoding='utf-8'))
added = [
    'tests/test_dual_selection.py',
    'examples/config_dual_auto.json',
    'examples/config_dual_paper_sepolia.json',
    'docs/DUAL_SELECTION_V032.md',
    'tools/refresh_manifest_v032.py',
]
paths = sorted(set(existing) | set(added))
updated = {}
for filename in paths:
    path = root / filename
    if not path.is_file():
        raise FileNotFoundError(f'Manifest references a missing file: {filename}')
    updated[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
manifest_path.write_text(json.dumps(updated, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(f'Refreshed {len(updated)} SHA256 entries in {manifest_path}')
