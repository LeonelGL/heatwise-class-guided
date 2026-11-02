# Class-guided endmember selection

## Inputs

The processor reads a single-item STAC catalog referencing a local hyperspectral
GeoTIFF/COG, a GUSL workbook and a JSON/YAML configuration. Wavelengths are read
from the raster metadata or an explicitly supplied wavelength file. Raster
scale, offset and validity masks are applied during input loading.

The example configuration is `examples/config_sepolia_report.json`; its
settings are **scene-specific**, not universal defaults.

## Scene candidates

1. Exclude configured spectral gaps and bands with insufficient valid samples.
2. Identify potential urban pixels using brightness and NDVI criteria.
3. Extract spectrally extreme candidates through stratified PCA/PPI-like random
   projections.
4. Check local spatial support, select representative spectra and remove
   near-duplicate candidates.

The selected spectra originate from image pixels, rather than being copies of
GUSL reference signatures.

## GUSL matching

The configured GUSL sheets (`BRUSSELS_APEX_GENLIB`, `DLR` for Sepolia) are
interpolated to image wavelengths with PCHIP; unsupported regions are not
extrapolated. Similarity is evaluated using SAM and MBDSA.

**FULL** matches the candidate pool using the common set of spectral bands
with valid samples across the retained spectra. This intersection may be
smaller than the set of usable image bands. Material classes are selected
using `matching.FINAL_TARGET_CLASSES` and `TARGET_CLASS_PREFIXES`; for the
Sepolia configuration, multiple asphalt and concrete signatures can be kept.

A missing class can trigger a general fallback. The algorithm considers
unused scene candidates and every relevant GUSL reference of that class, using
a class-specific SAM ceiling (default: 8 degrees) and an assignment that avoids
reusing candidates. If none passes, the class remains absent, unless included
in `required_classes`, in which case the run fails. Fallback assignments
are provisional spectral matches, not proof of material presence.

Relevant options:

```yaml
matching:
  FALLBACK_ENABLED: true
  FALLBACK_MAX_SAM_DEG: 8.0
  FALLBACK_MAX_SAM_BY_CLASS: {}
```

The same missing-class policy applies to the independent MASK3 matching pass;
diagnostics are written separately for each mode.

## Band selection and MASK3

The processor optimizes 15 wavelengths using the FULL-selected endmember set.
It then repeats the candidate-to-GUSL classification on those wavelengths
(**MASK3**) to generate a second, independently selected library.

`matching.MASK3_SOURCE` can be `auto` (use the optimized bands) or `fixed`
(use `matching.MASK3_WAVELENGTHS_UM`). In fixed mode, selected wavelengths
must map to distinct supported image bands within
`matching.MASK3_MAX_DELTA_UM` (default 0.01 µm).

FULL and MASK3 export endmember spectra on **all usable image wavelengths**.
The optimized 15-band list is not a reduced hyperspectral image and is not
passed as an FCLS input.

## Outputs and interpretation

The two endmember XLSX files contain wavelength in the first column and one
column per selected signature. `selected_endmembers.xlsx` is identical to
`selected_endmembers_FULL.xlsx`, for downstream compatibility.

`selected_bands.json`, `mask3_matching_bands.json`, mode-specific
`diagnostics/` files and `diagnostics/endmember_classes.json` describe the
bands, assignments and grouping into material classes. The STAC output
provides geospatial metadata and relative asset links.

GUSL matching alone does not establish ground-truth labels. The algorithm
does not perform FCLS or calculate material abundance maps. Those are separate
operations described in `docs/FCLS_MATERIAL_AGGREGATION.md`.

For the archived Sepolia run on 2026-10-28, 250 input bands yielded 124
usable output wavelengths, 103 common FULL matching wavelengths and 15
MASK3 matching wavelengths. Nine endmembers were exported per mode.
These figures characterize that experiment only.

The retained `reference/` scripts serve as scientific regression baselines,
and `docs/PROVENANCE.json` records their checksums.
