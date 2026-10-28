# General FULL missing-class fallback — HEATWISE v0.3.1

## Scientific decision

All configured `matching.FINAL_TARGET_CLASSES` are handled by the same policy.
No class (including terracotta or metal) and no region (including Sepolia) is
hard-coded. The normal FULL class-guided extraction/matching is attempted
first. The fallback runs **only for a material class with no selected
endmember**. It does not perform MASK3 re-matching.

## Matching and selection

1. Let `M` be the classes missing from normal FULL selection.
2. For each class, identify ALL of its matching GUSL signatures using the
   configured `TARGET_CLASS_PREFIXES`. Do not rely on the global Top-K.
3. For each previously unused scene candidate, retain its lowest SAM against
   any signature of that class. All scores are measured on the existing FULL
   common spectral comparison mask, not on selected 15 bands.
4. Accept candidate-class pairs only if `SAM <= FALLBACK_MAX_SAM_DEG` (default
   8 degrees), or the configured per-class ceiling.
5. Assign one distinct candidate to each recoverable missing class, with a
   linear-sum assignment that first maximizes recovered class count, then
   minimizes total angular distance.
6. Export that actual candidate spectrum on every usable scene wavelength;
   do not export the GUSL template and do not alter existing endmembers.
7. Report remaining classes as unresolved when none pass. Honor
   `required_classes` as a strict requirement when configured.

## Configuration

```yaml
matching:
  FALLBACK_ENABLED: true
  FALLBACK_MAX_SAM_DEG: 8.0
  FALLBACK_MAX_SAM_BY_CLASS: {}
```

Setting `FALLBACK_ENABLED: false` restores the original FULL-only selection
without any fallback. Class-specific thresholds can be declared by matching
the class IDs listed in `FINAL_TARGET_CLASSES`.

## Products and auditability

The scientific products remain exactly:
- `selected_endmembers.xlsx`: all usable wavelengths of scene-derived FULL
  endmembers, including provisional fallback representatives;
- `selected_bands.json`: independently optimized 15-band selection.

The auxiliary `diagnostics/FULL_fallback_report.json` and `run_summary.json`
record class, candidate, matching GUSL spectrum, SAM, MBDSA, best competing
library spectrum, winning class before fallback, quality flag and unresolved
classes. These flags are **not** scientific confirmation of material identity.

## Cautions

A small SAM can still indicate confusion between physically similar classes.
FCLS outputs should explicitly distinguish primary and provisional inputs
when reporting abundance/classification, and independent validation against
reference points is required before ESA handoff. Since a fallback class
changes the set of endmembers, it can alter the *independent* 15-band
optimization results, but it never feeds those 15 bands back into matching.
The FCLS implementation is not part of this repository and is unchanged.
