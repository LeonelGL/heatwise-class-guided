cwlVersion: v1.2
class: Workflow
id: main
label: HEATWISE FULL class-guided endmembers and band selection
doc: >
  EOAP-style workflow. Select endmembers once using FULL spectral matching
  against GUSL; optimize 15 bands independently. Emit two scientific files
  plus diagnostic metadata. No MASK3, reduced raster, or FCLS execution.
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
s:softwareVersion: "0.3.1"
s:codeRepository: https://github.com/LeonelGL/heatwise-class-guided
