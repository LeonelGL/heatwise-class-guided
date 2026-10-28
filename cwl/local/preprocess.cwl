cwlVersion: v1.2
class: CommandLineTool
id: class_guided
label: HEATWISE FULL local preprocessor
doc: >
  Local execution without a DockerRequirement. Match FULL once and optimize
  bands independently. Scientific outputs are an endmember XLSX and band JSON.
baseCommand:
  - python3
requirements: {}
arguments:
  - position: 0
    valueFrom: $(inputs.processor.path)
  - --output-dir
  - results
inputs:
  - id: input_catalog
    type: Directory
    label: Input STAC catalog
    doc: Locally staged single-item STAC catalog with one COG asset.
    inputBinding:
      prefix: --input-catalog
  - id: gusl
    type: File
    label: GUSL spectral library
    doc: Configured GUSL XLSX library, no ground truth.
    inputBinding:
      prefix: --gusl
  - id: config
    type: File
    label: Processing configuration
    doc: JSON or YAML configuration.
    inputBinding:
      prefix: --config
  - id: wavelengths
    type: File?
    label: Input wavelengths
    doc: Optional input image wavelength centers in micrometers.
    inputBinding:
      prefix: --wavelengths
  - id: processor
    type: File
    label: Python processor
    doc: Integrated Python scientific processor.
    default:
      class: File
      location: ../../class_guided_processor.py
outputs:
  products:
    type: Directory
    outputBinding:
      glob: results
$namespaces:
  s: https://schema.org/
s:softwareVersion: "0.3.1"
s:codeRepository: https://github.com/LeonelGL/heatwise-class-guided

