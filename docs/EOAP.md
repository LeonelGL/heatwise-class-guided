# HEATWISE class-guided v0.3.0 — EOAP processing boundary

## Scope

The package is a **preprocessor**, not the official unmixing application.
It receives one locally staged STAC raster scene, an explicitly supplied
GUSL XLSX, configuration, and optionally original-band wavelength centers.

The package outputs precisely two **scientific data products**:

1. `selected_endmembers.xlsx` — FULL class-guided endmembers on all usable
   scene wavelengths, intended for a separate FCLS consumer.
2. `selected_bands.json` — 15 selected bands and their metadata, computed
   independently after the FULL endmembers are fixed.

Other files in the output Directory (e.g. run summary, diagnostics,
band-selection workbook, catalog) document execution. They are not
additional scientific image/classification/abundance products.

No MASK3 re-matching, no reduced scene COG, no MAT file, and no FCLS solver
or postprocessing occurs in this application.

## Packaging components

- `cwl/workflow.cwl`: EOAP-oriented CWL Workflow exposing input catalog,
  GUSL, configuration and optional wavelength file; output is a Directory.
- `cwl/preprocess.cwl`: corresponding CommandLineTool, explicit CLI
  bindings and `DockerRequirement` for local image tag
  `heatwise/class-guided:0.3.0`.
- `cwl/local/workflow.cwl` and `cwl/local/preprocess.cwl`: local no-Docker
  variants, used only with an installed Python environment.
- `Dockerfile`: Python 3.11 implementation and pinned dependencies.
- `catalog.json` and `item.json`: STAC output links with the two scientific
  files marked as data assets, other files as metadata assets.
- `tools/validate_outputs.py`: checks the FULL-only product schema, band
  indices, STAC integrity and prohibition of generated raster products.

The output Item inherits temporal context from the input STAC Item where
available, and the source raster supplies geographic footprint. The
**original image is not an output asset**. This is important because its
input-stage location must not be mistaken for a persistent EOAP product.

## External unmixing handoff

The unchanged official ESA-Heatwise FCLS processor consumes the input
hyperspectral raster **separately** from the FULL endmember XLSX.
The independent JSON band selection is **not passed to FCLS**.

The endmember spreadsheet contains usable wavelengths, which may exclude
invalid sensor bands. Therefore actual consumer-side spectral alignment,
interpolation/masking behavior and radiometric scale must be verified
using the *real* original raster and official consumer code. No claim of
validated direct compatibility follows solely from synthetic tests.

## Status and remaining requirements

The code is structured for CWL/OGC EOAP-style packaging, but
**this is not ESA platform approval or certification**. The current
branch's full CI/Docker/CWL outcome and real-scene Sepolia/GUSL run must
be checked after the v0.3.0 updates are committed.

Before delivery, confirm: target-platform stage-in/stage-out behavior,
published container image pinned by digest, source licensing, GUSL
distribution rights, metadata and band alignment, scientific results
against reference validation points, and documented reproducibility.
