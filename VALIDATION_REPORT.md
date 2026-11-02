# Verification and limitations

## Automated checks

GitHub Actions runs Python regression tests, validates both CWL workflows,
builds the Docker image and executes synthetic end-to-end examples for
class-guided preprocessing and material aggregation. It checks the exact
bundled real-data Git blobs, their STAC references, 250-band Sepolia raster
metadata and GUSL workbook sheets. Release preparation checks both packed
CWL files with a versioned Docker image.

- [Last verified `main` CI run](https://github.com/LeonelGL/heatwise-class-guided/actions/runs/41487807680)
- [Real Sepolia v2/GUSL class-guided run, 28 October 2026](https://github.com/LeonelGL/heatwise-class-guided/actions/runs/40743012798)

The real-scene run used 250 input image bands, yielding 124 usable output
wavelengths, 103 common FULL matching bands and 15 MASK3 matching bands.
Nine signatures were exported for each endmember library; 277 scene
candidates entered matching. The configured band search sampled 500,000
combinations. These are experiment-specific measurements, not guaranteed
results for other scenes.

## Scope of verification

The real Sepolia execution verifies extraction, matching and exports at
the referenced historical revision. Current CI verifies structural
integrity of the bundled data and regression behavior but does **not**
repeat the full, computationally expensive real-scene run.

No official HySUPP/FCLS fit using these exported signatures has been
verified within this repository. The material postprocessor has been
tested using synthetic FCLS-shaped abundances, not official FCLS outputs.
Material labels, including fallback assignments, have not been
independently ground-truth validated by these tests.

The FULL similarity calculation uses a common finite-band intersection
across candidates and GUSL; this can exclude otherwise usable image bands.
Numerical equivalence between independent science runs is not guaranteed
without a separate reproducibility assessment.

These tests establish software functionality, not formal ESA platform
acceptance or a licensed software release.
