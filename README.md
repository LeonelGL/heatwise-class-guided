# HEATWISE class-guided endmember and band preprocessor

**Version 0.3.2 — dual FULL / MASK3 class-guided endmember selection**

This repository implements a scene-specific, ground-truth-independent workflow
for hyperspectral urban material characterization. It exports separately selected FULL and MASK3 endmember libraries and a scene-specific selection of 15 discriminative bands. It **does not perform FCLS unmixing**.

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
6. Apply a **general class-conditional fallback** to any class in
   `matching.FINAL_TARGET_CLASSES` that remains unrepresented. It ranks all
   scene candidates against all GUSL signatures of the missing class using
   the same FULL spectral comparison matrices. A fallback can relax the
   requirement that this class be the candidate's global winner, but requires
   a configurable class-specific SAM ceiling (default 8 degrees), cannot
   steal candidates used by existing endmembers, and cannot reuse a fallback
   candidate for multiple classes. A class without a plausible candidate
   remains unrepresented and is explicitly reported. The recovered spectrum
   is a scene-derived candidate, not a copied GUSL spectrum. These are
   provisional material labels, **not independently validated identities**.
7. Independently optimize 15 discriminative bands from the FULL-selected endmembers.
8. **Rerun class-guided matching on the original candidate pool using only these 15
   bands (MASK3)**, including mode-specific quality flags and fallback decisions.
9. Export separate FULL and MASK3 endmember libraries, both retaining **all usable
   spectral wavelengths**, not just the 15 matching bands.

The default report configuration evaluates 500,000 15-band combinations drawn
from 100 preselected bands and then recommends 15 wavelengths subject to at least
0.040 µm spacing. The scene determines the wavelengths dynamically.

**Important spectral limitation:** the current FULL SAM/MBDSA kernel uses a
single global common-finite-band intersection across retained candidates and
library signatures. `full_metric_bands` can be smaller than the number of
usable image bands, although final endmember signatures retain the complete
usable scene grid. This limitation is documented and must be assessed on real
Sepolia/GUSL inputs.

FULL matching uses the global set of common finite spectral bands, while MASK3
uses the 15 selected bands to reassess and reselect endmembers independently.
The 15-band selection **does not change the already selected FULL endmembers**.

## Outputs and FCLS interoperability

| Output file | Description |
| --- | --- |
| `selected_endmembers_FULL.xlsx` | FULL-selected endmember spectra, all usable scene wavelengths. |
| `selected_endmembers_MASK3.xlsx` | Independently MASK3-selected endmember spectra, all usable scene wavelengths. |
| `selected_endmembers.xlsx` | Backward-compatible alias identical to the FULL spreadsheet; preserves the existing ESA HySUPP input contract. |
| `selected_bands.json` | The 15 optimized wavelengths, raster band indices and selection diagnostics. |
| `mask3_matching_bands.json` | The 15 actual wavelengths and indices used in MASK3 matching. |

All endmember spreadsheets contain a first wavelength column (`wavelength_um`)
and one reflectance column per selected endmember. These are **scene-derived
candidate signatures**, not direct exports of GUSL spectra. Some classes have
multiple endmembers. Fallback class identities are explicitly marked
provisional in the diagnostics.

Additional `diagnostics/` files, `run_summary.json`, `effective_config.json`,
and STAC `catalog.json` / `item.json` provide reproducibility information.
This program does not create a reduced-band raster, abundance maps,
classification maps, or a `.mat` file. It does not modify the source image.

