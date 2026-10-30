# HEATWISE class-guided — scientific and technical change record

## Current scope: version 0.3.2 — dual FULL + MASK3 (2026-10-30)

- FULL and MASK3 independently select scene-derived endmembers from a common
  candidate pool. MASK3 matches only on the 15 bands selected from FULL.
- Both modes export all usable spectral wavelengths. The legacy
  selected_endmembers.xlsx is a byte-equivalent table alias of FULL.
- The containerized EOAP embeds the processor Python in Docker, with no
  external processor script as a required CWL input.
- The tag-triggered GitHub Release workflow produces pinned-version Docker/CWL
  assets and a single-file packed CWL; it does not run on normal commits.
- Documentation and the source integrity manifest are updated for this contract.
- Real GUSL and Sepolia test datasets are excluded from the current delivery
  tree pending an approved redistribution determination. Synthetic fixtures
  and source/reference algorithms are preserved; earlier experiments remain
  referenced through immutable workflow run links and prior Git history.
- Code licensing requires a project-approved LICENSE; no license is inferred.

## Previous scope: version 0.3.1 (FULL-only with general missing-class fallback)

**Historical context only.** The current v0.3.2 workflow performs both FULL
and MASK3 matching; see the v0.3.2 section above.

### General missing-class fallback (introduced in 0.3.1)

If a material in `FINAL_TARGET_CLASSES` is missing after ordinary FULL class
selection, the preprocessor attempts to recover it by comparing all extracted
scene candidates against *all GUSL spectra matching that class*, not only
the original Top-K list. A fallback permits a target class to be a second
or lower choice, but requires a configurable class-specific SAM ceiling;
its default is 8 degrees, subject to independent validation. A joint
one-to-one minimum-cost assignment maximizes the number of covered missing
classes before minimizing total SAM. Endmembers already selected are never
changed or reused. No material or geographical location is privileged.

If no eligible unused candidate meets the SAM limit, the class remains absent;
it is reported as unresolved rather than fabricating a spectrum. Every
fallback is provisional and recorded in
`diagnostics/FULL_fallback_report.json` and `run_summary.json`.
These quality flags distinguish *forced class representation* from
*scientifically validated material presence*. The existing FCLS is unchanged.

### Endmember selection and outputs

- A CHIME-like reflectance raster and configured GUSL spectral-library XLSX are
  explicit inputs. Image wavelengths must be available from metadata or an
  explicitly supplied per-band file. Nodata, scale/offset and band ordering
  are handled by the reader.
- Extract scene-based candidate spectra using the stratified PCA/PPI-like
  procedure and local spectral-support/deduplication filters.
- Resample library spectra with PCHIP to the usable scene wavelength grid
  without extrapolating beyond each source signature's measured range.
- Perform **one** class-guided matching pass, named `FULL`, using SAM and
  MBDSA, class assignments, acceptance flags and class-specific selections.
  There is **no reduced-band MASK3 rematching**.
- `selected_endmembers.xlsx`: first column `wavelength_um`, remaining columns
  FULL-selected endmember reflectances on **all usable scene wavelengths**.
  These are scene-derived candidate spectra (or averages where configured),
  not the raw GUSL library spectra.
- `selected_bands.json`: 15 independently optimized wavelengths, original
  source-raster band indices, usable-grid indices, grouping, scores and
  configuration. Its 15 bands DO NOT feed back into endmember selection and
  are NOT consumed by the official FCLS.
- No selected-band GeoTIFF, no MAT artifact, no unmixing abundance map,
  no classification raster, and no execution of the FCLS solver.

Supporting logs, match/bundle diagnostics, band-selection workbook,
effective configuration, run summary and STAC metadata are retained as
provenance records, not extra scientific outputs. The source image is neither
modified nor copied into the output directory.

### Scope of "FULL" — important scientific qualification

FULL **does not mean blindly using all 250 nominal input bands**.
`Extraction.detect_usable_bands` excludes configured spectral gaps and
bands with insufficient finite observations. The `FULL` matcher then uses
a **single global finite-band intersection** of retained scene candidates
and all retained GUSL signatures. This effective common domain may contain
fewer bands than the usable image domain; both counts are reported.
The final endmember spreadsheet retains all *usable image* wavelengths
rather than being cropped to that global matching subset or to 15 bands.

The global intersection is a preserved original numerical choice, not a
newly validated optimal comparison strategy. A poorly covered GUSL spectrum
can shrink it substantially. This must be quantitatively audited using
real Sepolia CHIME v2 and GUSL data before reporting spectral comparability.

### Independent band optimization

