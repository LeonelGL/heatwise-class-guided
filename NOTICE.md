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

The real GUSL spectral library and real Sepolia CHIME-like raster were
used in earlier local/CI experiments. There is no independently verified
redistribution permission for either in the reviewed repository. These
files are excluded from the **current** code delivery tree. Deployment
requires separately staged, appropriately authorized datasets.

Synthetic spectra and synthetic raster fixtures are provided exclusively to
exercise the code. They are not ground-truth datasets or equivalent to the
real Sepolia validation scene.

Git history may contain earlier data versions. Removing tracked data from
the latest branch **does not remove it from earlier commits or existing
clones**; permanent removal would require a separately authorized history
rewrite and assessment of any existing public copies.

## Release guard

The GitHub Actions release workflow will reject a release when LICENSE is
missing and when the known real GUSL / Sepolia asset paths are present.
The Docker image includes code and dependencies, not those real datasets.
