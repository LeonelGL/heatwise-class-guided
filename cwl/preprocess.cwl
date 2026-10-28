cwlVersion: v1.2
class: CommandLineTool
id: class_guided
label: HEATWISE FULL class-guided preprocessor
doc: >
  Extract scene candidates, match once using all usable FULL wavelengths,
  and select discriminative bands independently. Output selected_endmembers.xlsx
  and selected_bands.json, plus diagnostics. Do not run FCLS or MASK3.
baseCommand:
  - python3
requirements:
  DockerRequirement:
    dockerPull: heatwise/class-guided:0.3.1
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
s:softwareVersion: "0.3.1"
s:codeRepository: https://github.com/LeonelGL/heatwise-class-guided
