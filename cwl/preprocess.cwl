cwlVersion: v1.2
class: CommandLineTool
id: class_guided
label: HEATWISE FULL and MASK3 class-guided preprocessor
doc: >
  Extract scene-derived candidates, perform FULL spectral matching, optimize
  15 bands from FULL endmembers and independently re-match using MASK3.
  Export full-length selected_endmembers_FULL.xlsx and
  selected_endmembers_MASK3.xlsx, backward-compatible selected_endmembers.xlsx
  (FULL), selected_bands.json, mask3_matching_bands.json, diagnostics and STAC.
  All exported signatures retain all usable image bands. No FCLS or reduced
  image products are generated.
baseCommand:
  - python3
  - /app/class_guided_processor.py
requirements:
  DockerRequirement:
    dockerPull: heatwise/class-guided:0.3.2
arguments:
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
outputs:
  products:
    type: Directory
    outputBinding:
      glob: results
$namespaces:
  s: https://schema.org/
s:softwareVersion: "0.3.2"
s:version: "0.3.2"
s:codeRepository: https://github.com/LeonelGL/heatwise-class-guided
