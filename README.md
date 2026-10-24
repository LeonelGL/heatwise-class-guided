# HEATWISE class-guided processor

A unified scientific preprocessor for scene-specific hyperspectral endmembers and
bands, connected to the existing HEATWISE FCLS implementation. Python 3.11.

**Status: functional and tested on synthetic data; not yet qualified for ESA delivery.**
Real-scene/GUSL reproduction, Docker execution and target-platform acceptance remain
pending. Read `VALIDATION_REPORT.md` before interpreting the example outputs.

## What it does

1. Extract stratified PCA/PPI-like scene candidates and prune/deduplicate them.
2. Interpolate GUSL onto the image grid with PCHIP, without endpoint extrapolation.
3. Assign classes with SAM, rank with MBDSA, select FULL endmembers including bundles.
4. Optimize spectral bands through separability, combinations and frequency analysis.
5. Re-run matching and endmember selection on the resulting scene-specific MASK3.
6. Export aligned endmembers, reduced physical-reflectance COG and metadata.
7. Optionally run the unchanged official FCLS and emit endmember/material maps and STAC.

The original scripts are reference material only; they are not required at runtime.
No ground-truth input is used. No fixed Sepolia wavelength list is used in selection.

## Install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock-python311.txt
```

On Windows activate with `.venv\Scripts\activate`. The complete tested environment
is pinned in the lock file; `requirements.txt` contains direct runtime dependencies,
`requirements-dev.txt` adds validation tools. The lock is an environment freeze,
not a cryptographically hashed supply-chain lock. The Docker base tag is also not
pinned to a digest yet. These are release-hardening tasks, not validation claims.

## Run your scene

Edit `config.json`, especially GUSL sheet names, explicit scene gaps and material
prefixes. For direct image input, provide the true acquisition datetime in config.
If tags lack trustworthy centers, provide one wavelength in µm per original band.

```bash
python class_guided_processor.py \
  --image /data/scene_COG.tif \
  --gusl /data/GUSL_spectra_by_material_headers.xlsx \
  --config config.json \
  --wavelengths /data/wavelengths_um.txt \
  --output-dir results/my_scene
```

Or use staged STAC, carrying the source acquisition time:

```bash
python class_guided_processor.py \
  --input-catalog /data/scene_catalog \
  --gusl /data/GUSL_spectra_by_material_headers.xlsx \
  --config config.json --output-dir results/my_scene
```

`--input-catalog` expects `catalog.json`, exactly one Item and one COG asset.
`--asset-key` disambiguates multiple assets. Relative asset hrefs resolve against
the Item location. Remote assets must be staged by the platform first. GUSL is an
explicit independent CWL File, not embedded in the image or inferred from validation.
Keep the staged GUSL File outside the supplied STAC Directory to avoid overlapping
File/Directory staging in runners.

Output directories must be empty or nonexistent. Inputs are never edited. A failed
run may leave diagnostic files; use a new directory for a retry. Success is indicated
by exit code 0, not merely by the existence of some files.

## Configuration

All stage settings are in editable JSON (YAML is also accepted). Unknown configuration
keys fail. CLI overrides include:

```bash
python class_guided_processor.py --input-catalog /data/catalog \
  --gusl /data/gusl.xlsx --config config.json --output-dir results/scene \
  --seed 42 --preselect-top-bands 100 --bands-per-combo 15 \
  --n-random-combinations 500000 --top-n-combinations 100 \
  --n-final-bands 15 --min-spacing-um 0.040
```

Default `vegetation_mode=separate` explicitly extends the original urban-only
extractor. Use `urban_only` for its original NDVI exclusion, or `all` for brightness
stratification without NDVI (e.g. sensors lacking the required red/NIR bands).
`required_classes` can make missing materials fatal; by default missing classes are
reported and absent columns are omitted. `class_mapping` explicitly maps endmember
names to materials if the registered numeric-suffix rule is insufficient.

Example configurations:

- `config.json`: generic scene, report band-selection parameters, no hardcoded gap.
- `examples/config_sepolia_report.json`: same with the supplied Sepolia gap.
- `examples/config_legacy_urban_dynamic_mask.json`: original urban exclusion and
  supplied selector parameters, but still the NEW dynamic MASK3 workflow; not a
  claim of historical reproducibility.
- `examples/synthetic_config.json`: fast testing only (1,500 combinations).

FULL comparison uses the original GLOBAL finite-band intersection over GUSL. The
selector is restricted to that effective domain, and MASK3 must use all selected
bands. Poor library coverage causes an informative failure; it does not trigger
undocumented extrapolation or pairwise similarity changes.

## Products

| Product | Meaning |
|---|---|
| `EndmembersFinales_mask3.xlsx` | Wavelength rows, one column per final endmember; first sheet compatible with official FCLS |
| `hyperspectral_mask3_COG.tif` | Selected original bands, same grid/CRS, physical reflectance |
| `mask3_wavelengths_um.txt` | Exactly the reduced image centers, in the same order |
| `selected_bands.json` | Actual wavelengths, original base-0/base-1 indices, effective FULL domain, scores, grouping, seed and configuration |
| `Endmembers_FULL.xlsx` | FULL selection used by the band selector |
| `band_selection.xlsx` | Single-band scores, top combinations, frequencies and final recommendations |
| `endmember_classes.json` | Endmember-to-material grouping |
| `effective_config.json`, `run_summary.json` | Parameters, input SHA256, library versions, counts and missing classes |
| `diagnostics/` | Candidate locations, class assignments, averaging/bundle provenance; optional matrices and NPZ arrays |
| `catalog.json`, `item.json` | Relative, self-contained STAC references to products |

The selector can use diagonal Bhattacharyya only if **every** material has at least
two final signatures. The typical 3+3+1+1+1 bundle therefore uses standardized
Euclidean distance. It does not pretend that one averaged endmember is a sample set.

## Synthetic example and tests

```bash
python examples/make_synthetic.py
python class_guided_processor.py \
  --input-catalog examples/synthetic --gusl examples/gusl_synthetic.xlsx \
  --config examples/synthetic_config.json --output-dir results/synthetic
