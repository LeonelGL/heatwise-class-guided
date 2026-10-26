# HEATWISE class-guided preprocessor

This project prepares scene-specific endmembers and a spectrally aligned image for the existing ESA HEATWISE unmixing package. It does not run FCLS or produce abundance/classification maps.

## Processing

CHIME-like image + external GUSL XLSX → stratified PCA/PPI-like candidates → FULL SAM/MBDSA matching and endmember selection → automatic discriminative band selection → MASK3 re-matching of all candidates → aligned image and endmembers.

The reference band configuration is 100 preselected bands, 15 bands per combination, 500,000 sampled combinations, 100 retained best combinations, 15 final bands and 0.040 µm minimum spacing. Bands are selected from the input scene, never from a fixed Sepolia list. Original algorithms and explicit changes are documented in `docs/CHANGES.md`.

## Output contract

The official `ESA-Heatwise/heatwise-hysupp-unmixing` processor checked on 2026-10-26 reads a multiband GeoTIFF and an XLSX/CSV endmember table. It does not accept MAT endmember files. Therefore this project exports:

- `hyperspectral_mask3_COG.tif`: selected bands, physical reflectance, source spatial grid and CRS.
- `EndmembersFinales_mask3.xlsx`: wavelength rows and one column per endmember, including multiple asphalt/concrete signatures.
- `mask3_wavelengths_um.txt`: exactly the image wavelengths in spectral order.
- `unmixing_inputs.json`: relative input paths, dimensions, wavelength vector and scale factor for the separate unmixing processor.
- `selected_bands.json`, `Endmembers_FULL.xlsx`, `band_selection.xlsx`, diagnostics and execution metadata.
- `catalog.json` and `item.json`: STAC catalog and product assets.

The input may have 250 bands; the default final image has 15 selected bands. Every final endmember has the same 15 spectral samples. The program verifies alignment before declaring success. No MAT format is invented for a different HySUPP interface.

## Install and run

```bash
python3.11 -m venv .venv
# Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock-python311.txt
python class_guided_processor.py --image /data/Sepolia_CHIME_v2.tif --gusl /data/GUSL.xlsx --config examples/config_sepolia_report.json --output-dir results/sepolia
```

The filenames above are placeholders for the actual inputs, not bundled real data. For direct raster input, first set `acquisition_datetime` in the configuration to the true image acquisition datetime with timezone. Do not use the processing date. If the raster lacks wavelengths, add `--wavelengths /data/wavelengths_um.txt` (one center per original band). Check the configured GUSL sheets, material prefixes and invalid spectral interval against the actual Sepolia v2 data. Do not infer sensor metadata merely from a filename or a 250-band count.

Alternatively use `--input-catalog /data/staged_catalog` instead of `--image`; the acquisition time then comes from the input STAC Item. The staged catalog must contain one Item and one COG asset (or use `--asset-key`). GUSL is a separate explicit input. Outputs must go into a new or empty directory. Original inputs are not modified.

## Hand off to the official unmixing project

In the separate official unmixing installation, use:

```bash
python processor.py --input-image /absolute/results/sepolia/hyperspectral_mask3_COG.tif --endmembers /absolute/results/sepolia/EndmembersFinales_mask3.xlsx --wavelengths-txt /absolute/results/sepolia/mask3_wavelengths_um.txt --scale-factor 1.0 --output-dir /absolute/results/sepolia_unmixing
```

This project does not bundle or replace the official FCLS implementation. Scale factor 1.0 is intentional: declared input scale/offset have already been applied to physical reflectance in the reduced image.

## Synthetic tests and CWL

```bash
python examples/make_synthetic.py
python class_guided_processor.py --input-catalog examples/synthetic --gusl examples/gusl_synthetic.xlsx --config examples/synthetic_config.json --output-dir results/synthetic
python -m pytest tests -q
python -m cwltool --validate cwl/workflow.cwl
```

`cwl/workflow.cwl` runs preprocessing only; `cwl/preprocess.cwl` is its CommandLineTool. GUSL is supplied as a File, and the staged input catalog as a Directory. Docker image reference `heatwise/class-guided:0.2.0` is a local build tag, not a published image:

```bash
docker build -t heatwise/class-guided:0.2.0 .
python -m cwltool --outdir results/cwl cwl/workflow.cwl examples/job_synthetic.yml
```

See `VALIDATION_REPORT.md` for executed checks and limits. Real Sepolia v2/GUSL reproduction and Docker/platform execution remain pending.

`examples/output_250` is the fresh version 0.2.0 preprocessing example for a **synthetic** 250-band input. Its generator supports `make(path, band_count=250)`. It is not the real Sepolia sensor grid. `examples/output_500k` is a retained historical synthetic 0.1.0 preprocessing example using the larger band search. Neither is a real-scene accuracy validation.

## Delivery status

See [EOAP readiness](docs/EOAP_READINESS.md) and [validation report](VALIDATION_REPORT.md). The read-only GitHub Actions workflow tests Python, CWL, Docker and output integrity. A green run does not replace real Sepolia/GUSL validation or ESA platform acceptance.
