"""Scientific regression and FULL-only export tests for HEATWISE v0.3.0.

Original-kernel parity checks use reference/ scripts; the end-to-end test uses
only synthetic data. No real Sepolia accuracy or ESA acceptance is claimed.
"""
import ast
import json
import math
import random
import re
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from scipy.interpolate import PchipInterpolator
from sklearn.decomposition import PCA

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import class_guided_processor as p

ROOT = Path(__file__).resolve().parents[1]


def original(pattern):
    """Load reference function definitions, without executing Windows boot/main."""
    path = next((ROOT / 'reference').glob(pattern))
    tree = ast.parse(path.read_text(encoding='utf-8'))
    keep = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Assign))]
    ns = dict(
        np=np, pd=pd, Path=Path, re=re, math=math, random=random,
        combinations=combinations, PchipInterpolator=PchipInterpolator, PCA=PCA,
    )
    exec(compile(ast.Module(body=keep, type_ignores=[]), 'original', 'exec'), ns)
    return ns


def test_material_grouping():
    names = [
        'asphalt_road_1', 'asphalt_road_2', 'asphalt_road_3',
        'concrete_1', 'concrete_2', 'concrete_3',
        'metal', 'metal_roof', 'roof_dark_1', 'roof_light_1',
    ]
    groups = p.infer_groups(names)
    assert len(groups['asphalt_road']) == 3
    assert len(groups['concrete']) == 3
    assert 'metal_roof' in groups and 'roof_dark_1' in groups
    assert p.infer_groups(['concrete__1', 'concrete__2']) == {
        'concrete': ['concrete__1', 'concrete__2']
    }


def test_excel_order_and_original_bug(tmp_path):
    path = tmp_path / 'spectra.xlsx'
    pd.DataFrame({
        'wavelength_um': [.8, .4, .6], 'Asphalt': [8, 4, 6]
    }).to_excel(path, index=False)
    w, x, *_ = p.Matching().read_spectral_library_excel(path)
    np.testing.assert_allclose(w, [.4, .6, .8])
    np.testing.assert_equal(x, [[4, 6, 8]])
    _, wrong, *_ = original('Comparar*')['read_spectral_library_excel'](path)
    assert not np.array_equal(wrong, x)


def test_pchip_no_extrapolation_parity():
    wl = np.array([.4, .6, .8, 1.])
    spectra = np.array([[.1, np.nan, .4, .3], [.2, .3, .4, .5]])
    target = np.array([.3, .4, .5, .7, 1., 1.2])
    got = p.Matching().pchip_library_to_target_grid(wl, spectra, target)
    expected = original('Comparar*')['pchip_library_to_target_grid'](
        wl, spectra, target
    )
    np.testing.assert_equal(got, expected)
    assert np.isnan(got[:, [0, -1]]).all()


def test_global_finite_intersection_parity():
    scene = np.array([[.1, .2, .3, .4], [.4, .3, .2, .1]])
    lib = np.array([[np.nan, .2, .3, .5], [.1, .3, .4, .6]])
    got = p.Matching().compute_similarity_matrices(scene, lib)
    expected = original('Comparar*')['compute_similarity_matrices'](scene, lib)
    for a, b in zip(got, expected):
        np.testing.assert_equal(a, b)
    np.testing.assert_equal(got[2], [False, True, True, True])


def test_insufficient_overlap():
    with pytest.raises(RuntimeError):
        p.Matching().compute_similarity_matrices(
            np.ones((2, 3)), np.array([[np.nan, np.nan, 1]])
        )


@pytest.mark.parametrize('exact', [False, True])
def test_band_metrics_and_fast_combinations_parity(exact):
    old = original('select*')
    rng = np.random.default_rng(4)
    wl = np.linspace(.4, 2.5, 24)
    groups = {
        k: rng.uniform(.1, .8, (3 if exact else 1, 24)).astype('float32')
        for k in ['a', 'b', 'c']
    }
    selector = p.BandSelection()
    combos = list(combinations(range(8), 4))
    expected = old['evaluate_combinations'](wl, groups, combos, exact)
    got = p.evaluate_combinations_fast(selector, wl, groups, combos, exact)
    np.testing.assert_allclose(
        got[['avg_sep', 'min_sep']], expected[['avg_sep', 'min_sep']],
        rtol=2e-6, atol=1e-7,
    )
    a = selector.compute_single_band_scores(wl, groups, exact)
    b = old['compute_single_band_scores'](wl, groups, exact)
    pd.testing.assert_frame_equal(a, b)