python -m pytest tests -q
python tools/validate_outputs.py examples/output
```

Included `examples/output/` contains a completed Python 3.11 CWL+FCLS run.
`examples/output_500k/` contains the preprocessing run with the requested 100/15/
500,000/100/15/0.040 band settings, but synthetic extraction and synthetic library.
Neither folder represents Sepolia or real GUSL validation.

## Existing FCLS integration

```bash
python fcls_adapter.py --prepared results/synthetic \
  --upstream upstream --output-dir results/fcls
```

The adapter imports the reviewed processor and FCLS core in `upstream/`, pinned to
commit `c97ae3d3c0d8140069733750f448521b30b920ed`. It does not implement a replacement
optimizer. It produces abundance/classification COGs and additional material-summed
products. Endmember labels and material labels are distinct and recorded in
`fcls_run.json`. The original FCLS fallback and convergence reporting remain intact.

For direct use of the official CLI instead:

```bash
PYTHONPATH=upstream/src python upstream/processor.py \
  --input-image results/synthetic/hyperspectral_mask3_COG.tif \
  --endmembers results/synthetic/EndmembersFinales_mask3.xlsx \
  --wavelengths-txt results/synthetic/mask3_wavelengths_um.txt \
  --output-dir results/official_fcls --scale-factor 1.0
```

The supplied adapter fixes packaging metadata externally; the upstream CLI's STAC
limitations are described in `docs/EOAP.md`.

## Docker and CWL

Docker was unavailable during development. These commands are prepared, not claimed
as successfully executed:

```bash
docker build -t heatwise/class-guided:0.1.0 .
docker run --rm -v "$PWD:/work" -w /work heatwise/class-guided:0.1.0 \
  python3 /app/class_guided_processor.py \
  --input-catalog examples/synthetic --gusl examples/gusl_synthetic.xlsx \
  --config examples/synthetic_config.json --output-dir results/docker
python -m cwltool --validate cwl/full_workflow.cwl
python -m cwltool --outdir results/cwl cwl/full_workflow.cwl examples/job_synthetic.yml
```

Use `cwl/workflow.cwl` for preprocessing only; `cwl/full_workflow.cwl` adds FCLS.
Both are Workflow documents, with explicit CommandLineTools/baseCommand and
DockerRequirement. The image reference is a **local build tag**, not a published
registry image. Before ESA deployment publish an authorized image and replace it
with a registry reference pinned to a digest.

Host-only testing uses a generated variant removing only DockerRequirement:

```bash
python tools/local_cwl.py
python -m cwltool --no-container --preserve-environment PATH \
  --outdir results/host cwl/local/full_workflow.cwl examples/job_synthetic.yml
```

In this managed environment, ordinary cwltool's psutil child-PID monitoring failed.
The tested invocation used `tools/cwl_host_runner.py` in place of `python -m cwltool`.
It catches only the unavailable process-monitor telemetry and waits for the process;
scientific commands, data staging, outputs and exit status still run through cwltool.
See the validation report; this is not equivalent to a Docker/platform test.

## Reading order

1. `VALIDATION_REPORT.md`: what actually ran and release blockers.
2. `docs/CHANGES.md`: scientific preservation, fixes and explicit behavioral changes.
3. `docs/EOAP.md`: repository review, package organization and interoperability.

Memory currently scales with the full image cube plus matching/combinations. COG
export is windowed, but extraction is not an out-of-core implementation. Very large
scenes need resource sizing and separate performance validation. Random seed and
pinned dependencies improve reproducibility; exact bitwise agreement across BLAS,
CPU or dependency versions is not promised. Original code and upstream redistribution
rights must be confirmed by the project before public release; no license is invented.
