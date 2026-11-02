# Material-level abundance and Top-1 maps

`tools/aggregate_fcls_classes.py` postprocesses the **external** HEATWISE
HySUPP/FCLS abundance raster. It does not run FCLS or change the original
per-endmember abundance estimates.

## Calculation

For material `c`, with endmembers `G_c`:

```text
abundance_c(pixel) = sum(abundance_k(pixel) for k in G_c)
top1(pixel)        = argmax_c abundance_c(pixel)
```

For example, three asphalt fractions of 0.25, 0.20 and 0.15 produce
an asphalt abundance of 0.60. A single concrete fraction of 0.40 does not
outweigh their **combined** material abundance.

The grouping comes from `diagnostics/endmember_classes.json` created by
class-guided. The script validates the endmember names and order against the
exported XLSX and FCLS metadata; it does not assume a fixed number of
endmembers or a hard-coded label ordering.

## Inputs

- FCLS `*_abundance_stack_COG.tif`, or the FCLS STAC output directory
  containing `catalog.json` with an `abundance` asset.
- The **same** `selected_endmembers_FULL.xlsx` or
  `selected_endmembers_MASK3.xlsx` supplied to FCLS.
- `diagnostics/endmember_classes.json` from that class-guided run.
- FCLS `*_class_names.json` and `*_run_metadata.json`.
- `FULL` or `MASK3` mode and the actual acquisition date-time with timezone
  (ISO 8601). Sepolia's date alone is insufficient to infer its exact time.

Example, after executing FCLS separately:

```bash
python tools/aggregate_fcls_classes.py \
  --fcls-output-dir /data/fcls-output \
  --selected-endmembers /data/class-guided/selected_endmembers_FULL.xlsx \
  --class-mapping /data/class-guided/diagnostics/endmember_classes.json \
  --mode FULL \
  --fcls-class-names /data/fcls-output/scene_class_names.json \
  --fcls-metadata /data/fcls-output/scene_run_metadata.json \
  --acquisition-datetime YOUR_VERIFIED_ISO8601_DATETIME \
  --output-dir results/materials \
  --output-prefix scene
```

If the FCLS run used MASK3, pass the MASK3 workbook and `--mode MASK3`.
The selected 15 wavelengths are used for class-guided **matching**, not
automatically as a restriction on the FCLS input bands.

## Outputs

- `<prefix>_class_abundances_COG.tif`: one band per material, sums of the
  corresponding FCLS endmember fractions.
- `<prefix>_material_top1_COG.tif`: one band with 1-based material labels;
  zero indicates nodata or an unassigned pixel.
- `<prefix>_material_classes.json`: material-label definitions, member
  endmembers, source file hashes and pixel counts.
- `catalog.json` and `item.json`: STAC output with WGS84 geometry/bbox
  and links to both COGs and the JSON metadata.

The geotransform, CRS and nodata masks are retained. Optional
`--min-abundance` applies to **aggregated material fractions**, not
individual endmembers.

## CWL test

The workflow `cwl/material_workflow.cwl` uses the same Docker image as the
class-guided processor. An executable synthetic example is available:

```bash
python examples/make_postprocess_fixture.py results/material-fixture
docker build -t heatwise/class-guided:0.3.2 .
python -m cwltool --outdir results/material-check \
  cwl/material_workflow.cwl \
  results/material-fixture/job_material_synthetic.yml
python tools/validate_material_outputs.py results/material-check/results synthetic
```

The FCLS-shaped fixture is synthetic and does not test the official FCLS
processor or real-scene material accuracy.

**Provenance limitation:** the official FCLS metadata records the library
filename and endmember names but not a content hash of the library used.
This postprocessor records hashes of the files supplied to it, but cannot
prove that FCLS previously used identical spectral values. Retain the
original input workbook and FCLS run records.