def test_ppi_and_pruning_parity():
    old = original('Extraer*')
    old.update(
        N_RANDOM_PROJECTIONS=20,
        TOP_PPI_CANDIDATES_PER_STRATUM=20,
        N_PCA_COMPONENTS=5,
    )
    ex = p.Extraction({
        k: old[k]
        for k in [
            'N_RANDOM_PROJECTIONS', 'TOP_PPI_CANDIDATES_PER_STRATUM',
            'N_PCA_COMPONENTS',
        ]
    })
    cube = np.random.default_rng(7).uniform(.1, .8, (8, 8, 24)).astype('float32')
    valid = np.ones((8, 8), bool)
    got = ex.ppi_like_candidates(cube, valid, np.random.default_rng(42))
    expected = old['ppi_like_candidates'](cube, valid, np.random.default_rng(42))
    for a, b in zip(got, expected):
        np.testing.assert_equal(a, b)
    a = ex.local_pruning(cube, valid, cube.mean(2), *got, 'dark')
    b = old['local_pruning'](cube, valid, cube.mean(2), *expected, 'dark')
    assert len(a) == len(b)
    for x, y in zip(a, b):
        for key in x:
            np.testing.assert_equal(x[key], y[key])


def test_matching_bundle_parity():
    old = original('Comparar*')
    m = p.Matching()
    rng = np.random.default_rng(7)
    X = rng.uniform(.1, .7, (18, 30)).astype('float32')
    names = [f'CAND_{i:02d}' for i in range(18)]
    ln = [
        ('Asphalt' if i < 6 else 'Concrete' if i < 12 else 'Metal') + f'_{i}'
        for i in range(18)
    ]
    sam, mbd, _ = m.compute_similarity_matrices(X, X.copy())
    top = m.build_top_matches_dataframe(names, ln, sam, mbd, 'sam', 50)
    a = m.add_acceptance_flags(
        m.summarize_candidates_by_target_class(top, m.TARGET_CLASS_PREFIXES)
    )
    b = old['add_acceptance_flags'](
        old['summarize_candidates_by_target_class'](top, m.TARGET_CLASS_PREFIXES)
    )
    pd.testing.assert_frame_equal(a, b)
    aa = m.select_asphalt_concrete_x3('FULL', a, names, X, X, np.arange(30))
    bb = old['select_asphalt_concrete_x3']('FULL', b, names, X, X, np.arange(30))
    for x, y in zip(aa, bb):
        pd.testing.assert_frame_equal(x, y)


def test_spacing():
    s = p.BandSelection()
    wl = np.linspace(.4, 2.5, 120)
    freq = pd.DataFrame({
        'band_idx': range(120), 'wavelength_um': wl,
        'freq_total': np.arange(120), 'freq_top_min': 0,
        'freq_top_avg': 0,
    })
    out = s.recommend_bands_from_frequency(freq, 15, .04)
    assert len(out) == 15
    assert np.all(np.diff(out.wavelength_um) >= .04)


@pytest.mark.parametrize('values', [[.4, .4], [.4, np.nan], [-.4, .5], [.4]])
def test_bad_wavelengths(values):
    with pytest.raises(ValueError):
        p.validate_wavelengths(values, 2)


def test_missing_metadata_and_mask_scale(tmp_path):
    path = tmp_path / 'image.tif'
    with rasterio.open(
        path, 'w', driver='GTiff', height=2, width=2, count=2,
        dtype='uint16', crs='EPSG:32634',
        transform=from_origin(0, 100, 30, 30), nodata=65535,
    ) as dst:
        dst.write(np.array([
            [[100, 65535], [200, 300]],
            [[400, 500], [600, 700]],
        ], dtype='uint16'))
        dst.scales = (.001, .001)
        dst.offsets = (0., 0.)
    with pytest.raises(ValueError):
        p.read_image(path)
    txt = tmp_path / 'wl.txt'
    np.savetxt(txt, [.8, .5])
    cube, wl, order, _ = p.read_image(path, txt)
    np.testing.assert_equal(order, [1, 0])
    assert np.isnan(cube[0, 1, 1])
    assert cube[0, 0, 1] == pytest.approx(.1)
    np.testing.assert_allclose(wl, [.5, .8])


def test_full_only_api_rejects_mask3(tmp_path):
    # A previous re-matching path must never be silently reintroduced.
    with pytest.raises(ValueError, match='FULL'):
        p.match_candidates(
            p.Matching(), np.ones((2, 20)), np.arange(20),
            ['a', 'b'], np.ones((2, 20)), ['Asphalt_1', 'Concrete_1'],
            'MASK3', tmp_path, False,
        )


def test_unknown_config(tmp_path):
    path = tmp_path / 'bad.json'
    path.write_text('{"bands":{"BAND_TYPO":3}}')
    with pytest.raises(ValueError):
        p.load_config(path)


