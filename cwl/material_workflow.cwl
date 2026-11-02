cwlVersion: v1.2
class: Workflow
id: material_top1
label: HEATWISE material Top-1 after official FCLS
doc: >
  Independently packaged optional postprocessing EOAP. Stage official FCLS
  outputs through their STAC catalog and aggregate endmember abundances into
  material classes using the selected class-guided grouping. The FCLS
  processor is external and unchanged.
inputs:
  fcls_outputs:
    type: Directory
    label: Official FCLS STAC output
  selected_endmembers:
    type: File
  class_mapping:
    type: File
  mode:
    type: string
  fcls_class_names:
    type: File
  fcls_metadata:
    type: File
  acquisition_datetime:
    type: string
  output_prefix:
    type: string
    default: HEATWISE_FCLS
  min_abundance:
    type: "float?"
steps:
  aggregate:
    run: material_postprocess.cwl
    in:
      fcls_outputs: fcls_outputs
      selected_endmembers: selected_endmembers
      class_mapping: class_mapping
      mode: mode
      fcls_class_names: fcls_class_names
      fcls_metadata: fcls_metadata
      acquisition_datetime: acquisition_datetime
      output_prefix: output_prefix
      min_abundance: min_abundance
    out:
      - products
outputs:
  products:
    type: Directory
    outputSource: aggregate/products
$namespaces:
  s: https://schema.org/
s:softwareVersion: "0.3.2"
s:version: "0.3.2"
s:codeRepository: https://github.com/LeonelGL/heatwise-class-guided
