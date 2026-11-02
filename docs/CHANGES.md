# Change history

The current implementation is `0.3.2` and provides two independent
CWL processors in one Docker image:

- Class-guided extraction and independent FULL/MASK3 endmember selection,
  with an optimized 15-band subset.
- Material-level abundance aggregation and Top-1 mapping from externally
  produced FCLS estimates.

The current source tree includes the real Sepolia v2 and GUSL reference
inputs, their STAC descriptor and a runnable example. Both processors
have regression and Docker/CWL tests, including versioned CWL packaging.

Scientific implementation details are in [Method](METHOD.md); interface
and release instructions are in [EOAP](EOAP.md) and [Release](RELEASE.md).
Archived development history is available in Git commits. Scientific
reference script hashes are in [Provenance](PROVENANCE.json).
