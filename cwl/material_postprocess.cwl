cwlVersion: v1.2
class: CommandLineTool
id: material_postprocess
label: HEATWISE FCLS endmember-to-material postprocessor
doc: >
  Independent post-FCLS stage: read an official FCLS STAC output directory
  and corresponding material mapping, sum endmember abundances by material,
  and write material-abundance and Top-1 GeoTIFFs with valid STAC metadata.
  Does not execute or alter the official FCLS processor.
baseCommand:
  - python3
  - /app/aggregate_fcls_classes.py
requirements:
  DockerRequirement:
    dockerPull: heatwise/class-guided:0.3.2
arguments:
  - --output-dir
  - results
inputs:
  fcls_outputs:
    type: Directory
    label: Official FCLS output STAC directory
    doc: Contains catalog.json with an abundance asset and its local raster.
    inputBinding:
      prefix: --fcls-output-dir
  selected_endmembers:
    type: File
    label: Endmember XLSX actually used by FCLS
    inputBinding:
      prefix: --selected-endmembers
  class_mapping:
    type: File
    label: Class-guided class mapping
    doc: diagnostics/endmember_classes.json from matching class-guided run.
    inputBinding:
      prefix: --class-mapping
  mode:
    type: string
    label: Class-guided selection mode
    doc: FULL or MASK3. Must match the selected endmember spreadsheet.
    inputBinding:
      prefix: --mode
  fcls_class_names:
    type: File
    label: Official FCLS class_names JSON
    inputBinding:
      prefix: --fcls-class-names
  fcls_metadata:
    type: File
    label: Official FCLS run_metadata JSON
    inputBinding:
      prefix: --fcls-metadata
  acquisition_datetime:
    type: string
    label: Original scene acquisition timestamp with timezone
    doc: >
      ISO8601 with explicit timezone. Official FCLS STAC dates may describe
      processing rather than acquisition; do not infer from processing time.
    inputBinding:
      prefix: --acquisition-datetime
  output_prefix:
    type: string
    default: HEATWISE_FCLS
    inputBinding:
      prefix: --output-prefix
  min_abundance:
    type: "float?"
    doc: Optional classification threshold applied AFTER class aggregation.
    inputBinding:
      prefix: --min-abundance
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
