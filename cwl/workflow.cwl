cwlVersion: v1.2
class: Workflow
id: main
label: HEATWISE scene-specific endmembers
doc: EOAP staged STAC input and self-contained output directory.
inputs:
- id: input_catalog
  type: Directory
  label: input catalog
  doc: Staged single-item STAC catalog, including local COG assets.
- id: gusl
  type: File
  label: gusl
  doc: External GUSL XLSX resource; no ground truth.
- id: config
  type: File
  label: config
  doc: JSON or YAML processing configuration.
- id: wavelengths
  type: File?
  label: wavelengths
  doc: Optional explicit input wavelength centers in micrometers.
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
