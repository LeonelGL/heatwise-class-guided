# HEATWISE v0.3.2 — dual FULL / MASK3 endmember selection

## Scientific design

This extension preserves a single scene-derived PCA/PPI candidate pool. It then
performs **two separate class-guided assignments** against the GUSL library:

1. **FULL**: calculate SAM/MBDSA using all bands finite in every retained library
   signature and scene candidate (e.g. 103 common comparison bands for Sepolia).
2. **MASK3**: calculate SAM/MBDSA, assign materials, select class representatives
   and apply missing-class fallback using precisely 15 selected wavelengths.

**Both methods export the selected scene spectra on all usable image wavelengths**,
not merely the 15 matching wavelengths (e.g. 124 rows for Sepolia v2). In particular,
class-averaged endmembers are averaged using the complete candidate spectra.

## Scientific output files

- `selected_endmembers_FULL.xlsx` — FULL-selected, **full-length** spectra.
- `selected_endmembers_MASK3.xlsx` — MASK3-selected, **full-length** spectra.
- `selected_endmembers.xlsx` — compatibility alias containing the same spectra
  and column order as `selected_endmembers_FULL.xlsx` (former ESA FCLS contract).
- `selected_bands.json` — 15 optimized diagnostic bands calculated from the FULL
  endmember set; this is not the reduced endmember Excel.
- `mask3_matching_bands.json` — the actual 15 spectral centers and their original
  scene indices used for MASK3 matching.
- `diagnostics/FULL_*.csv`, `diagnostics/MASK3_*.csv` — separate class assignments,
  candidate usage, replicate choices and fallback reports per mode.
- `run_summary.json` — both mode-specific endmember lists, common-band counts,
  fallback decisions, inputs, metadata and processing versions.

The processor does not run FCLS, copy a reduced-band image, assign a material
class as ground truth, or independently validate material identity.

## How MASK3 wavelengths are chosen

- **Default (`MASK3_SOURCE="auto"`)**: optimize 15 bands from the FULL-selected
  signatures first, then re-run class selection on those bands. They are the
  SAME wavelengths shown in `selected_bands.json`.
- **Optional (`MASK3_SOURCE="fixed"`)**: specify exactly 15 wavelengths in
  `MASK3_WAVELENGTHS_UM`. This mode is appropriate for testing a published mask.
  The nearest finite measured image bands are used; the maximum permitted
  difference is `MASK3_MAX_DELTA_UM` (default 0.01 µm). Repeated indices or
  missing common GUSL coverage cause an explicit error, not silent relaxation.

The original Sepolia report used an older nominal wavelength grid. The fixed
paper mask example therefore serves to **test** that mask against CHIME v2; it
does not establish identity with the original paper endmember collection.

## Commands (with externally staged authorized datasets)

Automatic MASK3 (keeps existing Sepolia scientific configuration):

```bash
python class_guided_processor.py \
  --input-catalog /data/sepolia_stac \
  --gusl /data/GUSL_spectra_by_material_headers.xlsx \
  --config examples/config_sepolia_report.json \
  --output-dir results/sepolia_dual
```

For fixed MASK3, use the supplied `examples/config_dual_paper_sepolia.json`
(or merge its `matching.MASK3_*` settings into the existing Sepolia config).

Important: the real Sepolia image and GUSL XLSX are **not included** in the
current delivery tree. Stage authorized inputs at deployment time.

## ESA/EOAP compatibility and versioning

Version 0.3.2 changes the output contract from 2 main products to a dual-mode
contract and adds STAC assets and metadata. The legacy `selected_endmembers.xlsx`
remains an exact alias of FULL to protect previously integrated FCLS consumers,
but `tools/validate_outputs.py`, scientific tests, workflows, Docker/CWL tags,
and the SHA-256 manifest must be updated together. Changes are made in the
existing feature/dual-full-mask3 branch until the project approves a release. The official
FCLS processor is not modified by this patch.

## Verification

The new synthetic integration tests check both exported matrices on identical
full spectral grids, that MASK3 computes similarity only on selected bands,
that the fixed wavelength tolerance is enforced, and that the FULL alias
remains identical to the explicit FULL file. Real Sepolia dual-mode preflight passed on 2026-10-28 in GitHub Actions run
40743012798. The complete downstream HySUPP/FCLS pipeline was not executed.
