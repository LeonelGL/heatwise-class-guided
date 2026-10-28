"""Scene-independent FULL class fallback: no material or city hard-coded."""
import numpy as np
import pandas as pd
import pytest

import class_guided_processor as p


def _fixture():
    # Existing asphalt is protected; two other classes lack normal endmembers.
    # Class alpha's lowest SAM is candidate C1; class beta has only C1 under
    # its threshold, so the global one-to-one assignment must reserve C1 for
    # beta and use C2 for alpha.
    m = p.Matching({
        'FINAL_TARGET_CLASSES': ['asphalt_road', 'alpha', 'beta'],
        'TARGET_CLASS_PREFIXES': {
            'asphalt_road': ['Asphalt'],
            'alpha': ['Alpha'],
            'beta': ['Beta'],
        },
        'FALLBACK_ENABLED': True,
        'FALLBACK_MAX_SAM_DEG': 8.0,
        'FALLBACK_MAX_SAM_BY_CLASS': {'beta': 5.0},
    })
    names = ['C0', 'C1', 'C2', 'C3']
    lib = ['Asphalt_1', 'Alpha_1', 'Beta_1']
    X = np.array([
        np.linspace(0.12, 0.2, 16),
        np.linspace(0.31, 0.4, 16),
        np.linspace(0.25, 0.34, 16),
        np.linspace(0.42, 0.55, 16),
    ])
    sam = np.array([
        [1., 7., 7.],
        [2., 4., 4.5],
        [2.4, 5., 6.],
        [1.5, 10., 11.],
    ])
    mbd = sam / 20
    summary = pd.DataFrame({
        'candidate': names,
        'best_target_class': ['asphalt_road'] * len(names),
        'accepted_by_thresholds': [True] * len(names),
    })
    return m, X, names, lib, sam, mbd, summary


def _run(m, X, names, lib, sam, mbd, summary, reserved=frozenset({'C0'})):
    return p.select_missing_class_fallbacks(
        m, X, names, lib, sam, mbd, summary,
        selected_classes={'asphalt_road'},
        reserved_candidates=set(reserved),
    )


def test_general_multi_class_fallback_uniqueness_and_optimality():
    m, X, names, lib, sam, mbd, summary = _fixture()
    chosen, report = _run(m, X, names, lib, sam, mbd, summary)
    assert set(chosen) == {'alpha', 'beta'}
    assert names[chosen['alpha']['scene_index']] == 'C2'
    assert names[chosen['beta']['scene_index']] == 'C1'
    assert all(x['quality_flag'].startswith('PROVISIONAL') for x in report['selected'])
    assert len(report['unresolved']) == 0
    assert all(x['max_accepted_sam_deg'] <= 8 for x in report['selected'])
    assert report['mode'] == 'FULL'


def test_generic_threshold_and_unresolved_reports():
    m, X, names, lib, sam, mbd, summary = _fixture()
    m.FALLBACK_MAX_SAM_BY_CLASS = {'alpha': 3., 'beta': 4.}
    chosen, report = _run(m, X, names, lib, sam, mbd, summary)
    assert chosen == {}
    assert {x['class_name'] for x in report['unresolved']} == {'alpha', 'beta'}
    assert all(x['reason'] == 'SAM_ABOVE_CEILING_OR_NO_FINITE_MATCH' for x in report['unresolved'])


def test_disabled_fallback_has_no_assignments():
    m, X, names, lib, sam, mbd, summary = _fixture()
    m.FALLBACK_ENABLED = False
    chosen, report = _run(m, X, names, lib, sam, mbd, summary)
    assert chosen == {}
    assert len(report['unresolved']) == 2
    assert all(x['reason'] == 'FALLBACK_DISABLED' for x in report['unresolved'])


def test_class_with_no_gusl_templates_is_unresolved():
    m, X, names, lib, sam, mbd, summary = _fixture()
    m.TARGET_CLASS_PREFIXES['beta'] = ['Absent']
    chosen, report = _run(m, X, names, lib, sam, mbd, summary)
    assert 'alpha' in chosen
    assert {'class_name': 'beta', 'reason': 'NO_GUSL_SIGNATURES_FOR_CLASS'} in report['unresolved']


def test_no_available_candidates_does_not_reuse_primary_endmembers():
    m, X, names, lib, sam, mbd, summary = _fixture()
    chosen, report = _run(m, X, names, lib, sam, mbd, summary, reserved=names)
    assert chosen == {}
    assert len(report['unresolved']) == 2
    assert all(x['reason'] == 'NO_UNRESERVED_SCENE_CANDIDATES' for x in report['unresolved'])


def test_per_class_configuration_must_be_valid():
    m, X, names, lib, sam, mbd, summary = _fixture()
    m.FALLBACK_MAX_SAM_BY_CLASS = {'unknown_material': 4.0}
    with pytest.raises(ValueError, match='Unknown fallback threshold'):
        _run(m, X, names, lib, sam, mbd, summary)
    m.FALLBACK_MAX_SAM_BY_CLASS = {'alpha': -2.}
    with pytest.raises(ValueError, match='Invalid fallback SAM ceiling'):
        _run(m, X, names, lib, sam, mbd, summary)


def test_no_missing_classes_means_no_fallback():
    m, X, names, lib, sam, mbd, summary = _fixture()
    chosen, report = p.select_missing_class_fallbacks(
        m, X, names, lib, sam, mbd, summary,
        selected_classes=set(m.FINAL_TARGET_CLASSES), reserved_candidates=set(),
    )
    assert chosen == {}
    assert report['missing_classes_before_fallback'] == []
    assert report['unresolved'] == []
