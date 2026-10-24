# Scientific and technical change report

## Source basis and scope

All three supplied scripts were read before implementation. Their unmodified copies
are in `reference/`, with the complete extracted constant settings in
`reference/original_defaults.json`. The processor contains their actual numerical
kernels, refactored into instance-configured `Extraction`, `Matching`, and
`BandSelection` classes, plus an in-memory orchestration layer. It neither launches
nor imports the three original scripts. Source comments/docstrings in Spanish are
retained where useful; this document explains the decisions in English.

## Extraction

Preserved: adaptive finite-band fractions (20-band minimum and fallback), brightness
percentiles, NDVI urban definition, brightness thirds, stratified sampling, L2-normalized
PCA, standardized PCA coordinates, random PPI projections, extrema counts, spectral
support, angular medoid representative, score weights, stratum quotas, supplemental
candidates, and SAM deduplication. Reflectance vectors retained for matching are
physical spectra; L2 normalization is confined to the original shape computations.
Local support includes the seed itself in the original code. With minimum support=1
this is a weak isolation test; preserved, not silently tightened. Global dedup sorts
by score, so interleaving does not guarantee final stratum quotas; also preserved.
`MIN_FINAL` is an aspiration, not a guaranteed number. Log/metadata show actual count.

Necessary technical changes:

- Removed Windows DLL preload, environment mutation and global warning suppression.
- Honor per-band GDAL masks as well as nodata. Apply declared raster scale/offset
  consistently during extraction and output; default float reflectance remains unchanged.
- Require actual wavelength centers. Removed invented linear 0.4–2.5 µm fallback
  and interpolation of missing metadata. Explicit text is in µm; raster tags support
  µm/nm. Duplicate image centers are rejected rather than merged.
- Sort wavelength centers and image band indices together; retain original indices.
- Enforce complete finite spectra before PCA. The original 98%-finite fallback can
  leave NaNs that PCA cannot process; no spectral imputation is introduced.

Explicit scientific/configuration changes:

- Generic config has no hardcoded Sepolia gap. `config_sepolia_report.json` supplies
  [0.9960, 1.9714] µm explicitly. Data-driven invalid-band detection still applies.
- Default `vegetation_mode=separate` preserves the original urban extraction and
  adds the same PPI/pruning procedure on valid NDVI>0.30 pixels, up to 30 vegetation
  candidates. Combined pool is deduplicated. It does NOT guarantee GUSL will classify
  them as vegetation. `urban_only` reproduces the exclusion; `all` stratifies all
  valid pixels by brightness without NDVI. These modes can change results and require
  real-scene validation. NDVI requires valid red/NIR within 0.04 µm tolerance.
- A user may require classes using `required_classes`; missing classes then stop the run.
  Otherwise absent materials are reported, not fabricated as NaN endmembers.

## GUSL matching

Preserved algorithms: prefix class mapping; Brussels/DLR sheets (configurable);
PCHIP on finite knots without endpoint extrapolation; linear interpolation for two
knots; first value retained for duplicate library wavelengths; SAM and MBDSA;
SAM class assignment; MBDSA within-class ranking; optional acceptance; top-three
averages; asphalt/concrete quality/opponent-margin/diversity bundle selection.
Auxiliary bitumen/soil/water compete but are not final classes by default.

### Confirmed defect corrected

The original Excel reader sorts the dataframe by wavelength and then applies the
same permutation again to each spectral column. For initially unordered input,
reflectances no longer correspond to their wavelength rows. The second permutation
is removed. A regression test demonstrates the original error and corrected pairing.
Sorted original Excel data are unaffected. This correction changes results for
unsorted inputs because it restores their physical correspondence.

### Important preserved limitations

- Despite general wording about common bands, `compute_similarity_matrices` uses
  one GLOBAL finite-band intersection across all retained candidates and all library
  spectra, not pairwise intersections. FULL therefore means all nominal valid image
  bands before that intersection. Both nominal and effective counts/indices are logged.
- A short-coverage spectrum can greatly reduce the common spectral domain. An all-NaN
  library signature is omitted; a signature with only partial coverage remains.
  No automatic library-coverage filtering or pairwise metric change is introduced.
- PCHIP bridges internal missing knots; “no extrapolation” does not mean it preserves
  internal missing intervals. This is original behavior, not a new gap-filling promise.
- Original float32 library grids/outputs remain. Endpoint roundoff can exclude a target
  infinitesimally outside rounded library limits; observed in the synthetic fixture.
  No undocumented boundary extrapolation is enabled.
- Class competitors are limited to the original TOP_K=50 SAM matches. A class missing
  from this pool is not necessarily far in physical terms. The original asphalt/
  concrete fallback fills missing opponent margin with the best finite margin (or 0
  if none exist); this optimistic rule is preserved and identifiable in diagnostics.
