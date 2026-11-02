# HEATWISE: material-level Top-1 after official ESA FCLS

This is an **optional, separate downstream postprocessing step**. It does not
run, vendor, or modify the official `ESA-Heatwise/heatwise-hysupp-unmixing`
processor. The existing `class_guided_processor.py` and EOAP/CWL interface
continue to export endmembers and bands only.

## Scientific distinction

Official FCLS estimates one abundance `a_k(x,y)` per input **endmember** and
writes an endmember-level Top-1 raster. With three asphalt and three concrete
signatures, this is not necessarily equivalent to the dominant **material**:

    A_material(x,y) = sum(a_k(x,y) for k belonging to material)
    Top1_material(x,y) = argmax_material A_material(x,y)

For example, asphalt fractions 0.25 + 0.20 + 0.15 outrank a concrete fraction
of 0.40 when grouping by material (asphalt = 0.60). The abundance stack from
FCLS is preserved unchanged. No refitting is performed.

## Inputs and execution

First run class-guided normally, choosing either `selected_endmembers_FULL.xlsx`
or `selected_endmembers_MASK3.xlsx`. Then run **the unchanged official FCLS**
using the **same XLSX**. Finally, from this repository root:

```bash
python tools/aggregate_fcls_classes.py \
  --abundances /results/fcls/Sepolia_FCLS_abundance_stack_COG.tif \
  --selected-endmembers /results/class-guided/selected_endmembers_FULL.xlsx \
  --class-mapping /results/class-guided/diagnostics/endmember_classes.json \
  --mode FULL \
  --fcls-class-names /results/fcls/Sepolia_FCLS_class_names.json \
  --fcls-metadata /results/fcls/Sepolia_FCLS_run_metadata.json \
  --output-dir /results/materials \
  --output-prefix Sepolia_FULL
```

For MASK3, use the MASK3 XLSX **and** `--mode MASK3` and an FCLS run made with
that library. Do not confuse the 15 bands *used to choose MASK3 endmembers*
with the spectral bands used by FCLS: official FCLS ordinarily uses all usable
input bands.

## Output files

- `Sepolia_FULL_class_abundances_COG.tif`: one class-summed abundance band per
  material; source georeferencing and nodata are retained.
- `Sepolia_FULL_material_top1_COG.tif`: one raster band, 1-based material IDs;
  `0` indicates invalid/unassigned pixels.
- `Sepolia_FULL_material_classes.json`: label names, exact group membership,
  provenance inputs, and counts.

The class order follows the class-guided `classes_by_mode[mode]` mapping; do
**not** assume that material label IDs will always follow the same order.

## Provenance and safeguards

The program requires the selected XLSX column names, official FCLS class-name
JSON, official FCLS run metadata, per-band tags (when present), and class-guided
class mapping to agree. Missing, duplicated, or reordered names fail rather
than silently creating wrong labels. The official FCLS metadata records the
XLSX basename and endmember names, **not a cryptographic hash of the XLSX**.
Therefore identical spectra cannot be proved from these outputs alone; preserve
the original workbook and source hashes for a fully auditable science run.

The official FCLS abundance raster's finite/nodata mask defines valid pixels.
An optional `--min-abundance` threshold applies to the **maximum summed material
abundance**; by default the threshold is taken from FCLS metadata. This is
not identical to the official threshold for an individual endmember.

This script is standalone, not yet an integrated EOAP output or a verified
real-Sepolia/ESA FCLS scientific validation. Synthetic unit tests exercise the
class sums, GeoTIFF/georeferencing, missing-pixel handling, and input mismatches.
No claim of historical Top-1 accuracy is made without ground-truth validation.
