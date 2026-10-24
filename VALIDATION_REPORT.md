# Validation report — review build 0.1.0

**Conclusion:** a functioning integrated processor and synthetic end-to-end EOAP
prototype are delivered. This is **not** a fully validated ESA release and does not
reproduce or validate HEATWISE real-scene accuracy claims.

## Implemented

- Actual in-process integration of extraction, class-guided matching and mandatory
  band selection; no subprocess calls to the three original algorithms.
- FULL selection followed by dynamic MASK3 optimization and actual re-matching.
- Original SAM/MBDSA, top-K competition, asphalt/concrete bundles and class averages.
- Configurable report-sized band settings (100/15/500,000/100/15/0.040 µm).
- Registered numeric-suffix grouping, covariance eligibility and Euclidean fallback.
- Aligned final XLSX, physical-reflectance COG, band-index JSON and wavelength text.
- Source masks, nodata, grid/CRS preservation and explicit source scale/offset.
- Instance-scoped parameters, seed, dependency versions, input hashes and diagnostics.
- Workflow CWL, CommandLineTools, explicit base commands, Docker declarations,
  staged STAC input and relative output catalog/assets.
- Full workflow calling the existing upstream FCLS, with endmember and material-summed
  abundance/classification products. No FCLS algorithm replacement.
- Dockerfile, reproducible Python 3.11 dependency freeze, examples and tests.

## Tests actually executed

| Test | Result | Evidence |
|---|---|---|
| Python syntax compilation | PASS | Processor compiled before execution; modules imported in tests |
| Python 3.11 dependency installation | PASS after correction | `validation/python311_dependencies.log`, `final_environment_setup.log` |
| Unit/regression/integration tests | 19 PASS; 0 final failures | `validation/pytest_final.log`; earlier `pytest_python311.log` |
| Original-kernel parity on synthetic inputs | PASS | Tests cover PCA/PPI, local pruning, global-finite SAM/MBDSA, PCHIP, class assignment, bundles, single-band scores and both combination metrics |
| Excel unordered-row regression | PASS | Test demonstrates original double-permutation defect and corrected correspondence |
| Small synthetic complete processor | PASS | 66 candidates, 15 output bands, 9 final endmembers including vegetation |
| Report-sized band search | PASS on SYNTHETIC data | `validation/python311_500k.log`, `examples/output_500k/selected_bands.json` |
| Same-seed reproducibility | PASS | Two independent end-to-end synthetic runs produce identical selection JSON, spectral tables and run summaries |
| Image value/grid preservation | PASS | End-to-end test checks selected source pixels including NaNs, CRS, shape and transform |
| Nodata, absent metadata, duplicate/bad wavelengths | PASS | Unit and integration tests; wholly invalid band excluded |
| Misaligned wavelength text | PASS (expected rejection) | Alignment regression test |
| Material grouping | PASS | `_1`, `_2`, `_3` and `__1` supported for registered classes; distinct material names preserved |
| CWL static validation | PASS | `validation/cwl_validate_final.log` / original `cwl_validate.log` |
| Full CWL host execution | PASS with documented telemetry workaround | `validation/cwl_python311_final.log` reports final success |
| Ordinary host cwltool execution in this environment | FAILED due to process-monitor/PID visibility | `validation/cwl_standard_python311.log` |
| Strict COG structure validation | PASS for five final rasters | `validation/output_checks_final.json` / `output_checks.json` |
| STAC core schema validation | PASS, one Item | Output checks validate catalog/Item using PySTAC/jsonschema |
| Relative STAC asset links | PASS, 14 assets exist | Output checks, also after relocating packaged example output |
| FCLS nonnegativity and sum-to-one | PASS | 1,950 valid synthetic pixels; 0 solver failures, success rate 1.0 |
| Docker build/run | NOT EXECUTED | Docker executable/daemon unavailable |
| Containerized CWL / target ESA platform | NOT EXECUTED | Pending actual platform and Docker access |
| Real Sepolia, full GUSL and historical wavelengths | NOT EXECUTED | Required real input pair not supplied locally |
| Real classification/abundance accuracy | NOT EXECUTED | No ground truth validation run; no accuracy claim |

Final tests ran on Python **3.11.17**, NumPy **2.2.6**, SciPy **1.15.3**,
Rasterio **1.4.3** / GDAL **3.9.3**, pandas **2.2.3**, scikit-learn **1.6.1**,
openpyxl **3.1.5** and PySTAC **1.15.2**. Initial exploratory tests also ran on
Python 3.12; their logs remain but do not replace the Python 3.11 checks.

