# EO Application Package interface

The repository provides two separate CWL 1.2 workflows, sharing one Docker
image. Both expose an output `Directory` called `products`.

## 1. Class-guided preprocessing

**Workflow:** `cwl/workflow.cwl`  
**Tool:** `cwl/preprocess.cwl`  
**Entrypoint:** `/app/class_guided_processor.py`

| Input | CWL type | Description |
| --- | --- | --- |
| `input_catalog` | Directory | Single-item STAC catalog with local COG asset |
| `gusl` | File | GUSL workbook |
| `config` | File | JSON/YAML processing configuration |
| `wavelengths` | File? | Optional input wavelengths in µm |

The output Directory includes FULL/MASK3 endmember XLSX, selected-band JSON,
mode-specific diagnostics, run summary and STAC `catalog.json`/`item.json`.
No image resampling, FCLS fitting or abundance mapping occurs.

The included real-data example is `examples/job_sepolia.yml`, which uses
`examples/sepolia/`, `examples/resources/GUSL_spectra_by_material_headers.xlsx`
and `examples/config_sepolia_report.json`.

```bash
docker build -t heatwise/class-guided:0.3.2 .
python -m cwltool --outdir results/sepolia-cwl \
  cwl/workflow.cwl examples/job_sepolia.yml
```

The output `selected_endmembers.xlsx` duplicates
`selected_endmembers_FULL.xlsx` for FCLS compatibility. The 15-band
selection does **not** imply that downstream FCLS must use only 15 bands.

## 2. Material aggregation after external FCLS

**Workflow:** `cwl/material_workflow.cwl`  
**Tool:** `cwl/material_postprocess.cwl`  
**Entrypoint:** `/app/aggregate_fcls_classes.py`

| Input | CWL type | Description |
| --- | --- | --- |
| `fcls_outputs` | Directory | External FCLS STAC output with abundance asset |
| `selected_endmembers` | File | The FULL or MASK3 XLSX used by FCLS |
| `class_mapping` | File | `diagnostics/endmember_classes.json` from the same run |
| `mode` | string | `FULL` or `MASK3` |
| `fcls_class_names` | File | FCLS class-name JSON |
| `fcls_metadata` | File | FCLS run-metadata JSON |
| `acquisition_datetime` | string | Verified timestamp with timezone |
| `output_prefix` | string | Optional, defaults to `HEATWISE_FCLS` |
| `min_abundance` | float? | Optional threshold after aggregation |

Outputs include class-summed abundance and material Top-1 COGs, label/provenance
JSON, and a STAC catalog with a WGS84 footprint.

This is **postprocessing only**. The official FCLS code remains external;
it must be run separately on the original image with the matching endmember
XLSX. See [Material aggregation](FCLS_MATERIAL_AGGREGATION.md) for the CLI
and CWL test example.

## Docker, tests and release

The Dockerfile installs pinned Python 3.11 runtime dependencies and both
Python entrypoints, but not the GUSL workbook or Sepolia COG; CWL stages these
from the repository or another data source.

`cwl/local/` contains optional no-Docker variants of the class-guided
preprocessor. The validation workflow runs Python tests and synthetic
Docker/CWL tests for both processors; it also checks the identity and metadata
of the bundled real data.

For a fixed-version release, `tools/prepare_release.py` generates separate
version-pinned CWL pairs and packed CWLs. The formal publishing workflow
requires a software `LICENSE` before pushing a Docker image or creating a
GitHub Release; see [Release procedure](RELEASE.md).
