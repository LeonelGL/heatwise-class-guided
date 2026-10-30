"""Scientific regression tests for FULL+MASK3 without changing spectrum length."""
import json
from pathlib import Path
import importlib.util
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

PROCESSOR = Path(__file__).resolve().parents[1] / 'class_guided_processor.py'
spec = importlib.util.spec_from_file_location('heatwise_dual', PROCESSOR)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_mask3_never_truncates_selected_spectra(tmp_path):
    """Matching uses 15 only, exported endmembers retain all 32 spectral values."""
    rng = np.random.default_rng(42)
    L = 32
    wl = np.linspace(.42, 2.45, L)
    n_candidates = 30
    base = np.vstack([.14 + .02 * np.sin(wl * 3),
                      .26 + .025 * np.cos(wl * 4),
                      .09 + .05 * np.sin(wl * 2)])
    scene = np.vstack([base[i % 3] + rng.normal(0, .003, L)
                       for i in range(n_candidates)]).astype(np.float32)
    library = base.astype(np.float32)
    names = [f'CAND_{i:03d}' for i in range(n_candidates)]
    libnames = ['Asphalt_1', 'Concrete_1', 'Vegetation_1']
    cfg = {'FINAL_TARGET_CLASSES': ['asphalt_road', 'concrete', 'vegetation'],
           'TARGET_CLASS_PREFIXES': {'asphalt_road': ['Asphalt'], 'concrete': ['Concrete'],
                                     'vegetation': ['Vegetation']},
           'TOP_K': 3,
           'FALLBACK_ENABLED': False}
    matcher = module.Matching(cfg)
    full, full_mask = module.match_candidates(matcher, scene, wl, names, library, libnames,
                                            'FULL', tmp_path, True)
    mask = np.zeros(L, bool)
    mask[np.arange(15)] = True
    sparse, sparse_mask = module.match_candidates(matcher, scene, wl, names, library, libnames,
                                                 'MASK3', tmp_path, True, comparison_mask=mask)
    assert full_mask.sum() == 32
    assert sparse_mask.sum() == 15
    assert len(full) >= 2 and len(sparse) >= 2
    for v in list(full.values()) + list(sparse.values()):
        assert v.shape == (L,)
    assert len(module.make_endmembers_dataframe(full, wl)) == L
    assert len(module.make_endmembers_dataframe(sparse, wl)) == L
    assert json.loads((tmp_path / 'MASK3_fallback_report.json').read_text())['mode'] == 'MASK3'


def test_mask3_fixed_wavelength_mapping_and_rejects_invalid():
    wl = np.linspace(.40, 2.50, 26)
    eligible = np.ones(len(wl), bool)
    selected = np.arange(15)
    cfg = {'matching': {'MASK3_N_BANDS': 15, 'MASK3_SOURCE': 'fixed',
                        'MASK3_WAVELENGTHS_UM': (wl[np.arange(15)] + .001).tolist(),
                        'MASK3_MAX_DELTA_UM': .01}}
    indices, info = module.resolve_mask3_indices(wl, eligible, selected, cfg)
    np.testing.assert_array_equal(indices, np.arange(15))
    assert max(info['absolute_deviation_um']) <= .0010001
    cfg['matching']['MASK3_WAVELENGTHS_UM'][0] = .05
    with pytest.raises(ValueError, match='No usable MASK3 band near'):
        module.resolve_mask3_indices(wl, eligible, selected, cfg)
    cfg['matching']['MASK3_WAVELENGTHS_UM'] = wl[[0] * 15].tolist()
    with pytest.raises(ValueError, match='distinct'):
        module.resolve_mask3_indices(wl, eligible, selected, cfg)


def test_mask3_auto_uses_full_optimized_indices():
    wl = np.linspace(.44, 2.40, 27)
    full = np.ones(len(wl), bool)
    idx = np.arange(15)
    cfg = {'matching': {'MASK3_N_BANDS': 15, 'MASK3_SOURCE': 'auto',
                        'MASK3_WAVELENGTHS_UM': [], 'MASK3_MAX_DELTA_UM': .01}}
    resolved, info = module.resolve_mask3_indices(wl, full, idx, cfg)
    np.testing.assert_array_equal(idx, resolved)
    assert info['source'] == 'auto'
    assert len(info['actual_wavelengths_um']) == 15


