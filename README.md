# HEATWISE class-guided endmember and band preprocessor

**Version 0.3.0 — FULL endmember selection, independent spectral band selection**

This repository implements a scene-specific, ground-truth-independent workflow
for hyperspectral urban material characterization. It prepares two scientific
products for a CHIME-like scene. It **does not perform FCLS unmixing**.

## Scientific methodology

1. Read an input hyperspectral GeoTIFF/COG with valid wavelength centers,
   reflectance scale/offset, georeferencing and nodata masks.
2. Detect usable spectral bands; exclude explicitly configured gaps and bands
   with inadequate finite-data coverage.
3. Extract scene-based candidate endmembers using PCA, stratified PPI-like
   projections, local spectral support, medoid representation and deduplication.
4. Interpolate configured GUSL spectral-library sheets onto the usable scene
   wavelengths with PCHIP, without endpoint extrapolation.
5. **Match candidates to GUSL using FULL spectra**, with SAM/MBDSA and
   class-guided material selection. Asphalt and concrete may retain multiple
   scene endmembers; some other material classes are averages of candidates.
6. Export the selected endmembers with **all usable spectral wavelengths**.
7. Independently optimize 15 discriminative bands from the already-selected
   FULL endmembers. **Do not rerun matching or alter endmembers**.

The default report configuration evaluates 500,000 15-band combinations drawn
from 100 preselected bands and then recommends 15 wavelengths subject to at least
0.040 µm spacing. The scene determines the wavelengths dynamically.

**Important spectral limitation:** the current FULL SAM/MBDSA kernel uses a
single global common-finite-band intersection across retained candidates and
library signatures. `full_metric_bands` can be smaller than the number of
usable image bands, although final endmember signatures retain the complete
usable scene grid. This limitation is documented and must be assessed on real
Sepolia/GUSL inputs.

The word FULL distinguishes this workflow from the historical second-pass
MASK3 method. There is **no MASK3 re-matching** in version 0.3.0.

## Scientific outputs: exactly two

| File | Description | Consumer |
| --- | --- | --- |
| `selected_endmembers.xlsx` | Wavelengths in µm (first column) and one reflectance column per FULL-selected endmember; all usable scene wavelengths | External official FCLS processor |
| `selected_bands.json` | The independently optimized 15 wavelengths, original raster band indices (zero- and one-based), selection indices and methodological diagnostics | Spectral band analysis; **not an FCLS input** |

A separate `diagnostics/` folder, configuration, run summary and a
`catalog.json`/`item.json` STAC catalog support reproducibility and ESA-style
stage-out. These are **supporting files, not additional scientific products**.

The output directory contains **no reduced image**, no MASK3 endmember
spreadsheet, no `.mat` data, and no abundance/classification rasters.
The input raster is **not copied or modified**.

## Installation

Python 3.11 is recommended. Use the pinned dependency lock:

```bash
python3.11 -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock-python311.txt
```

## Usage with the real scene

Example (adjust paths; files are not included in the repository):

```bash
python class_guided_processor.py \
  --image /data/Sepolia_CHIME_v2.tif \
  --gusl /data/GUSL_spectra_by_material_headers.xlsx \
  --config examples/config_sepolia_report.json \
  --output-dir results/sepolia
```

For direct `--image` input, set `acquisition_datetime` in the configuration to
the actual acquisition timestamp **with timezone**, not to processing time.
The reported Sepolia acquisition **date** is 2009-07-18; the precise acquisition
time/timezone must be verified rather than guessed.

If band centers are not in the raster metadata, supply:

```bash
--wavelengths /data/sepolia_original_wavelengths_um.txt
```

The file must contain one wavelength center in **micrometers** for each
original image band, in original raster order. Image and endmember wavelengths
are sorted consistently during processing.

To use a staged STAC input:

```bash
python class_guided_processor.py \
  --input-catalog /data/staged_catalog \
  --gusl /data/GUSL_spectra_by_material_headers.xlsx \
  --config examples/config_sepolia_report.json \
  --output-dir results/sepolia
```

The STAC catalog must describe one Item with a locally staged COG asset.
Choose a new or empty output directory.

**GUSL source convention:** the current reader uses the configured
`BRUSSELS_APEX_GENLIB` and `DLR` sheets from the XLSX. The separate
`GUSL_catalog_all.csv` is **not yet parsed by this executable**. Its potential
role in materials mapping must be audited before claiming both resources are
integrated. Verify sheet names, material prefixes, gap intervals and image
wavelengths against the real Sepolia inputs.

## Scientific interface with the ESA HEATWISE unmixing package

The external repository
[ESA-Heatwise/heatwise-hysupp-unmixing](https://github.com/ESA-Heatwise/heatwise-hysupp-unmixing)
remains **unchanged**. It accepts the original input image and the exported
endmember table. The independently selected 15-band JSON is **not passed** to
the official FCLS processor.

Do **not** pass a MASK3 raster, do **not** set a fabricated scale factor, and do
**not** assume all sensor bands are usable. Spectral alignment, interpolation
behaviour and radiometric scale must be verified with the actual original
image and the official FCLS interface before claiming real-scene compatibility.

## Synthetic test and EOAP/CWL

```bash
python examples/make_synthetic.py
python class_guided_processor.py --input-catalog examples/synthetic \
  --gusl examples/gusl_synthetic.xlsx \
  --config examples/synthetic_config.json \
  --output-dir results/synthetic
python tools/validate_outputs.py results/synthetic
python -m pytest tests -q
python -m cwltool --validate cwl/workflow.cwl
python -m cwltool --validate cwl/local/workflow.cwl
```

Build a local image (the tag is not evidence of a published registry image):

```bash
docker build -t heatwise/class-guided:0.3.0 .
python -m cwltool --outdir results/cwl cwl/workflow.cwl examples/job_synthetic.yml
python tools/validate_outputs.py results/cwl/results
```

`cwl/workflow.cwl` is the container workflow; `cwl/local/workflow.cwl`
runs without Docker. GitHub Actions tests both declarations and runs the
containerized synthetic workflow. It does not execute official FCLS.

The `examples/output`, `examples/output_250`, and `examples/output_500k`
folders, if present, are **historical synthetic outputs of the old interface**
and must **not** be treated as examples generated by version 0.3.0.
Their legacy MASK3 content is not part of the current output contract.

## Validation and release status

See `VALIDATION_REPORT.md`, `docs/CHANGES.md`, `docs/EOAP.md` and
`docs/EOAP_READINESS.md` for reproducibility, algorithmic limitations and
ESA-facing packaging requirements.

Previously reported CI successes refer to **version 0.2.0**, not to this
new workflow. Tests/CI must be rerun after every update. Validation with the
actual Sepolia CHIME-like v2 scene and complete GUSL resources, a registry
image pinned by digest, platform stage-in/stage-out and scientific accuracy
evaluation remain pending. No ESA qualification is claimed.
