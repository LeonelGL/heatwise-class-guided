# HEATWISE class-guided urban material mapping

This repository contains two independent Python/CWL processors:

1. **Class-guided selection:** extracts candidate spectra from a hyperspectral scene, matches them to the GUSL library, and exports scene-specific endmembers selected using FULL spectra and an optimized 15-band subset (MASK3).
2. **Material mapping:** groups the endmember abundances produced by the external [HEATWISE HySUPP/FCLS processor](https://github.com/ESA-Heatwise/heatwise-hysupp-unmixing) into material-level abundance maps and a dominant-material (Top-1) map.

Both processors share a Docker image. **FCLS itself is not included or executed here.**

## Processing chain

```text
CHIME-like image + GUSL
          |
  class_guided_processor.py
          |
  FULL/MASK3 endmembers + selected bands + class mapping
          |
  external HySUPP/FCLS (run separately)
          |
  per-endmember abundance raster
          |
  aggregate_fcls_classes.py
          |
  per-material abundances + material Top-1
```

The preprocessor uses PCA/PPI-like candidate extraction, spectral screening, PCHIP interpolation of GUSL signatures, SAM/MBDSA matching and class-guided selection. It chooses 15 wavelengths from the FULL endmembers, then independently matches the same scene candidate pool on those bands for MASK3. Both output libraries retain **all usable scene wavelengths**, not just the 15 selected bands. Missing classes can receive provisional fallback candidates subject to a SAM threshold.

See [Method](docs/METHOD.md) for algorithm details and configurable parameters.

## Reference inputs

The repository includes the original example data:

| Input | Path |
| --- | --- |
| CHIME-like Sepolia v2, 250 bands | `examples/sepolia/Sepolia_CHIME_Thermopolis_v2_COG.tif` |
| Sepolia input STAC catalog | `examples/sepolia/catalog.json` |
| GUSL spectral library | `examples/resources/GUSL_spectra_by_material_headers.xlsx` |
| Sepolia processing configuration | `examples/config_sepolia_report.json` |
| Sepolia CWL job | `examples/job_sepolia.yml` |

The GUSL reader uses the `BRUSSELS_APEX_GENLIB` and `DLR` worksheets by default. `GUSL_catalog_all.csv` is not required by the current processor. The Sepolia acquisition **date** is 2009-07-18; an exact acquisition time has not been established. File identities and source commits are recorded in [Reference data](docs/REFERENCE_DATA.json).

## Install

Use Python 3.11:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`. The version-pinned `requirements.txt` is used for local execution, testing, and Docker builds.

## Run class-guided on Sepolia

Run from the repository root:

```bash
python class_guided_processor.py \
  --input-catalog examples/sepolia \
  --gusl examples/resources/GUSL_spectra_by_material_headers.xlsx \
  --config examples/config_sepolia_report.json \
  --output-dir results/sepolia
```

Or use the containerized CWL:

```bash
docker build -t heatwise/class-guided:0.3.2 .
python -m cwltool --outdir results/sepolia-cwl \
  cwl/workflow.cwl examples/job_sepolia.yml
```

`cwltool` runs on the host and stages input files into Docker. The supplied Sepolia configuration uses 20,000 random projections and 500,000 band combinations; running it can be computationally demanding. For a new city, substitute its STAC image and configure the processing parameters as appropriate.

### Main preprocessor outputs

| File | Meaning |
| --- | --- |
| `selected_endmembers_FULL.xlsx` | Spectra selected using FULL-band similarity |
| `selected_endmembers_MASK3.xlsx` | Independently selected spectra using 15-band similarity |
| `selected_endmembers.xlsx` | Identical compatibility copy of the FULL workbook |
| `selected_bands.json` | Optimized wavelengths and band indices |
| `mask3_matching_bands.json` | Actual image bands used for MASK3 matching |
| `diagnostics/endmember_classes.json` | Endmember-to-material grouping for each selection mode |

The output directory also contains diagnostics, run metadata and a STAC catalog. Endmember workbooks have `wavelength_um` as the first column. **The 15-band list is a selection result, not a requirement to reduce the input image for FCLS.**

## Run material-level Top-1

Run the external HySUPP/FCLS with the original image and **one** of the exported endmember XLSX files. Then run our independent postprocessor on the resulting abundance stack and corresponding FCLS metadata:

```bash
python tools/aggregate_fcls_classes.py \
  --abundances /data/fcls/scene_abundance_stack_COG.tif \
  --selected-endmembers results/sepolia/selected_endmembers_FULL.xlsx \
  --class-mapping results/sepolia/diagnostics/endmember_classes.json \
  --mode FULL \
  --fcls-class-names /data/fcls/scene_class_names.json \
  --fcls-metadata /data/fcls/scene_run_metadata.json \
  --acquisition-datetime YOUR_VERIFIED_ISO8601_DATETIME \
  --output-dir results/materials \
  --output-prefix sepolia
```

The `--acquisition-datetime` value must be a verified ISO 8601 timestamp with timezone; do not infer a time from Sepolia's known date. Use `--mode MASK3` only when FCLS used the MASK3 workbook.

The postprocessor sums the abundance of all selected endmembers assigned to each material and then selects the dominant material. It writes `*_class_abundances_COG.tif`, `*_material_top1_COG.tif`, a class-label JSON file and STAC metadata. Details, including CWL invocation, are in [Material postprocessing](docs/FCLS_MATERIAL_AGGREGATION.md).

## Tests and packaging

```bash
python -m pytest tests -q
python -m cwltool --validate cwl/workflow.cwl
python -m cwltool --validate cwl/material_workflow.cwl
```

The CI workflow also builds Docker and executes both processors with **synthetic test inputs**. Tests check the bundled real GUSL/Sepolia file identities and metadata, but do not repeat the computationally expensive real-scene workflow or execute official FCLS. The recorded [real Sepolia class-guided run](https://github.com/LeonelGL/heatwise-class-guided/actions/runs/40743012798) used these reference inputs.

See [EOAP interface](docs/EOAP.md), [Release procedure](docs/RELEASE.md), and [Validation](VALIDATION_REPORT.md). The formal tagged release requires a project-approved software license. Data attribution and redistribution terms are a separate matter; see [NOTICE](NOTICE.md).