## What the synthetic tests do and do not establish

The generated image contains five constructed spectral materials, smooth brightness
variation, small noise, an all-nodata band, per-pixel missing data and georeferencing.
The synthetic two-sheet library deliberately stores wavelength rows in reverse order.
This exercises the actual extraction/matching/band-selection workflow and its data
contracts. It is not a realistic substitute for GUSL or a validation of spectral
classification accuracy on urban scenes.

The 500,000-combination run uses the requested band-selection settings but the fast
synthetic extraction settings (100 projections), not the default 2,000 projections.
It found 15 bands and nine endmembers. Do not attribute report accuracies to it.
The smaller same-seed integration test uses 200 combinations and 25 projections.
Numerical equivalence of the optimized combination evaluator is checked against the
original functions with relative tolerance 2e-6, absolute tolerance 1e-7.

The 118-band effective FULL domain in the fixture differs from its 119 usable image
bands because the original float32 library grid rounds an endpoint. That original
no-extrapolation behavior is preserved and documented, not hidden.

## Failures encountered and disposition

1. **Original Excel double sorting:** confirmed scientifically relevant source defect;
   corrected and covered by a regression test.
2. **Original vegetation exclusion:** conflicts with expecting a vegetation endmember.
   Default separate extraction branch added explicitly; original urban-only mode retained.
3. **Prototype integration defects:** missing class-prefix configuration and an unsupported
   PySTAC method were found in initial runs and corrected before the passing tests.
4. **Initial dependency set:** Rasterio 1.5.2 requires Python >=3.12; rejected during
   Python 3.11 resolution and replaced with 1.4.3 and a compatible pinned stack.
5. **CWL `--no-container` with required Docker:** correctly rejected. A separate host-only
   CWL variant removes DockerRequirement solely for host tests; deployment CWL retains it.
6. **Host cwltool psutil error:** this environment intermittently hides child PIDs.
   Ordinary cwltool failed even when preprocessing succeeded. The included host runner
   catches `psutil.NoSuchProcess` only in memory monitoring and calls `Popen.wait()`;
   it does not skip a scientific step or change output/exit-code validation. The full
   workflow passed with that workaround. Normal-host cwltool must still be verified.
7. **Overlapping staged inputs:** GUSL nested inside the STAC Directory and independently
   staged as File caused a missing staged path. The example now stages a separate copy
   outside that Directory, consistent with GUSL being an independent external resource.
8. **Missing validation extra:** jsonschema was installed and pinned before successful
   STAC schema validation. It is included in the final developer requirements/lock.

Warnings in the final pytest run are dependency deprecations, not test failures.
Historical failed-run logs are retained to make this record auditable.

## Scientific checks still required

- Run the real Sepolia image with the actual complete GUSL workbook, exact source
  processing version and historical configuration. The official repository includes
  a Sepolia sample raster, but the needed complete GUSL pair was not available here.
- Compare candidate coordinates, spectra, class assignments and endmember identities
  stage by stage, not only the final band list.
- Quantify the effects of the fixed Excel sorting, added vegetation pool, FULL-common
  domain restriction, deterministic tie handling and default band-setting change.
- Use `tools/compare_historical_bands.py` on a real run. The supplied 15 historical
  wavelengths are a reference only; they are never injected into selection.
- Assess global intersection coverage, internal missing-knot interpolation, TOP_K
  competition truncation and optimistic missing-opponent margins in the actual GUSL.
- Check bundle conditioning, abundance uncertainty and material-level classification.
- Evaluate multiple cities/sensors; no scene independence claim beyond configuration
  and removal of location-specific hardcoded paths has been empirically validated.
- Validate resource scaling for large scenes. Extraction still reads a full cube.

## Actions required before declaring ESA-ready

1. Obtain project approval for the explicit scientific changes in `docs/CHANGES.md`.
2. Complete real-scene reproduction and accuracy/uncertainty evaluation.
3. Build/test Docker on supported Linux systems and run the containerized CWL workflow.
4. Publish an authorized image, pin registry/base-image digests and finalize release locks.
5. Exercise HEATWISE/ESA stage-in, STAC profile, execution and stage-out interoperability.
6. Verify licensing for source code, GUSL access/distribution and bundled upstream files.
7. Review logs, missing-class policies, input metadata expectations and version the release.

No GitHub changes, publication, main-branch edits or remote writes were performed.