def test_no_acceptance_thresholds_default():
    m = p.Matching()
    assert m.USE_ACCEPTANCE_THRESHOLDS is False
    assert m.CLASS_ASSIGNMENT_METRIC == 'sam'
    assert m.MATCH_RANK_METRIC == 'mbdsa'


def test_end_to_end_full_only_reproducible(tmp_path):
    """Check the actual two-output contract with bundled SYNTHETIC inputs."""
    from examples.make_synthetic import make

    source = make(tmp_path / 'input')
    cfg = p.load_config(ROOT / 'examples/synthetic_config.json')
    cfg['bands']['N_RANDOM_COMBINATIONS'] = 200
    cfg['extraction']['N_RANDOM_PROJECTIONS'] = 25
    image, source_item = p.resolve_stac(source)
    out_a = tmp_path / 'run_a'
    out_b = tmp_path / 'run_b'
    summary_a = p.run(
        image, source / 'gusl_synthetic.xlsx', out_a, cfg,
        source_item=source_item,
    )
    summary_b = p.run(
        image, source / 'gusl_synthetic.xlsx', out_b, cfg,
        source_item=source_item,
    )

    bands_a = json.loads((out_a / 'selected_bands.json').read_text())
    bands_b = json.loads((out_b / 'selected_bands.json').read_text())
    spectra_a = pd.read_excel(out_a / 'selected_endmembers.xlsx')
    spectra_b = pd.read_excel(out_b / 'selected_endmembers.xlsx')

    assert summary_a == summary_b
    assert bands_a == bands_b
    pd.testing.assert_frame_equal(spectra_a, spectra_b)
    assert summary_a['input_band_count'] == 120
    assert summary_a['endmember_selection'] == 'FULL'
    assert summary_a['mask3_reselection'] is False
    assert summary_a['band_selection_independent'] is True
    assert summary_a['unmixing_executed'] is False
    assert summary_a['scientific_accuracy_validated'] is False

    assert spectra_a.columns[0] == 'wavelength_um'
    assert len(spectra_a) == summary_a['usable_image_bands']
    assert len(spectra_a) == summary_a['endmember_spectral_bands']
    assert spectra_a.shape[1] - 1 == len(summary_a['final_endmembers'])
    assert spectra_a.columns[1:].tolist() == summary_a['final_endmembers']
    assert np.isfinite(spectra_a.to_numpy(dtype=float)).all()
    assert np.all(np.diff(spectra_a['wavelength_um']) > 0)
    assert 'vegetation' in summary_a['final_endmembers']

    band_wavelengths = np.asarray(bands_a['wavelengths_um'], dtype=float)
    selected_indices = np.asarray(
        bands_a['selected_usable_grid_indices_base0'], dtype=int
    )
    assert len(band_wavelengths) == 15
    assert len(spectra_a) > 15
    np.testing.assert_allclose(
        band_wavelengths,
        spectra_a['wavelength_um'].to_numpy()[selected_indices],
        rtol=0, atol=1e-9,
    )
    assert np.all(np.diff(band_wavelengths) >= .04 - 1e-9)
    assert bands_a['band_selection_independent'] is True
    assert bands_a['mask3_reselection'] is False
    assert 18 not in bands_a['original_band_indices_base0']

    assert not list(out_a.rglob('*.tif'))
    for obsolete in [
        'EndmembersFinales_mask3.xlsx', 'hyperspectral_mask3_COG.tif',
        'mask3_wavelengths_um.txt', 'unmixing_inputs.json',
    ]:
        assert not (out_a / obsolete).exists()
    assert not (out_a / 'diagnostics' / 'MASK3_metrics.npz').exists()
    assert (out_a / 'diagnostics' / 'FULL_class_assignments.csv').exists()
    assert (out_a / 'diagnostics' / 'band_selection.xlsx').exists()

    item = json.loads((out_a / 'item.json').read_text())
    assets = item['assets']
    assert './selected_endmembers.xlsx' in {v['href'] for v in assets.values()}
    assert './selected_bands.json' in {v['href'] for v in assets.values()}
    assert './diagnostics/candidates.csv' in {v['href'] for v in assets.values()}
    assert all(not Path(v['href']).is_absolute() for v in assets.values())
    assert item['properties']['heatwise:endmember_selection'] == 'FULL'
    assert item['properties']['heatwise:band_selection_independent'] is True

    with pytest.raises(ValueError, match='empty'):
        p.run(
            image, source / 'gusl_synthetic.xlsx', out_a, cfg,
            source_item=source_item,
        )

