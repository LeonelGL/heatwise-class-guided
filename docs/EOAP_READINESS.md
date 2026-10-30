# EOAP readiness — HEATWISE class-guided v0.3.2

This is a technical delivery checklist, **not ESA certification**.

| Topic | Implemented and tested | Remaining |
| --- | --- | --- |
| Scientific processing | FULL → optimized 15 wavelengths → independent MASK3; both export full-length endmember spectra | Class accuracy/parameter optimality are not certified |
| Python CLI and dependencies | Python 3.11; pinned lockfile; synthetic regression tests | Reconfirm execution on each official tagged release |
| EOAP stage-in | STAC input Directory, GUSL File, config File, optional wavelengths File | Authorized inputs must be staged externally |
| EOAP stage-out | Output Directory, relative STAC assets and dual Excel/JSON products | Consumer-specific platform staging review |
| Docker | Container build and synthetic CWL execution passed | Publish tag-specific image on final organization |
| CWL | Workflow and CommandLineTool; packaged Python; self-contained release CWL generated and validated | Final versioned release in ESA organization |
| GitHub releases | Automated version-pinned workflow prepared | Requires approved LICENSE and final tag |
| Real Sepolia v2 | 250-band scene and GUSL validated on 2026-10-28 | New runs require externally staged files |
| Input/licensing rights | No real GUSL/Sepolia assets in current delivery tree; restrictions documented | Explicit source-code license and third-party data permissions |
| Provenance | Original algorithm reference scripts retained; SHA-256 manifest with CI checking | Update after any final source changes |
| FCLS handoff | Spectral interface preflight completed | Run actual downstream HySUPP FCLS separately |
| Reproducibility | Input hashes, configurable seed and diagnostics | Investigate cross-run candidate variations before claims of exact numerical reproducibility |

## Verification evidence

- Synthetic Python, Docker, STAC and CWL processing:
  https://github.com/LeonelGL/heatwise-class-guided/actions/runs/41089164849
- Full Sepolia v2 and GUSL dual-selection preflight:
  https://github.com/LeonelGL/heatwise-class-guided/actions/runs/40743012798
- Versioned CWL preparation and packaging:
  https://github.com/LeonelGL/heatwise-class-guided/actions/runs/41090729518

The 250 original sensor bands reduced to 124 usable output wavelengths, 103
common FULL/GUSL comparison wavelengths and 15 MASK3 matching wavelengths
in the referenced Sepolia run. Endmember tables still retain all 124
wavelengths; no FCLS was executed.

## Known scope limitations

GUSL interpolation, FULL common-finite-band reduction, SAM/MBDSA acceptance
and PPI instability are scientific considerations requiring further study.
A provisional fallback class is a spectral assignment, not validated material
presence. The supplied GUSL_catalog_all.csv is not parsed by the algorithm.
The precise Sepolia acquisition time/timezone is not inferred from its date.

## Required administrative approvals

1. Choose and approve a source-code license, identify the rightful copyright
   holder(s), and add the corresponding LICENSE. Hannes asked that every
   open-source software deliverable include one, but did not select a license
   for this processor.
2. Confirm redistribution conditions for the real GUSL spectral library and
   mimicked Sepolia inputs. These are not included in the current source tree.
3. Decide the final version number and target repository with the project
   maintainers. No formal release or container publication has occurred.
