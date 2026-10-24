cwlVersion: v1.2
class: CommandLineTool
id: class_guided
label: HEATWISE class-guided preprocessing
doc: Extract candidates, match FULL, select bands, re-match MASK3 and emit aligned
  products.
baseCommand:
- python3
requirements:
  DockerRequirement:
    dockerPull: heatwise/class-guided:0.1.0
arguments:
- position: 0
  valueFrom: $(inputs.processor.path)
- --output-dir
- results
inputs:
- id: input_catalog
  type: Directory
  label: input catalog
  doc: Staged single-item STAC catalog, including local COG assets.
  inputBinding:
    prefix: --input-catalog
- id: gusl
  type: File
  label: gusl
  doc: External GUSL XLSX resource; no ground truth.
  inputBinding:
    prefix: --gusl
- id: config
  type: File
  label: config
  doc: JSON or YAML processing configuration.
  inputBinding:
    prefix: --config
- id: wavelengths
  type: File?
  label: wavelengths
  doc: Optional explicit input wavelength centers in micrometers.
  inputBinding:
    prefix: --wavelengths
- id: processor
  type: File
  label: processor
  doc: Integrated Python processor staged by CWL.
  default:
    class: File
    location: ../class_guided_processor.py
outputs:
  products:
    type: Directory
    outputBinding:
      glob: results
