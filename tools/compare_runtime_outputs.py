"""Check scientifically important outputs between host and runtime-only Docker.

This is a regression check, not an assessment of classification accuracy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def compare(host: Path, container: Path) -> None:
    for name in (
        "selected_endmembers_FULL.xlsx",
        "selected_endmembers_MASK3.xlsx",
        "selected_endmembers.xlsx",
    ):
        a = pd.read_excel(host / name)
        b = pd.read_excel(container / name)
        if list(a.columns) != list(b.columns):
            raise AssertionError(f"{name}: different endmember names/order")
        np.testing.assert_array_equal(a["wavelength_um"].to_numpy(), b["wavelength_um"].to_numpy())
        np.testing.assert_allclose(
            a.iloc[:, 1:].to_numpy(float), b.iloc[:, 1:].to_numpy(float),
            rtol=1e-6, atol=1e-7,
            err_msg=f"{name}: reflectance differs between host and Docker",
        )
        print(f"[RUNTIME-PARITY] {name}: {len(a)} wavelengths, {len(a.columns)-1} endmembers")
    for name, key in (
        ("selected_bands.json", "original_band_indices_base0"),
        ("mask3_matching_bands.json", "matching_grid_indices_base0"),
    ):
        a = json.loads((host / name).read_text())
        b = json.loads((container / name).read_text())
        if key not in a or key not in b:
            raise AssertionError(f"Missing selection key {key} in {name}")
        if a[key] != b[key]:
            raise AssertionError(f"{name}: different selected band indices")
    a = json.loads((host / "run_summary.json").read_text())
    b = json.loads((container / "run_summary.json").read_text())
    for key in ("endmembers_by_mode", "selected_bands", "mask3_metric_bands", "full_metric_bands"):
        if a.get(key) != b.get(key):
            raise AssertionError(f"run_summary.json: difference in {key}")
    print("[RUNTIME-PARITY] host vs production Docker: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("host", type=Path)
    parser.add_argument("container", type=Path)
    args = parser.parse_args()
    compare(args.host, args.container)
