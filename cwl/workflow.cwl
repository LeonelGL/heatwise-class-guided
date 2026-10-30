cwlVersion: v1.2
class: Workflow
id: main
label: HEATWISE class-guided FULL + MASK3 endmember and band selection
doc: >
  EOAP-style workflow. Extract scene-derived candidates and match against GUSL
  using FULL spectral information. Select 15 bands from FULL endmembers;
  independently re-match the same candidates on those bands (MASK3).
  Export full-length endmember libraries for both modes, a FULL compatibility
  alias, optimized-band metadata, diagnostics and STAC output. No FCLS
  unmixing, reduced raster or ground-truth validation.
inputs:
  - id: input_catalog
    type: Directory
    label: Input STAC catalog
    doc: Locally staged single-item STAC catalog with one COG asset.
  - id: gusl
    type: File
    label: GUSL spectral library
    doc: XLSX with configured Brussels and DLR sheets; no ground truth.
  - id: config
    type: File
    label: Configuration
    doc: Processing JSON or YAML configuration.
  - id: wavelengths
    type: File?
    label: Input wavelengths
    doc: Optional original image-band centers in micrometers.
steps:
  prepare:
    run: preprocess.cwl
    in:
      input_catalog: input_catalog
      gusl: gusl
      config: config
      wavelengths: wavelengths
    out:
      - products
outputs:
  products:
    type: Directory
    outputSource: prepare/products
$namespaces:
  s: https://schema.org/
s:softwareVersion: "0.3.2"
s:version: "0.3.2"
s:codeRepository: https://github.com/LeonelGL/heatwise-class-guided
