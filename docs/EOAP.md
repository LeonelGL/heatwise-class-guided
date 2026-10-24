# EOAP design and official repository review

Reference sources inspected:

- https://github.com/ESA-Heatwise/heatwise-hysupp-unmixing
- https://github.com/ESA-Heatwise/heatwise-hysupp-unmixing/pull/1
- https://github.com/ESA-Heatwise/heatwise-hysupp-unmixing/pull/3
- https://docs.ogc.org/bp/20-089r1.html

The last document is an OGC **Best Practice**, not an OGC Standard certification.
No compliance or ESA acceptance is asserted by this package.

## Observed upstream layout

Snapshot: `c97ae3d3c0d8140069733750f448521b30b920ed`.
The repository has `processor.py`, `extract_path_from_stac.py`,
`heatwise_hysupp_unmixing.cwl`, Dockerfile, requirements, Sepolia sample data and
`src/heatwise_unmixing/processing/fcls.py`. The solver is a SciPy SLSQP FCLS with a
fallback clipped/renormalized least-squares solution if optimization fails.
The new package does not rewrite this solver. Selected text sources are included in
`upstream/` for reproducible local integration; no remote branch was changed.

PR #1 introduced a Workflow wrapping input STAC extraction and the unmixing tool,
explicit command base paths and container declarations, plus a staged Sepolia
catalog. PR #3 changed the output to a Directory and added STAC catalog construction.
The new package follows those input/output patterns and keeps the GUSL resource as
an explicit File parameter.

## Packaging choice

A separate preprocessing component with a composite CWL workflow is the simplest
local deliverable: the existing scientific FCLS remains independently reviewable.
The two components can later be added under the official repository after project
review. No new repository or public image was created. The single Dockerfile in this
review package contains both components to simplify local integration; the upstream
FCLS code remains isolated in its snapshot directory.

`cwl/workflow.cwl` is preprocessing-only. `cwl/full_workflow.cwl` calls preprocessing
then FCLS. Each tool has explicit `baseCommand: [python3]`, documented inputs,
DockerRequirement and staged script resources. Processing runs in CWL's writable
working directory and returns a `results` Directory preserving a catalog and assets.
Scripts are File defaults staged by CWL, so host-only testing uses the same source.
`upstream` is a Directory default on the FCLS tool. The official files are imported
by the adapter, not copied into a new optimizer.

## STAC boundaries

- Input: a local staged catalog with a single Item and COG; hrefs resolve against
  their actual Item, including nested layouts. GUSL is separately staged.
- Output: STAC 1.1 core catalog/Item with relative assets, geographic WGS84 geometry
  and bbox, source acquisition time and a separate processing timestamp.
- Reduced reflectance bands include effective spectral centers; source raster tags
  and original indices are retained in the raster/JSON products.
- Table and metadata assets remain in the catalog; diagnostics remain in the output
  directory and are copied through the FCLS stage.
- The full workflow preserves preprocessing products and adds endmember and material
  abundance/classification COGs and numerical label mappings.

The schema test covers STAC core and supplied fields. A core-schema pass is not proof
of mission-specific profile conformance, complete extension metadata or platform
stage-in/stage-out interoperability.

## Upstream metadata issues identified

The inspected `build_stac` uses projected raster bounds as geographic Item geometry,
uses processing time for acquisition datetime, and assigns classification band
metadata to `asset_abundance`, overwriting its abundance-band metadata. The upstream
source snapshot is left unchanged. Our FCLS adapter builds its output catalog from
the correctly georeferenced preprocessing Item and adds distinct assets and label
metadata, avoiding those issues without altering FCLS calculations.

## Release tasks

1. Execute Docker build and container tests on Linux/Python 3.11.
2. Obtain an authorized registry namespace; publish reviewed images and pin digests.
3. Check transitive dependency/artifact hashes and base-image digest for release.
4. Execute CWL with containers on the actual HEATWISE/ESA platform, including stage-in,
   catalog discovery, asset upload and stage-out.
5. Agree on any required STAC extension profile and class-code conventions.
6. Confirm GUSL redistribution/access licensing, source-code licensing and upstream
   snapshot ownership before any public distribution.
7. Run complete Sepolia and cross-city scientific validations, record inputs/hashes,
   configuration differences and the effect of vegetation/domain changes.
