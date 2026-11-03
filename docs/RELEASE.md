# Versioned EOAP release

The GitHub Actions workflow `.github/workflows/release.yml` triggers when a
tag matching `vMAJOR.MINOR.PATCH` (optionally with a prerelease suffix) is
pushed. It builds both EOAPs against the same versioned Docker image.

## Release assets

- `heatwise_class_guided.cwl`: packed class-guided preprocessor.
- `heatwise_material_top1.cwl`: packed material postprocessor.
- `workflow.cwl`, `preprocess.cwl`, `material_workflow.cwl`,
  `material_postprocess.cwl`: the four corresponding CWL sources.
- `heatwise-class-guided-cwl-v<VERSION>.zip`: source CWL pairs.
- `README.md`, `NOTICE.md`, `LICENSE` and material aggregation instructions.
- Docker image: `ghcr.io/<owner>/<repo>:<VERSION>`.

Release CWLs reference that exact Docker image tag rather than `latest`.
The publishing workflow checks the source checksum manifest, runs regression
tests, validates the CWL files, builds the tagged image and smoke-tests
both processors before publication. These tests use synthetic processing
inputs; they do not run the official FCLS processor.

## Check packaging without publishing

From the repository root, with the dependencies in `requirements.txt` installed:

```bash
python tools/refresh_manifest_v032.py --check

python tools/prepare_release.py \
  --version 0.3.2 \
  --image ghcr.io/leonelgl/heatwise-class-guided:0.3.2 \
  --repository-url https://github.com/LeonelGL/heatwise-class-guided \
  --output-dir results/release-check

python -m cwltool --pack results/release-check/cwl/workflow.cwl \
  > results/release-check/heatwise_class_guided.cwl

python -m cwltool --pack results/release-check/cwl/material_workflow.cwl \
  > results/release-check/heatwise_material_top1.cwl
```

`tools/prepare_release.py` updates version, repository and Docker references
only in its generated output; source CWLs remain unchanged. The CI workflow
checks the packed CWLs against locally tagged images without pushing them.

## Before publishing

- Supply the project-approved software `LICENSE`. The release workflow
  currently stops if it is missing.
- Confirm attribution and redistribution conditions for the bundled GUSL
  library and Sepolia image separately from the software license.
- Agree the release version and repository ownership.
- Verify GitHub Actions has permission to publish the Docker image to GHCR
  and attach release assets.
- Keep version tags and published images immutable.

No new license is selected by the tooling, and publishing a tagged release
does not establish scientific classification accuracy.
