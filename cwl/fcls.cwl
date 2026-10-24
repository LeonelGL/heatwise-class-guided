cwlVersion: v1.2
class: CommandLineTool
id: fcls
label: Existing HEATWISE FCLS
doc: Unchanged upstream FCLS core and raster writers, with corrected STAC packaging.
baseCommand:
- python3
requirements:
  DockerRequirement:
    dockerPull: heatwise/class-guided:0.1.0
arguments:
- position: 0
  valueFrom: $(inputs.adapter.path)
- --output-dir
- results
inputs:
- id: prepared
  type: Directory
  label: prepared
  doc: Aligned preprocessor products.
  inputBinding:
    prefix: --prepared
- id: upstream
  type: Directory
  label: upstream
  doc: Reviewed upstream processor snapshot.
  default:
    class: Directory
    location: ../upstream
  inputBinding:
    prefix: --upstream
- id: adapter
  type: File
  label: adapter
  doc: Thin adapter reusing upstream FCLS.
  default:
    class: File
    location: ../fcls_adapter.py
outputs:
  products:
    type: Directory
    outputBinding:
      glob: results
