# Preparing a versioned ESA HEATWISE class-guided EOAP release

This procedure follows the strategy in
[ESA-Heatwise/heatwise-patch-extraction PR #3](https://github.com/ESA-Heatwise/heatwise-patch-extraction/pull/3).

The automated workflow is stored in .github/workflows/release.yml and runs
**only after a version tag is pushed**. Committing the workflow to a feature
branch does not publish a Docker image, tag or GitHub Release.

## What gets published

For tag v0.3.2 (example), the release workflow:

1. Verifies the tag is a fixed version and a project-approved LICENSE exists.
2. Runs the Python tests and generates version-pinned CWLs.
3. Runs cwltool --pack to produce heatwise_class_guided.cwl, a standalone CWL
   document that contains both the Workflow and CommandLineTool.
4. Builds ghcr.io/<repository-owner>/<repository-name>:0.3.2 with matching
   OCI version and source labels.
5. Executes a synthetic CWL + Docker test with that exact tagged image and
   validates the FULL/MASK3/STAC outputs.
6. Only after successful testing, pushes the Docker image and creates a GitHub
   Release attaching the packed CWL, the original two-CWL ZIP, separate
   workflow.cwl and preprocess.cwl, README.md, NOTICE.md and LICENSE.

The paired CWLs must be downloaded together to preserve the relative reference
"run: preprocess.cwl". The autonomous heatwise_class_guided.cwl is preferable
for an EOAP demonstration or a single direct download.

The release generator updates s:version, s:softwareVersion, s:codeRepository
and dockerPull **in staged release assets only**. Source CWLs remain unchanged.

## Test the release preparation without publishing

Run from the repository root:

    python tools/prepare_release.py --version 0.3.2 \
      --image ghcr.io/leonelgl/heatwise-class-guided:0.3.2 \
      --repository-url https://github.com/LeonelGL/heatwise-class-guided \
      --output-dir results/release-smoke

    python -m cwltool --validate results/release-smoke/cwl/workflow.cwl
    python -m cwltool --pack results/release-smoke/cwl/workflow.cwl > \
      results/release-smoke/heatwise_class_guided.cwl
    python -m cwltool --validate results/release-smoke/heatwise_class_guided.cwl

The pull-request validation workflow performs these checks automatically.

## Before creating the first formal ESA tag

- Obtain authorization for the source-code LICENSE and confirm whether the
  actual Sepolia image and real GUSL XLSX may be redistributed.
- Review the repository and CWL input/output contract with Hannes.
- Move or mirror the approved final code into ESA-Heatwise, as agreed with
  the project team. The workflow automatically publishes to the namespace
  matching github.repository, so no hardcoded personal account remains in the
  release assets.
- Confirm GitHub Actions is authorized to write repository contents and GHCR
  packages and that any required package/repository policies are satisfied.
- Confirm the final version number, possibly v0.3.2; no release tag has been
  created by the release preparation work.
- Keep tags fixed: do not overwrite already-published version tags or Docker
  tags. Git tag names alone do not technically prevent owners from retagging;
  enforce immutability with organization tag protection/rules where available.

Only then, from a properly reviewed and merged commit in the intended
repository, create and push the final tag:

    git tag -a v0.3.2 -m "HEATWISE class-guided v0.3.2"
    git push origin v0.3.2

This activates the release workflow.

## Important limitations

The release workflow checks packaging and synthetic execution, **not**
scientific classification accuracy or actual FCLS abundance outputs.
The class-guided preprocessor remains a separate EOAP feeding the established
HySUPP unmixing EOAP. The final integrated pipeline CWL may need to point to
specific image versions of both components.
