cwlVersion: v1.2
class: CommandLineTool
id: class_guided
label: HEATWISE FULL and MASK3 class-guided preprocessor
doc: >
  Extract scene candidates, match independently using FULL and 15-band MASK3,
  and select discriminative bands independently. Output selected_endmembers.xlsx
  selected_endmembers_FULL.xlsx, selected_endmembers_MASK3.xlsx,
  and selected_bands.json, plus diagnostics. Both endmember files contain all usable spectral bands. Do not run FCLS or generate reduced raster products.
baseCommand:
  - python3
requirements:
  DockerRequirement:
    dockerPull: heatwise/class-guided:0.3.2
arguments:
  - position: 0
    valueFrom: $(inputs.processor.path)
  - --output-dir
  - results
inputs:
  - id: input_catalog
    type: Directory
    label: Input STAC catalog
    doc: Locally staged single-item STAC catalog containing one COG asset.
    inputBinding:
      prefix: --input-catalog
  - id: gusl
    type: File
    label: GUSL spectral library
    doc: Input XLSX containing the configured GUSL sheets.
    inputBinding:
      prefix: --gusl
  - id: config
    type: File
    label: Processing configuration
    doc: JSON or YAML with extraction, matching, and band-selection settings.
    inputBinding:
      prefix: --config
  - id: wavelengths
    type: File?
    label: Input band wavelengths
    doc: Optional original image-band centers in micrometers.
    inputBinding:
      prefix: --wavelengths
  - id: processor
    type: File
    label: Python processor
    doc: Integrated Python scientific processor supplied with the workflow.
    default:
      class: File
      location: ../class_guided_processor.py
outputs:
  products:
    type: Directory
    outputBinding:
      glob: results
$namespaces:
  s: https://schema.org/
s:softwareVersion: "0.3.2"
s:codeRepository: https://github.com/LeonelGL/heatwise-class-guided
