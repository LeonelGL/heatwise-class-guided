# HEATWISE: material-level maps after official HySUPP/FCLS

## Responsibility and scientific scope

Two independent executables share one versioned Docker image:

1. **Class-guided preprocessing EOAP** (`class_guided_processor.py`,
   `cwl/workflow.cwl`): consumes CHIME-like STAC imagery and GUSL; produces
   FULL/MASK3 endmember XLSX, optimized 15-band selection, and class mapping.
2. **Material postprocessing EOAP** (`tools/aggregate_fcls_classes.py`,
   `cwl/material_workflow.cwl`): consumes **externally generated** official
   FCLS abundance output plus the associated endmember workbook and mapping.
   It never invokes, modifies, or packages the ESA FCLS processor.

There is **no single EOAP that executes all three stages** (preprocessing,
external FCLS, postprocessing). Users explicitly run official FCLS in between.

The official ESA FCLS produces abundances `a_k(x,y)` for each **spectral
endmember** and an individual-endmember Top-1. If multiple signatures refer
to the same material, the class-level products instead use:

```text
A_material(x,y) = sum(a_k(x,y) for endmembers k in that material)
material_Top1(x,y) = argmax_material A_material(x,y)
```

For example, asphalt 0.25 + 0.20 + 0.15 outweighs concrete 0.40.
The original individual-endmember FCLS results are preserved unmodified.
The class labels may be provisional: a spectral match to GUSL is not proof
of the true material identity.

## Direct CLI example (official FCLS has already been run)

```bash
python tools/aggregate_fcls_classes.py \
  --abundances /data/fcls/Sepolia_FCLS_abundance_stack_COG.tif \
  --selected-endmembers /data/class-guided/selected_endmembers_FULL.xlsx \
  --class-mapping /data/class-guided/diagnostics/endmember_classes.json \
  --mode FULL \
  --fcls-class-names /data/fcls/Sepolia_FCLS_class_names.json \
  --fcls-metadata /data/fcls/Sepolia_FCLS_run_metadata.json \
  --acquisition-datetime 2009-07-18T12:00:00+02:00 \
  --output-dir /data/materials \
  --output-prefix Sepolia_FULL
```

**The timestamp above is only a syntax example, NOT a verified acquisition
time for Sepolia.** Enter the actual acquisition time and timezone from
authoritative imagery metadata; the only established Sepolia date is
2009-07-18. We do not substitute FCLS processing time for acquisition time.
The CLI also accepts `--fcls-output-dir /data/fcls` *instead of*
`--abundances`, discovering the abundance asset via official FCLS STAC
`catalog.json`.

Use `selected_endmembers_MASK3.xlsx` and `--mode MASK3` **only** if the
upstream FCLS run used that exact workbook. The 15 bands used to *select*
MASK3 endmembers do not automatically constrain FCLS spectral bands.

## CWL stage-in / stage-out

`cwl/material_workflow.cwl` wraps `cwl/material_postprocess.cwl` with
independent EOAP stage-in. Required arguments:

- `fcls_outputs`: **Directory**, the official FCLS STAC output containing
  `catalog.json`, an Item with an `abundance` asset, and its local GeoTIFF.
- `selected_endmembers`: **File**, exactly the FULL or MASK3 XLSX used in
  FCLS; `class_mapping`: **File** `diagnostics/endmember_classes.json`.
- `mode`: `FULL` or `MASK3`; `fcls_class_names` and `fcls_metadata`:
  **File** outputs of the same official FCLS run.
- `acquisition_datetime`: ISO8601 with explicit timezone; optional
  `output_prefix` and `min_abundance`.

Example synthetic end-to-end *postprocessor-only* test, without running FCLS:

```bash
python examples/make_postprocess_fixture.py results/material-fixture
docker build -t heatwise/class-guided:0.3.2 .
python -m cwltool --outdir results/material-test cwl/material_workflow.cwl \
  results/material-fixture/job_material_synthetic.yml
python tools/validate_material_outputs.py results/material-test/results synthetic
```

The source fixture deliberately **simulates** FCLS-shaped abundance data.
It is not a test of ESA FCLS or real material-classification accuracy.

## Material EOAP outputs

- `<prefix>_class_abundances_COG.tif`: one summed abundance band per
  material, georeferenced with nodata preserved.
- `<prefix>_material_top1_COG.tif`: 1-based dominant **material** labels;
  0 means invalid/unassigned.
- `<prefix>_material_classes.json`: exact group membership, source file
  SHA256 digests, acquisition time, classification threshold and counts.
- `catalog.json` and `item.json`: STAC 1.1 output containing a
  WGS84 geometry/bbox and relative assets to the two COGs and metadata.

Classes and numeric labels follow `classes_by_mode[mode]` in the selection
mapping. Never hardcode label positions or assume nine endmembers are present:
the selector may omit a class if its candidates are not plausible.

## Safety and known limitations

- The XLSX columns, official FCLS `class_names.json`, official run metadata,
  raster band tags (when present), and mapping must agree. Unknown, duplicated,
  or reordered endmembers fail rather than silently changing class identities.
- The official FCLS metadata records endmember *names and workbook basename*,
  but not an endmember-content digest; this tool hashes the **actual** workbook
  supplied to it. It cannot prove retrospectively that FCLS used identical
  spectral numeric values. Preserve the original workbook and run provenance.
- Invalid pixels remain nodata; optionally, `min_abundance` thresholds
  the **maximum aggregated material** abundance (which is different from the
  official per-endmember threshold). Default comes from FCLS metadata.
- All versions of the tool are subject to independent scientific validation;
  passing synthetic CWL/COG/STAC tests is not a claim of real Sepolia FCLS
  accuracy or formal ESA certification.

## Versioned delivery

The release preparation builds **two independent version-pinned packed CWLs**,
`heatwise_class_guided.cwl` and `heatwise_material_top1.cwl`, alongside one
versioned Docker image containing both entrypoints. It also includes the four
source CWLs in the release archive. The release workflow refuses to publish
until a project-approved LICENSE exists; none is selected or inserted here.
