# EOAP readiness — review against OGC 20-089r1

Reference: https://docs.ogc.org/bp/20-089r1.html (reviewed 2026-10-26). This is a Best Practice, not an ESA certification. The platform owner must confirm project-specific acceptance criteria.

| Requirement / delivery concern | Implementation and evidence | Remaining action |
|---|---|---|
| Command-line application | Python 3.11 CLI; explicit arguments and failure exit status | Real-scene execution |
| Container | Dockerfile and pinned Python dependencies; build/run passed CI 40362481432 | Base digest pinning |
| Application Package | CWL Workflow plus CommandLineTool, baseCommand, DockerRequirement | Target-platform runner acceptance (containerized cwltool passed CI) |
| Input descriptions | id, label, doc, typed input catalog, GUSL/config Files | Platform mapping of stage-in |
| STAC staged input | Local catalog.json with Item/COG; GUSL separate | Remote staging by target platform |
| STAC staged output | catalog.json, Item with footprint/acquisition time, relative assets including diagnostics | Platform stage-out acceptance |
| Spectral interface | COG + XLSX + TXT; no MAT; alignment checked | Real Sepolia v2 and complete GUSL |
| Reproducibility | Seed, effective configuration, versions, hashes, original-source tests | Validate full real experiment |
| Docker image reference | heatwise/class-guided:0.2.0 local tag | Publish authorized registry image, pin digest and update CWL |
| Provenance/license | NOTICE.md, original sources, methodology changes | Owner-approved release license; GUSL redistribution/access conditions |
| Automated validation | Read-only GitHub Actions runs tests, Docker and containerized CWL | Run 40362481432 passed; repeat on target platform |

No deployment to the official ESA repository or image publication is performed by this repository's CI. CI has contents:read and does not push commits or publish packages. A successful CI run still does not establish real-scene scientific reproduction or ESA target-platform acceptance.
