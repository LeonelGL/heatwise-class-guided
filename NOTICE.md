# Software provenance, third-party data, and release rights

The HEATWISE class-guided preprocessor integrates scene-candidate extraction,
GUSL-assisted material matching and spectral-band selection originally
developed for HEATWISE. Source audit versions are preserved in reference/
and recorded by content hashes in docs/PROVENANCE.json. The separately
maintained official HySUPP/FCLS software is **not copied or executed** here.

## Source-code license

The HEATWISE project agreed to publish formal software deliverables as
open source. Hannes Neuschmidt requested a LICENSE file for every deliverable
on 14 September 2026 and named MIT, GPLv3 and Apache-2.0 as **examples**.
No specific license has yet been approved for this processor, and this
NOTICE does not grant a license. Confirm the appropriate copyright holder
and license text with the responsible project institution before releasing.

## Third-party test data

The Sepolia CHIME-like reference raster and GUSL spectral workbook used in
the original HEATWISE experiments are now **intentionally included** under
`examples/sepolia/` and `examples/resources/`, respectively, with their
STAC input metadata and a reproducible CWL job. This is a scientific
reproducibility choice requested by the repository owner. It does not
constitute a verified third-party redistribution license for the GUSL
library or the Sepolia image. Confirm provenance, attribution and permission
before transferring these assets to another publishing organization.

Synthetic spectra and synthetic raster fixtures are provided exclusively to
exercise the code. They are not ground-truth datasets or equivalent to the
real Sepolia validation scene.

Git history may contain earlier data versions. Removing tracked data from
the latest branch **does not remove it from earlier commits or existing
clones**; permanent removal would require a separately authorized history
rewrite and assessment of any existing public copies.

## Release guard

The GitHub Actions release workflow rejects a formal release when the
project-approved source LICENSE is missing; it now checks that the bundled
reference data are present. The Docker image intentionally contains code
and dependencies only; the CWL runner stages the reference inputs as files
from the checked-out repository.
