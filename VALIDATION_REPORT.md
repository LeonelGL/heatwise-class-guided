# Validation report — HEATWISE class-guided 0.3.1

## Intended scientific contract

- Process scene reflectance with PPI-like candidate extraction and GUSL
  class-guided FULL SAM/MBDSA matching.
- Select endmembers exactly once from FULL comparisons; never rerun
  class assignment with MASK3.
- Export **all usable** endmember wavelengths to `selected_endmembers.xlsx`.
- Independently optimize 15 bands to `selected_bands.json`.
- Do not generate a reduced raster or execute the official FCLS.
- Emit supporting diagnostics and STAC metadata referencing all existing
  output files using relative asset paths.

FULL comparisons use the **global common finite-band intersection** of
scene candidates and GUSL signatures, which may contain fewer bands than
the exported usable endmember grid. `full_metric_bands` and
`endmember_spectral_bands` must be examined in actual runs.

## Verification status (do not confuse with execution evidence)

| Check | State | Evidence / required follow-up |
| --- | --- | --- |
| `class_guided_processor.py` in working branch | Implemented | FULL-only pipeline with version `0.3.1`; exact commit history in GitHub |
| Unit/kernel parity tests | Test definitions updated | Run `python -m pytest tests -q` and review results for current commit |
| Synthetic end-to-end FULL export | Test defined | `test_end_to_end_full_only_reproducible`; execute on current commit |
| Two-product/STAC validation | Validator updated | Run `python tools/validate_outputs.py results/ci/results` |
| CWL static validation | Workflow documents being updated | Run `python -m cwltool --validate cwl/workflow.cwl` |
| Local CWL static validation | Local definitions being updated | Run `python -m cwltool --validate cwl/local/workflow.cwl` |
| Docker build and execution | Not yet independently verified for 0.3.0 | Check new GitHub Actions run |
| Real 250-band Sepolia V2 | Not validated | Supply real image and authoritative band metadata |
| Complete real GUSL XLSX | Not validated | Check coverage/sheets and signatures |
| `GUSL_catalog_all.csv` integration | Not implemented in current reader | Audit catalogue role; do not claim consumed |
| Official FCLS input compatibility | Not established by current synthetic tests | Check usable wavelength grid and consumer behavior |
| ESA platform interoperability | Not established | Acceptance on designated stage-in/stage-out environment |

### Historical checks from 0.2.0 — NOT current version evidence

Previous repository documentation reports 19 tests passing on v0.2.0,
a successful Docker/containerized CWL run
[40362481432](https://github.com/LeonelGL/heatwise-class-guided/actions/runs/40362481432),
and a successful 250-band **synthetic** preprocessor experiment using a
reduced number of band combinations. Those checks pertain to the former
MASK3/reduced-raster output contract and are **not v0.3.0 validation**.

The directories `examples/output`, `examples/output_250`, and
`examples/output_500k` may still contain old reduced-raster synthetic
artifacts. They are retained as historical records only and are not
current 0.3.0 exemplars.

## Commands for v0.3.0 verification

```bash
python -m pip install -r requirements-lock-python311.txt
python -m pytest tests -q
python -m cwltool --validate cwl/workflow.cwl
python -m cwltool --validate cwl/local/workflow.cwl
docker build -t heatwise/class-guided:0.3.0 .
python -m cwltool --outdir results/ci cwl/workflow.cwl examples/job_synthetic.yml
python tools/validate_outputs.py results/ci/results
```

Check the GitHub Actions run for the actual branch commit. A green run
establishes the synthetic packaging/tests for that revision only.
Do not infer real-scene classification accuracy or ESA certification.

## Scientific checks required on real Sepolia CHIME v2

1. Confirm original spectral centers, CRS, nodata, source scale/offset,
   acquisition date/time and the actual gap mask for Sepolia.
2. Verify both expected GUSL XLSX sheets and class prefixes, material
   naming and spectral support. Clarify the separate CSV catalogue.
3. Compare usable-image band count versus FULL common comparison-band
   count; identify exactly which wavelengths contributed to SAM/MBDSA.
4. Inspect selected urban spectra, endmember class counts and
   asphalt/concrete margin diagnostics; reject physically implausible fits.
5. Confirm the 15 selected wavelength indices/spacing and show that they
   have no effect on the already-fixed FULL endmember signatures.
6. Validate spectral radiometry and interpolation between the selected
   endmembers and the original full image in the external official FCLS.
7. Evaluate accuracy/uncertainty against available reference material
   points and record per-class error mechanisms.
8. Repeat from a clean environment with versioned inputs/configuration,
   matching input checksums and output provenance.

No v0.3.0 scientific accuracy claim is made here.

## 0.3.1 general missing-class fallback (provisional)

The generic policy is enabled by default for every missing target class,
not by a scene-specific exception. It finds the best **unused scene-derived**
signatures within a configurable FULL SAM ceiling against all GUSL examples
for each missing class. A joint assignment prevents reuse of one candidate
by different classes. No class is fabricated if this criterion is not met.

Local checks performed when preparing the change:
- seven targeted unit tests passed;
- the archived real Sepolia FULL matrices recovered terracotta and metal
  provisionally as two distinct candidates, with SAM angles below 8 degrees;
- a separate synthetic end-to-end run exported all usable wavelengths and
  15 independent selected bands and did not activate fallback when no class
  was missing. The STAC stage was replaced by a local stub in this run
  because this sandbox lacks pystac; GitHub Actions must verify STAC/CWL.

The new workflow on GitHub Actions and independent material validation with
reference samples **remain unverified** until executed on the final commit.
