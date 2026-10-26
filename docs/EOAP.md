# Preprocessing EOAP boundary, version 0.2.0

The application ends at aligned spectral inputs. The only packaged Workflow is `cwl/workflow.cwl`; its `preprocess.cwl` tool has explicit baseCommand, labeled/documented inputs and DockerRequirement. STAC input is locally staged. GUSL is a separate File resource. Output is a Directory containing a relative STAC catalog, COG, XLSX and diagnostics.

The separate ESA-Heatwise/heatwise-hysupp-unmixing project consumes GeoTIFF and XLSX/CSV plus optional wavelength TXT. Its current processor.py was retrieved and checked on 2026-10-26. Its read_input_raster uses rasterio; read_endmembers accepts .xlsx/.xls and .csv/.txt, rejecting .mat. A legacy/general HySUPP MAT interface is not the delivered processor interface reviewed here.

This revision removes fcls_adapter.py, the upstream runtime snapshot and the FCLS/full-chain CWL branches from the deliverable. No scientific extraction/matching/band-selection algorithm changes were made. It adds a machine-readable handoff file unmixing_inputs.json. Historical preprocessing examples may record version 0.1.0; the current-run example records 0.2.0.

The repository should contain unpacked source, not a ZIP used at runtime. A versioned ZIP is a downloadable delivery artifact only. The source is maintained in the personal repository LeonelGL/heatwise-class-guided. See EOAP_READINESS.md for release blockers.

Docker execution, registry publication/digest pinning, containerized CWL and target ESA interoperability remain unverified. The package is not declared ESA-ready.
