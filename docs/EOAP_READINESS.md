# EOAP readiness — HEATWISE class-guided 0.3.0

This is an engineering readiness checklist, **not ESA certification**.
The target operator must confirm the exact acceptance criteria.
Prior GitHub Actions pass evidence for **0.2.0** is not evidence that
**0.3.0** has passed.

| Concern | 0.3.0 implementation | Still to validate / complete |
| --- | --- | --- |
| Processing scope | FULL-only class-guided endmember extraction and independent band optimization | Compare with real Sepolia/GUSL reference method |
| Scientific data output | `selected_endmembers.xlsx` and `selected_bands.json` | Full real-scene dimensional/reflectance consistency |
| Endmember matching | SAM/MBDSA on global common finite spectral intersection | Audit which and how many bands contribute on real data |
| Preprocessor CLI | Python 3.11; explicit image/STAC, GUSL, configuration, wavelengths and output arguments | Actual stage-in command run |
| Input contract | STAC single Item, locally staged COG; external GUSL XLSX | Real source metadata, source library coverage |
| Output contract | STAC catalog + Item with two scientific assets and relative diagnostic assets | Target platform stage-out validation |
| CWL | Workflow and CommandLineTool with typed inputs | Re-run cwltool validation and containerized CWL for 0.3.0 |
| Docker | Python 3.11 pinned dependencies; local `heatwise/class-guided:0.3.0` tag | Successful v0.3.0 Docker build; publish approved image/digest |
| Python regression | Original-kernel parity and FULL-only synthetic tests defined | Verify green current-branch CI run and logs |
| Reproducibility | Random seed, config, versions, input SHA-256, wavelength and band indices, diagnostics | Validate complete real experiment |
| Handoff to official FCLS | Endmember XLSX and original full raster expected; band JSON independent | Check wavelength interpolation, missing bands and scale on real image |
| Provenance/license | `reference/` originals, `docs/PROVENANCE.json`, `NOTICE.md` | Agree publication license, third-party GUSL rights |
| Spectral provenance | Real wavelengths required; no fabricated sensor centers | Confirm Sepolia V2 wavelength grid and acquisition time |
| Scientific accuracy | Synthetic tests only for this package | Ground-truth evaluation and per-material uncertainty |
| Repository integrity | `MANIFEST_SHA256.json` | Regenerate after all final code/docs commits |

**Historical evidence (0.2.0 only):** GitHub Actions run
[40362481432](https://github.com/LeonelGL/heatwise-class-guided/actions/runs/40362481432)
was reported as successful for the previous reduced-COG/MASK3-based
interface. It must not be represented as v0.3.0 acceptance.

Open issues include the global finite intersection across GUSL signatures,
the unparsed `GUSL_catalog_all.csv`, the inability to infer a precise Sepolia
acquisition timestamp from only its reported date (2009-07-18), and the
need to confirm endmember-to-full-raster compatibility with FCLS.