def test_dual_output_pipeline_keeps_same_full_grid(tmp_path, monkeypatch):
    """Synthetic end-to-end run; STAC mocked because pystac is absent locally."""
    rng = np.random.default_rng(15)
    L, H, W = 40, 23, 25
    wl = np.linspace(.4, 2.5, L)
    asphalt = .10 + .025 * np.sin(wl * 3)
    concrete = .24 + .025 * np.cos(wl * 3)
    vegetation = .07 + .09 * np.exp(-((wl - 1.1) / .55)**2)
    templates = np.vstack([asphalt, concrete, vegetation])
    cl = np.indices((H, W))[1] % 3
    cube = np.empty((L, H, W), dtype=np.float32)
    for row in range(H):
        for col in range(W):
            cube[:, row, col] = templates[cl[row, col]] * (
                1 + rng.normal(0, .04)) + rng.normal(0, .005, L)
    tif = tmp_path / 'synthetic.tif'
    with rasterio.open(tif, 'w', driver='GTiff', width=W, height=H, count=L,
                       dtype='float32', crs='EPSG:4326',
                       transform=from_origin(12, 43, .001, .001)) as dst:
        dst.write(cube)
        for i, wavelength in enumerate(wl, 1):
            dst.set_band_description(i, f'{wavelength:.12f}')
    gusl = tmp_path / 'gusl.xlsx'
    df = pd.DataFrame({'wavelength_um': wl,
                       'Asphalt_1': asphalt, 'Concrete_1': concrete,
                       'Vegetation_1': vegetation})
    with pd.ExcelWriter(gusl) as writer:
        df.to_excel(writer, sheet_name='BRUSSELS_APEX_GENLIB', index=False)
        df.to_excel(writer, sheet_name='DLR', index=False)
    cfg = module.load_config(None)
    cfg['vegetation_mode'] = 'all'
    cfg['extraction'].update({'MIN_FINAL': 5, 'MAX_FINAL': 35,
                              'N_RANDOM_PROJECTIONS': 35,
                              'TOP_PPI_CANDIDATES_PER_STRATUM': 30,
                              'N_PCA_COMPONENTS': 3,
                              'DEDUP_SAM_DEG': .2})
    cfg['matching'].update({'GUSL_SHEETS': ['BRUSSELS_APEX_GENLIB', 'DLR'],
                            'FINAL_TARGET_CLASSES': ['asphalt_road','concrete','vegetation'],
                            'FALLBACK_ENABLED': False,
                            'TOP_K': 6,
                            'MASK3_SOURCE': 'auto'})
    cfg['bands'].update({'PRESELECT_TOP_BANDS': 30, 'N_RANDOM_COMBINATIONS': 60,
                         'N_FINAL_BANDS': 15, 'MIN_SPACING_UM': .04})
    cfg['acquisition_datetime'] = '2009-07-18T12:00:00Z'
    cfg['export_intermediates'] = False
    monkeypatch.setattr(module, 'write_stac', lambda *a, **k: None)
    previous_version = module.importlib.metadata.version
    monkeypatch.setattr(module.importlib.metadata, 'version',
                        lambda p: '0.0' if p == 'pystac' else previous_version(p))
    out = tmp_path / 'results'
    result = module.run(tif, gusl, out, cfg)
    assert result['status'] == 'success'
    assert result['endmember_selection_modes'] == ['FULL', 'MASK3']
    assert result['mask3_metric_bands'] == 15
    assert result['endmember_spectral_bands'] == L
    full = pd.read_excel(out / 'selected_endmembers_FULL.xlsx')
    mask3 = pd.read_excel(out / 'selected_endmembers_MASK3.xlsx')
    alias = pd.read_excel(out / 'selected_endmembers.xlsx')
    assert len(full) == L and len(mask3) == L
    np.testing.assert_array_equal(full['wavelength_um'], mask3['wavelength_um'])
    pd.testing.assert_frame_equal(alias, full)
    assert len(mask3.columns) >= 3
    assert result['mask3_reselection'] is True
    assert (out / 'diagnostics' / 'MASK3_class_assignments.csv').exists()
    assert (out / 'diagnostics' / 'FULL_class_assignments.csv').exists()
    assert len(json.loads((out / 'mask3_matching_bands.json').read_text())['matching_grid_indices_base0']) == 15
