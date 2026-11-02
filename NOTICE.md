# Provenance and data-use notice

This repository implements class-guided selection of urban endmembers
and subsequent material-level aggregation of externally computed FCLS
abundances. The scientific reference implementations are retained under
`reference/`; their checksums are recorded in `docs/PROVENANCE.json`.
The official HySUPP/FCLS executable is **not included**.

## Bundled scientific data

For reproducibility, the repository includes:

- `examples/resources/GUSL_spectra_by_material_headers.xlsx`
- `examples/sepolia/Sepolia_CHIME_Thermopolis_v2_COG.tif`
- The Sepolia STAC catalog and a CWL example.

The original Git blob identifiers and input details are recorded in
`docs/REFERENCE_DATA.json`. Inclusion is not, by itself, a grant of
a third-party data license. Attribution and redistribution conditions
for these inputs must be confirmed before republishing them through a
different organization or distribution channel.

## Software licensing

A project-approved `LICENSE` has not yet been added. The formal GitHub
Release workflow requires it before publishing versioned software assets.

Docker distributes the Python code and pinned dependencies, not copies
of the reference GUSL workbook or Sepolia image. CWL stages those files
from the checked-out repository when running the example.
