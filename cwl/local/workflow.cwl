cwlVersion: v1.2
class: Workflow
id: main
label: HEATWISE FULL local workflow
doc: >
  Local no-Docker workflow: produce FULL-selected spectral endmembers and
  independent band list; no MASK3, reduced raster, or FCLS execution.
inputs:
  - id: input_catalog
    type: Directory
    label: Input STAC catalog
    doc: Locally staged single-item STAC catalog with one COG asset.
  - id: gusl
    type: File
    label: GUSL spectral library
    doc: Configured GUSL XLSX library, no ground truth.
  - id: config
    type: File
    label: Configuration
    doc: JSON or YAML configuration.
  - id: wavelengths
    type: File?
    label: Input wavelengths
    doc: Optional input image wavelength centers in micrometers.
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
s:codeRepository: https://github.com/LeonelGL/heatwise-class-guided
