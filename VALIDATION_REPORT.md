# Validation report — preprocessing-only 0.2.0

This revision prepares inputs for the separate official ESA HEATWISE unmixing processor. It does not execute FCLS. No real-scene accuracy or ESA qualification is claimed.

## Implemented

All original integrated extraction, FULL matching, mandatory band selection and dynamic MASK3 re-matching stages remain. Output is GeoTIFF COG + XLSX endmembers + wavelength TXT, with alignment checks. A new unmixing_inputs.json records relative paths, spectral dimensions, endmember names, wavelengths, scale factor 1.0 and unmixing_executed=false. The original image band count is recorded separately from the selected band count.

The adapter, upstream runtime copy and full-chain/FCLS CWL documents were removed from this deliverable. No algorithmic FCLS replacement or MAT interface was added. The official processor.py was retrieved on 2026-10-26 to verify its actual accepted inputs.

## Checks executed on 2026-10-26

- Python 3.11.17 environment rebuilt from the pinned dependency lock (dependencies.log).
- 19 unit/regression/integration tests passed (pytest_final.log), including original-kernel parity, same-seed reproduction, nodata, physical reflectance, class grouping, alignment rejection and the new handoff contract.
- CWL Workflow static validation passed (cwl.log). Container execution was not performed.
- A fresh 250-band synthetic image and synthetic GUSL ran through all scientific stages: 67 candidates, 249 usable image bands, 248 FULL comparison bands, 15 selected bands and 9 final endmembers, including vegetation (synthetic_250_final.log and examples/output_250/run_summary.json).
- This 250-band run used the fast synthetic configuration (1,500 combinations), not the 500,000-combination report setting. The historical 120-band synthetic output_500k remains a separately identified version 0.1.0 example; it is not Sepolia validation.
- Official consumer input-reader compatibility and strict COG/STAC checks are recorded in official_input_contract.json and output_checks_250.json respectively. These checks do not execute the FCLS solver.

## Failed attempts and corrections

The previous virtual environment's Python symlink was unavailable; a new Python 3.11 environment was built. The first edit to the configurable synthetic generator accidentally changed its default argument; this was corrected before final testing. An overlapping preliminary run collided with an existing diagnostics directory; final runs used a fresh output directory. The new input-band-count metadata initially used the spatial axis; it was corrected to len(wavelengths) and covered by a regression assertion. These were technical/metadata corrections, not changes to scientific selection criteria. Preliminary failure logs are retained where available.

## Pending

The actual Sepolia CHIME v2 250-band image, complete GUSL resource and trustworthy acquisition/wavelength metadata are required for real execution and comparison with the historical experiment. Required material coverage and scene-specific gap settings must be verified on those inputs. Docker build/run, containerized CWL, a published digest-pinned image and ESA target-platform interoperability remain untested. The GitHub connector returned HTTP 404; source publication is being performed through the authorized browser session. Check the repository commit history for publication status.

## EOAP publication revision

All diagnostic files are now referenced as relative STAC assets, to preserve them during stage-out. Regression tests cover candidates.csv and unmixing_inputs.json references (pytest_eoap.log). CWL software version/repository metadata and docs/EOAP_READINESS.md were added. GitHub Actions uses contents:read only and is prepared to test Docker and containerized CWL; its presence is not evidence of a successful run. No new scientific changes were introduced.

## GitHub Actions execution (2026-10-26)

Run 40362015074 at commit 372796c passed scientific regression tests and built the Docker image, but containerized execution failed on importing Rasterio: `libexpat.so.1` was missing. Consequently the final output check failed because no products were created. This was a container dependency failure, not successful end-to-end validation. The Dockerfile now explicitly installs `libexpat1` and imports the scientific/geospatial dependencies at build time. The corrected container requires a new CI run.