Given the already-final FULL endmembers, `select_bands` scores spectral
separability by material class. It preselects bands, evaluates combinations,
ranks combinations by average/minimum separability, builds a frequency
table, then greedily enforces minimum wavelength spacing.

Report-style defaults: top 100 preselected bands, 15 per combination,
500,000 sampled combinations, top 100 per objective, 15 final bands,
minimum spacing 0.040 micrometers. Reduced synthetic configurations are
used in CI to keep checks computationally bounded. They do not reproduce
the full 500,000-combination real-scene experiment.

A diagonal Bhattacharyya estimate is used only where **every** material
class has at least two individual signatures; otherwise the legacy
standardized Euclidean proxy applies. Averaging three candidates into one
signature does **not** supply three independent covariance samples.

### Scientific kernels retained from the three supplied originals

**Candidate extraction:** adaptive finite-band screening, brightness
percentiles, NDVI threshold and urban brightness strata, optional
separate vegetation stratum, L2-normalized PCA, standardized PCA scores,
random PPI-like extrema accumulation, local spectral support,
angular medoid, support-based score, SAM deduplication and stratum
quotas. The source code's support count includes the seed pixel;
`MIN_SUPPORT_NEIGHBORS=1` therefore remains a weak isolation condition.
`MIN_FINAL` is a target, not a guaranteed output cardinality.

**GUSL matching:** configured Brussels/DLR sheets, PCHIP onto the scene
grid, prefix-driven material classes, SAM and MBDSA metrics, top-K
competitors, class assignment (default SAM), within-class ranking
(default MBDSA), optional acceptance thresholds, up to three separate
asphalt and concrete signatures, and class averages for applicable
other materials. The GUSL XLSX is consumed; `GUSL_catalog_all.csv` is
**not currently parsed** by this processor.

**Band selection:** pairwise separation objectives, random/exhaustive
combinations, deterministic seed and tie ordering, combined frequency
selection and minimum spacing.

### Previously documented technical corrections retained

- Corrected the double wavelength permutation in the original GUSL
  Excel reader for unsorted library wavelengths.
- Require real image wavelength centers; do not fabricate a 0.4–2.5 µm
  grid from the declared band count.
- Sort band data and corresponding original indices together.
- Apply raster masks, scale and offset consistently.
- Require fully finite selected candidate vectors before PCA rather
  than silently imputing non-finite reflectance values.
- Do not extrapolate external library spectra at the spectral endpoints.
- Validate selected band indices/spacing and refuse silently shortened lists.
- Separate synthetic fixtures from actual scene validation.

### Preserved scientific limitations to address later

1. Global finite intersection can remove usable discrimination bands.
2. The top-K GUSL competitor pool can omit another physically plausible
   material even when one exists elsewhere in the library.
3. The original fallback for missing asphalt/concrete opponent margins
   can favor an uncertain candidate.
4. GUSL PCHIP interpolation can bridge internal missing spectral intervals.
5. `USE_ACCEPTANCE_THRESHOLDS=False` by default. Current selected classes
   do not therefore imply stringent spectral-fit acceptance.
6. The class-guided label/name mapping must be checked against real
   GUSL sheets and materials, including possible bitumen/roof confusion.
7. Some class averages and asphalt/concrete replicas can lead to strongly
   correlated endmembers and FCLS ill-conditioning.
8. Synthetic workflows demonstrate interfaces and invariants only; they
   do not establish Sepolia overall accuracy or ESA qualification.

## Version history / provenance

### 0.3.1 — FULL-only endmember preparation

This version introduced general class-guided fallback and exported FULL spectra
without MASK3 re-matching. It has been superseded by the dual-mode v0.3.2.

### 0.2.0 — historical preprocessing-only interface

The previous implementation selected FULL candidates, optimized 15 bands,
**reran class assignment and endmember selection on the 15-band MASK3
subset**, and generated an aligned reduced COG, cropped endmember XLSX,
wavelength TXT and handoff JSON. This historical interface is obsolete
in 0.3.0 and is retained only in repository history and explicitly
identified historical synthetic examples.

### 0.1.0 — historical integrated development

Earlier integration/prototyping included unmixing-oriented adapters and
historical reduced-image examples. These are not the official FCLS
software and are not executed by the 0.3.0 pipeline.

## Code provenance

Reference versions of the three supplied algorithms remain in `reference/`
for scientific regression comparison. They are not imported or launched
by the current processor. The official FCLS resides exclusively in
`ESA-Heatwise/heatwise-hysupp-unmixing` and is **not changed** here.
Relevant provenance details are recorded in `docs/PROVENANCE.json`.

Release/license and third-party spectral-library redistribution rights
must be approved independently before an ESA-facing publication.

