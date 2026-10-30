# HEATWISE class-guided v0.3.2 — EO Application Package

## Purpose and processing boundary

This is an independent OGC EO Application Package (EOAP) preprocessor. It
receives a locally staged, single-item STAC catalog with a CHIME-like COG,
an externally supplied GUSL spectral library (XLSX), a configuration file,
and optionally a text file of original sensor band wavelengths (micrometers).

Processing stages: finite-band screening; scene-based PCA/PPI candidate extraction;
GUSL interpolation; class-guided FULL SAM/MBDSA matching; selection of 15
discriminative bands from FULL endmembers; independent MASK3 matching on the
15 selected bands; and export of full-length spectral signatures for both
selection modes.

## Scientific products and metadata

- selected_endmembers_FULL.xlsx — FULL-selected endmember spectra, retaining
  all usable scene wavelengths (124 in the Sepolia v2 reference run).
- selected_endmembers_MASK3.xlsx — independently MASK3-selected signatures,
  retaining the same complete usable wavelength grid.
- selected_endmembers.xlsx — exact compatibility alias of FULL for the unchanged
  ESA HySUPP/FCLS input contract.
- selected_bands.json — 15 selected bands, indices, and selection configuration.
- mask3_matching_bands.json — the 15 wavelengths actually used by MASK3.

Both modes have separate diagnostic files, fallback provenance and quality flags.
run_summary.json, effective_config.json, catalog.json and item.json provide
provenance and STAC stage-out metadata. The workflow returns one output
Directory containing these assets; STAC links to files using relative paths.

No FCLS is run in this EOAP. The selected-band list is NOT supplied to FCLS.
No reduced-band raster, abundance map, classification map, or MAT file is
generated. This preprocessor cannot independently verify a material's identity.
Fallback matches are explicitly provisional.

## Executable package and stage-in

- cwl/workflow.cwl — CWL 1.2 Workflow with four typed inputs and one output
  Directory. References the sibling cwl/preprocess.cwl.
- cwl/preprocess.cwl — CommandLineTool with one DockerRequirement, executing
  /app/class_guided_processor.py inside the image (without an external script).
- cwl/local/* — no-Docker local development equivalents.
- Dockerfile — Python 3.11 and pinned dependencies.
- tools/validate_outputs.py — validates the dual exports, STAC links, band
  indices and absence of reduced-raster/unmixing products.

Inputs must be staged separately for each deployment. The production source
tree and published container do not embed the original real GUSL library or
real Sepolia test scene; only synthetic regression fixtures are included.
Library and image redistribution, where needed, require an independent
documented rights decision.

## Version-fixed delivery

ESA requires versioned EOAP releases, with non-moving Docker image references.
tools/prepare_release.py creates release-specific versions of BOTH CWLs;
cwltool --pack makes one standalone heatwise_class_guided.cwl.
.github/workflows/release.yml runs for version tags such as v0.3.2 and:
- checks a nonempty approved LICENSE and the absence of real input datasets;
- regenerates/validates the release CWLs, runs tests and a Docker/CWL synthetic
  smoke test with the release image;
- publishes the version-specific image to ghcr.io/<owner>/<repo>:<version>;
- creates a GitHub Release attaching the packed CWL and original paired CWLs.

Source CWLs stay unchanged and may retain a local development Docker tag.
The release CWL uses the published image with an exact immutable *version
name*. Protect tags and image tags from reassignment as a project policy.

The software licensing decision is pending; the existence of an open-source
publication policy is not a license grant. No formal release may proceed
without a project-authorized LICENSE.

## Interoperability and evidence

Automated synthetic and dual-mode CI tests passed for the v0.3.2 processing
chain, and Sepolia real-scene preflight passed on 2026-10-28:
https://github.com/LeonelGL/heatwise-class-guided/actions/runs/40743012798

The separate CWL packaging test is executed by the pull-request CI. These
tests do not establish ESA-platform certification or a full downstream FCLS
run. A new real-scene experiment requires the authorized data to be restaged.

The original image must be provided independently, together with either FULL
or MASK3 endmember XLSX, to the official HySUPP/FCLS processor:
https://github.com/ESA-Heatwise/heatwise-hysupp-unmixing
