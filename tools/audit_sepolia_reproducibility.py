#!/usr/bin/env python3
"""HEATWISE: real-scene reproducibility + controlled PPI sensitivity audit.

Does not modify the scientific processor or the official ESA FCLS. Runs the
exact current class_guided_processor.py as independent subprocesses on one
GitHub runner, with controlled inputs, random seed, BLAS threads and config.

The 2000-v-500000 comparison MUST preserve candidate and endmember spectra.
A change caused by increasing N_RANDOM_PROJECTIONS is expected/diagnostic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


CASES = (
    ("baseline_A", 2000, 2000),
    ("baseline_B", 2000, 2000),
    ("bands_500000", 2000, 500000),
    ("ppi_10000", 10000, 2000),
)


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    return value


def read_case(output):
    diag = output / "diagnostics"
    with np.load(diag / "candidates.npz", allow_pickle=False) as npz:
        X = np.array(npz["spectra"], copy=True)
        wl = np.array(npz["wavelengths_um"], copy=True)
        orig = np.array(npz["original_indices_base0"], copy=True)
    locations = pd.read_csv(diag / "candidates.csv")
    em = pd.read_excel(output / "selected_endmembers.xlsx")
    summary = json.loads((output / "run_summary.json").read_text())
    bands = json.loads((output / "selected_bands.json").read_text())
    fallback = json.loads((diag / "FULL_fallback_report.json").read_text())
    return {
        "spectra": X, "wavelengths": wl, "original_indices": orig,
        "locations": locations, "endmembers": em, "mask3_endmembers": pd.read_excel(output / "selected_endmembers_MASK3.xlsx"),
        "summary": summary, "bands": bands, "fallback": fallback,
    }


def compare_cases(a, b):
    sa, sb = a["spectra"], b["spectra"]
    same_shape = sa.shape == sb.shape
    n_aligned = int(np.sum(np.all(sa == sb, axis=1))) if same_shape else 0
    max_abs = float(np.max(np.abs(sa.astype(float)-sb.astype(float)))) if same_shape else None
    frame_a, frame_b = a["locations"], b["locations"]
    cols = ["row", "col"]
    key_a = [tuple(row) for row in frame_a[cols].itertuples(index=False, name=None)]
    key_b = [tuple(row) for row in frame_b[cols].itertuples(index=False, name=None)]
    n_common_positions = len(set(key_a) & set(key_b))
    n_aligned_locations = sum(x == y for x, y in zip(key_a, key_b))
    names_a, names_b = list(a["endmembers"].columns[1:]), list(b["endmembers"].columns[1:])
    shared = sorted(set(names_a) & set(names_b))
    em_diffs = {
        name: float(np.max(np.abs(
            a["endmembers"][name].to_numpy(float)
            - b["endmembers"][name].to_numpy(float)
        ))) if len(a["endmembers"]) == len(b["endmembers"]) else None
        for name in shared
    }
    em_equal = (
        set(names_a) == set(names_b)
        and len(a["endmembers"]) == len(b["endmembers"])
        and np.array_equal(a["endmembers"]["wavelength_um"], b["endmembers"]["wavelength_um"])
        and all(x == 0.0 for x in em_diffs.values())
    )
    ma, mb = a["mask3_endmembers"], b["mask3_endmembers"]
    mask3_equal = ma.equals(mb)
    selected_a, selected_b = a["bands"].get("wavelengths_um", []), b["bands"].get("wavelengths_um", [])
    overlap = len(set(selected_a) & set(selected_b))
    return {
        "candidate_count_a": int(sa.shape[0]),
        "candidate_count_b": int(sb.shape[0]),
        "candidate_shape_equal": same_shape,
        "candidates_equal_exact": bool(same_shape and np.array_equal(sa, sb)),
        "candidate_rows_exactly_equal_at_same_index": n_aligned,
        "candidate_locations_equal_at_same_index": n_aligned_locations,
        "candidate_locations_shared_order_independent": n_common_positions,
        "candidate_max_abs_reflectance_difference_at_same_index": max_abs,
        "candidate_metadata_equal_exact": bool(frame_a.equals(frame_b)),
        "candidate_wavelengths_equal": bool(np.array_equal(a["wavelengths"], b["wavelengths"])),
        "original_band_indices_equal": bool(np.array_equal(a["original_indices"], b["original_indices"])),
        "endmember_names_a": names_a,
        "endmember_names_b": names_b,
        "endmembers_equal_exact_by_name": bool(em_equal),
        "mask3_endmembers_equal_exact": bool(mask3_equal),
        "endmember_max_abs_reflectance_difference_by_shared_name": em_diffs,
        "fallback_classes_a": a["summary"].get("fallback_selected_classes", []),
        "fallback_classes_b": b["summary"].get("fallback_selected_classes", []),
        "optimized_bands_a": selected_a,
        "optimized_bands_b": selected_b,
        "optimized_band_overlap_count": overlap,
    }


def run_case(name, nproj, ncomb, *, args, root, env):
    case = root / name
    case.mkdir(parents=True, exist_ok=False)
    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("Base configuration must be a mapping")
    cfg.setdefault("extraction", {})["N_RANDOM_PROJECTIONS"] = nproj
    cfg.setdefault("bands", {})["N_RANDOM_COMBINATIONS"] = ncomb
    cfg["seed"] = args.seed
    cfg_file = case / "case_config.yml"
    cfg_file.write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
    output = case / "products"
    command = [
        sys.executable, str(args.processor),
        "--input-catalog", str(args.input_catalog),
        "--gusl", str(args.gusl),
        "--config", str(cfg_file),
        "--output-dir", str(output),
    ]
    print(f"[RUN] {name}: PPI directions={nproj:,}, band combinations={ncomb:,}", flush=True)
    t0 = time.monotonic()
    result = subprocess.run(command, env=env, cwd=args.repository_root,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", check=False)
    elapsed = time.monotonic() - t0
    (case / "processor.log").write_text(result.stdout, encoding="utf-8")
    print(f"[RUN] {name}: exit={result.returncode}; elapsed={elapsed:.1f}s", flush=True)
    if result.returncode:
        print(result.stdout[-4500:], flush=True)
        raise RuntimeError(f"Case {name} failed (see {case / 'processor.log'})")
    info = read_case(output)
    s = info["summary"]
    if s.get("version") != "0.3.2":
        raise AssertionError(f"Expected v0.3.2, got {s.get('version')}")
    if s.get("mask3_reselection") is not True or s.get("endmember_selection") != "FULL+MASK3":
        raise AssertionError("The processor did not use FULL-only endmembers")
    if s.get("selected_bands") != 15:
        raise AssertionError("Expected exactly 15 independent selected bands")
    if info["spectra"].shape[1] != len(info["endmembers"]):
        raise AssertionError("Candidate and final endmember wavelength dimensions disagree")
    info["run_data"] = {"name": name, "n_ppi_directions": nproj, "n_band_combinations": ncomb,
                        "elapsed_seconds": round(elapsed, 2),
                        "candidate_spectra_sha256": hashlib.sha256(info["spectra"].tobytes()).hexdigest(),
                        "endmember_count": len(info["endmembers"].columns) - 1,
                        "candidate_count": int(info["spectra"].shape[0]),
                        "fallback_selected_classes": s.get("fallback_selected_classes", []),
                        "fallback_unresolved_classes": s.get("fallback_unresolved_classes", [])}
    (case / "case_summary.json").write_text(json.dumps(info["run_data"], indent=2) + "\n")
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--input-catalog", type=Path, default=Path("examples/sepolia"))
    parser.add_argument("--gusl", type=Path, default=Path("examples/resources/GUSL_spectra_by_material_headers.xlsx"))
    parser.add_argument("--config", type=Path, default=Path("examples/config_sepolia_report.json"))
    parser.add_argument("--processor", type=Path, default=Path("class_guided_processor.py"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/reproducibility_audit"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    args.repository_root = args.repository_root.resolve()
    for name in ("input_catalog", "gusl", "config", "processor"):
        value = getattr(args, name)
        setattr(args, name, value if value.is_absolute() else args.repository_root / value)
    args.output_dir = args.output_dir if args.output_dir.is_absolute() else args.repository_root / args.output_dir
    root = args.output_dir
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError(f"Audit output directory must start empty: {root}")
    env = os.environ.copy()
    env.update({"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1"})
    environment = {"python": sys.version, "platform": platform.platform(),
                   "processor": str(args.processor.relative_to(args.repository_root)),
                   "image_catalog": str(args.input_catalog.relative_to(args.repository_root)),
                   "gusl": str(args.gusl.relative_to(args.repository_root)),
                   "environment": {k:env[k] for k in ("PYTHONHASHSEED","OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS")}}
    (root / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
    print("[AUDIT] Same runner; pinned Python; separate child processes; controlled seed and threads.", flush=True)
    cases = {}
    comparisons = {}
    failure = None
    try:
        for name, nproj, ncomb in CASES:
            cases[name] = run_case(name, nproj, ncomb, args=args, root=root, env=env)
        comparisons["repeat_2000_vs_repeat_2000"] = compare_cases(cases["baseline_A"], cases["baseline_B"])
        comparisons["bands_2000_vs_500000"] = compare_cases(cases["baseline_A"], cases["bands_500000"])
        comparisons["ppi_directions_2000_vs_10000"] = compare_cases(cases["baseline_A"], cases["ppi_10000"])
        for name in ("repeat_2000_vs_repeat_2000", "bands_2000_vs_500000"):
            m = comparisons[name]
            if not (m["candidates_equal_exact"] and m["candidate_metadata_equal_exact"]
                    and m["candidate_wavelengths_equal"] and m["original_band_indices_equal"]
                    and m["endmembers_equal_exact_by_name"] and m["mask3_endmembers_equal_exact"]):
                failure = (failure or []) + [name]
    except Exception as exc:
        failure = (failure or []) + [f"audit_exception: {type(exc).__name__}: {exc}"]
        print(f"[AUDIT] Failure during execution: {exc}", file=sys.stderr)
    finally:
        report = {"workflow": "HEATWISE v0.3.2 reproducibility and PPI sensitivity",
                  "environment": environment,
                  "cases": {k: v["run_data"] for k,v in cases.items()},
                  "comparisons": comparisons,
                  "strict_invariants_failed": failure or [],
                  "interpretation": (
                      "Repeated identical runs and a change in the LATER band-search count MUST preserve the FULL candidates and endmembers. "
                      "Changing the EARLIER PPI projection count may change candidates; it is a sensitivity experiment, not a failure. "
                      "A failure in separate GitHub runs but not on the same runner suggests environment-dependent numerical behavior; it does not prove causation."
                  )}
        (root / "audit_report.json").write_text(json.dumps(jsonable(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("[AUDIT] Comparison summary:", flush=True)
        for name, value in comparisons.items():
            print("  ", name,
                  f"candidates_equal={value['candidates_equal_exact']}",
                  f"matched_positions={value['candidate_rows_exactly_equal_at_same_index']}",
                  f"endmembers_equal={value['endmembers_equal_exact_by_name']}",
                  f"15band_overlap={value['optimized_band_overlap_count']}/15", flush=True)
        print(f"[AUDIT] Strict invariant failures: {report['strict_invariants_failed']}", flush=True)
    return 2 if failure else 0


if __name__ == "__main__":
    sys.exit(main())