The separate official [ESA-Heatwise HySUPP unmixing
processor](https://github.com/ESA-Heatwise/heatwise-hysupp-unmixing) accepts
the original image and an endmember XLSX. FULL and MASK3 may each be
evaluated as **alternative endmember inputs**. The selected-band JSON is
diagnostic, **not a required FCLS input**. A spectral alignment preflight
has been performed; actual end-to-end FCLS operation and scientific
accuracy remain to be independently verified.

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

Example using the Sepolia test assets currently in this repository (confirm
rights to redistribute the real GUSL library before an external release):

```bash
python class_guided_processor.py \
  --input-catalog /data/sepolia_stac \
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
remains **unchanged**. It accepts the original input image and either exported
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
docker build -t heatwise/class-guided:0.3.2 .
python -m cwltool --outdir results/cwl cwl/workflow.cwl examples/job_synthetic.yml
python tools/validate_outputs.py results/cwl/results
```

`cwl/workflow.cwl` is the container workflow; `cwl/local/workflow.cwl`
runs without Docker. GitHub Actions tests both declarations and runs the
containerized synthetic workflow. It does not execute official FCLS.

The `examples/output`, `examples/output_250`, and `examples/output_500k`
folders, if present, are **historical outputs of older interfaces**
and must **not** be treated as outputs of version 0.3.2.

## Real Sepolia validation and ESA delivery status

The current branch `feature/dual-full-mask3` passed:

- [Python, Docker/CWL and synthetic validation (run 40742619588)](https://github.com/LeonelGL/heatwise-class-guided/actions/runs/40742619588).
- [Real Sepolia CHIME-like v2 and GUSL FULL/MASK3 preflight (run 40743012798)](https://github.com/LeonelGL/heatwise-class-guided/actions/runs/40743012798).

The latter used the Sepolia-specific configuration with 20,000 random PPI
projections, up to 1,000 PPI candidates per stratum, 300 maximum final urban
candidates, and 500,000 sampled combinations of 15 bands. It reported
250 input image bands, 124 usable output wavelengths, 103 FULL/GUSL
comparison bands, 15 MASK3 comparison bands, and 9 endmember signatures
per library. A total of 277 scene candidates entered matching.
These settings are **not universal defaults**; see
`examples/config_sepolia_report.json`.

These successful checks establish executable behavior and the **spectral
FCLS handoff preflight only**. They do not establish independently validated
material classes, FCLS abundance accuracy, full-system interoperability,
or ESA acceptance. Earlier independent executions showed changes in some
FULL candidates with nominally unchanged upstream settings; repeatability
should be audited before claiming bitwise deterministic results.

The official delivery must meet the EO Application Package (EOAP)
requirements. In particular, ESA requests a **fixed-version GitHub Release
with version-specific CWL and Docker image**, rather than reliance on a
moving `latest` image tag. Hannes Neuschmidt's
[release workflow example (ESA-Heatwise/heatwise-patch-extraction PR #3)](https://github.com/ESA-Heatwise/heatwise-patch-extraction/pull/3)
is the intended model. This development repository does **not** yet
publish an ESA-Heatwise release or a versioned GHCR container.

Before publication, update the remaining CWL and technical reports,
regenerate `MANIFEST_SHA256.json`, finalize the project-approved software
license, clarify GUSL/image redistribution permissions, and arrange
EOAP review and release in the ESA-Heatwise organization.

Additional methodology and output details:
`docs/DUAL_SELECTION_V032.md`, `docs/GENERAL_CLASS_FALLBACK.md`,
`docs/EOAP.md`, and `docs/EOAP_READINESS.md`.

## General missing-class fallback configuration

This policy is independent of location and applies uniformly to configured
material classes. It is enabled by default, and can be overridden from a JSON
or YAML configuration using:

```yaml
matching:
  FALLBACK_ENABLED: true
  FALLBACK_MAX_SAM_DEG: 8.0
  FALLBACK_MAX_SAM_BY_CLASS: {}
```

Optional, methodologically justified per-class maximum angles belong in
`FALLBACK_MAX_SAM_BY_CLASS` (e.g. `{'material_class': 6.0}`); the key must
already appear in `FINAL_TARGET_CLASSES`. Changing a threshold is a
scientific decision, not a way to guarantee a desired label. Disabled:
`FALLBACK_ENABLED: false`.

Diagnostic `diagnostics/FULL_fallback_report.json` lists the previously
missing classes, recovered candidates, SAM/MBDSA, competing GUSL signature,
quality flags and unresolved classes. The same information is summarized in
`run_summary.json`. If a required class must be present, list it in
`required_classes` so the run fails when no plausible candidate exists.

**Caution:** Recovered classes may be spectrally confused with another material
(e.g. asphalt vs terracotta). A fallback never proves a material is present.
Science-facing reports must distinguish ordinary matches from provisional
fallback endmembers and verify them independently before ESA delivery.