- `USE_ACCEPTANCE_THRESHOLDS=False` by default. If enabled: SAM<=8°, MBDSA<=0.12;
  margin threshold follows ranking metric (SAM>=1° or MBDSA>=0.01).
  The second class is chosen by class-assignment metric, so its MBDSA margin need not
  equal the margin to the second-best MBDSA class. No silent correction is made.
- First asphalt/concrete choice uses 0.60 quality / 0.40 margin; later choices use
  0.50 quality / 0.35 margin / 0.15 diversity. Existing first-choice constants remain.
- Metal, terracota and vegetation are averages of up to three accepted scene candidates.
  Asphalt/concrete stay as up to three separate scene spectra each, not averages.

## Band selection

| Setting | Supplied selector | Requested report configuration |
|---|---:|---:|
| Preselected bands | 35 | 100 |
| Bands per combination | 9 | 15 |
| Random combinations | 50,000 | 500,000 |
| Retained top combinations, per objective | 20 | 100 |
| Final bands | 15 | 15 |
| Minimum spacing, µm | 0.040 | 0.040 |

The processor default is the requested report configuration. That is NOT evidence
that it reproduces report wavelengths or accuracies. Smaller synthetic test configuration
uses 1,500 combinations and reduced extraction projections; separate tests exercise
500,000 combinations. Historical wavelengths are only in a comparison utility.

Preserved: class means; regularized diagonal Bhattacharyya when EVERY class has >=2
samples; otherwise global fallback to standardized Euclidean; single-band mixed
mean/min score; ranked pool; unique random combinations or exhaustive enumeration;
best-average and best-minimum lists; counting both lists (overlap counted twice);
frequency ordering; greedy minimum-spacing selection over the entire band frequency
table (including zero-frequency bands if needed).

- Class parsing recognizes registered class names followed by `_number` or `__number`.
  It does not split arbitrary underscores. Unknown names stay distinct; explicit
  `class_mapping` is available. The exact grouping and sample counts are exported.
- Input to the selector is the FULL final bundle: individual asphalt/concrete
  signatures plus single averaged signatures for other present classes. Thus the
  usual nine-endmember case uses the EUCLIDEAN PROXY. Three candidates inside a
  single average do not constitute three covariance samples. No pseudo-replication.
- Only FULL effective common GUSL bands enter band optimization. This explicit domain
  restriction ensures MASK3 can score all selected bands. It can change the result
  relative to selecting all nominal FULL rows even outside library coverage.
- Batch evaluation precomputes per-pair diagonal contributions and sums them. Euclidean
  contributions are squared distances, then square-rooted after summing bands.
  Bhattacharyya sums both diagonal terms. Tests compare both branches against original
  functions. Small floating-point differences are possible; tolerance is recorded.
- Unique random combinations are sorted deterministically; tied scores use explicit
  lexical index strings as final tie-break. Legacy set iteration/tie behavior was not
  a robust reproducibility contract. These ties may select different equal-score sets.
- If greedy spacing yields fewer than requested bands, fail instead of silently
  shortening MASK3 or relaxing 0.040 µm. This is not a global spacing optimizer.
- No ground truth or accuracy target is used anywhere in selection.

## MASK3 decision

The original script calls `run_single_analysis` AGAIN on reduced candidate/library
spectra. It reassigns classes, recomputes margins and reselects bundles/averages; it
then writes the full-grid spectra for those selected candidates. It does not simply
crop FULL endmembers. The new processor preserves this reselection using the dynamic
band indices. The delivered final spreadsheet contains only those selected rows,
matching the reduced image. This last cropping is a product-format change required
for direct FCLS. The fixed original 12 targets and nearest-band tolerance are NOT used.

## Raster and FCLS interface

Reduced image values are the selected original values after explicit source scale/
offset, not unit-norm spectra. Output float32 carries NaN nodata per band; masks are
preserved semantically, including holes. Grid/CRS/transform/resolution are unchanged.
Effective centers, original zero/one-based indices and order are exported. Excel
serialization may round at ~1e-16; equality is checked to absolute 1e-12 µm, with no
nearest-neighbor or resampling tolerance. Any dimension/order mismatch stops FCLS.

FCLS is unchanged from official commit `c97ae3d3c0d8140069733750f448521b30b920ed`.
The adapter calls its existing solver and raster writers. The official classification
is a dominant ENDMEMBER label. With three asphalt signatures, dominant endmember is
not equivalent to dominant summed material. Additional material abundance sums and
material classification are exported with explicit mappings; original endmember
outputs remain available. Ill-conditioning of similar bundles remains a scientific
risk and requires real-data assessment.
