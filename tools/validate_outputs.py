"""Validate HEATWISE FULL/MASK3 dual selection with complete usable spectra.

Run: python tools/validate_outputs.py results/ci/results
Requires pystac for STAC validation. Does not execute or validate FCLS accuracy.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pystac


MAIN_PRODUCTS = {
    'selected_endmembers.xlsx',  # Legacy compatibility: exactly FULL.
    'selected_endmembers_FULL.xlsx',
    'selected_endmembers_MASK3.xlsx',
    'selected_bands.json',
}


def validate(output_directory: Path):
    out = Path(output_directory).resolve()
    if not out.is_dir():
        raise ValueError(f'Output directory not found: {out}')
    for name in MAIN_PRODUCTS | {'mask3_matching_bands.json', 'run_summary.json'}:
        if not (out / name).is_file():
            raise ValueError(f'Missing output: {name}')
    obsolete = {'EndmembersFinales_mask3.xlsx', 'hyperspectral_mask3_COG.tif',
                'mask3_wavelengths_um.txt', 'unmixing_inputs.json'}
    if any((out / name).exists() for name in obsolete):
        raise ValueError('Obsolete legacy outputs were generated.')
    if list(out.rglob('*.tif')):
        raise ValueError('A new raster was generated; the image must remain unchanged.')

    report = json.loads((out / 'run_summary.json').read_text())
    bands = json.loads((out / 'selected_bands.json').read_text())
    mask_info = json.loads((out / 'mask3_matching_bands.json').read_text())
    full = pd.read_excel(out / 'selected_endmembers_FULL.xlsx', sheet_name='endmembers')
    mask3 = pd.read_excel(out / 'selected_endmembers_MASK3.xlsx', sheet_name='endmembers')
    legacy = pd.read_excel(out / 'selected_endmembers.xlsx', sheet_name='endmembers')

    for mode, df in [('FULL', full), ('MASK3', mask3)]:
        if df.columns[0] != 'wavelength_um' or df.shape[1] < 3:
            raise ValueError(f'{mode}: wavelength_um and at least 2 signatures required.')
        if not np.isfinite(df.to_numpy(dtype=float)).all():
            raise ValueError(f'{mode}: exported spectra contain NaN or infinity.')
        if not np.all(np.diff(df['wavelength_um'].to_numpy(dtype=float)) > 0):
            raise ValueError(f'{mode}: wavelengths are not strictly increasing.')
        if len(df) != report['usable_image_bands']:
            raise ValueError(f'{mode}: expected ALL {report["usable_image_bands"]} usable wavelengths.')
        if df.columns[1:].tolist() != report['endmembers_by_mode'][mode]:
            raise ValueError(f'{mode}: endmember names differ from run summary.')
    if not np.array_equal(full['wavelength_um'], mask3['wavelength_um']):
        raise ValueError('FULL and MASK3 do not preserve the same complete wavelength grid.')
    pd.testing.assert_frame_equal(full, legacy, check_exact=True)

    if report.get('status') != 'success' or report.get('endmember_selection') != 'FULL+MASK3':
        raise ValueError('run_summary.json does not document both selection modes.')
    if report.get('endmember_selection_modes') != ['FULL', 'MASK3']:
        raise ValueError('Selection modes are missing in the summary.')
    if report['final_endmembers'] != list(full.columns[1:]):
        raise ValueError('Legacy FULL endmember names are inconsistent.')
    if report.get('mask3_reselection') is not True:
        raise ValueError('MASK3 matching was not declared.')
    if report.get('mask3_selection_does_not_truncate_endmembers') is not True:
        raise ValueError('MASK3 output was not declared full-length.')
    if report.get('band_selection_independent') is not True:
        raise ValueError('Band optimization must be independent of MASK3 matching.')
    if report.get('unmixing_executed') is not False:
        raise ValueError('FCLS unexpectedly executed.')
    if not 10 <= report['full_metric_bands'] <= len(full):
        raise ValueError('Invalid FULL common-band count.')
    if report['mask3_metric_bands'] != mask_info['number_of_matching_bands']:
        raise ValueError('MASK3 matching did not use all configured diagnostic bands.')
    for mode in ('FULL', 'MASK3'):
        diag = json.loads((out / 'diagnostics' / f'{mode}_fallback_report.json').read_text())
        if diag['mode'] != mode or report['fallback_by_mode'][mode] != diag:
            raise ValueError(f'{mode}: fallback report inconsistent with summary.')
    wl = full['wavelength_um'].to_numpy(dtype=float)
    selected = np.asarray(bands['wavelengths_um'], dtype=float)
    indices = np.asarray(bands['selected_usable_grid_indices_base0'], dtype=int)
    if len(selected) != len(indices) or len(selected) != report['selected_bands']:
        raise ValueError('Invalid count of optimized bands.')
    if np.any(indices < 0) or np.any(indices >= len(wl)):
        raise ValueError('Optimized band index out of usable-grid bounds.')
    np.testing.assert_allclose(selected, wl[indices], atol=1e-9, rtol=0)
    if any(np.diff(selected) < float(bands['configuration']['MIN_SPACING_UM']) - 1e-9):
        raise ValueError('Optimized bands violate minimum spacing.')
    if bands.get('mask3_reselection') is not True:
        raise ValueError('Band metadata does not report dual selection.')
    mask3_indices = np.asarray(mask_info['matching_grid_indices_base0'], dtype=int)
    if len(mask3_indices) != len(np.unique(mask3_indices)) or len(mask3_indices) != report['mask3_metric_bands']:
        raise ValueError('Invalid or duplicate MASK3 matching indices.')
    np.testing.assert_allclose(mask_info['actual_wavelengths_um'], wl[mask3_indices], atol=1e-9, rtol=0)
    if mask_info['source'] == 'auto' and not np.array_equal(mask3_indices, indices):
        raise ValueError('Automatic MASK3 must use exactly the FULL-optimized 15 bands.')

    catalog = pystac.read_file(str(out / 'catalog.json'))
    validated = catalog.validate_all()
    items = list(catalog.get_all_items())
    if len(items) != 1:
        raise ValueError(f'Expected one STAC item, got {len(items)}.')
    item = items[0]
    if item.id != 'class-guided-full-mask3':
        raise ValueError('Unexpected STAC item identifier.')
    if item.properties.get('heatwise:endmember_selection') != ['FULL', 'MASK3']:
        raise ValueError('STAC selection modes are inconsistent.')
    if item.properties.get('heatwise:band_selection_independent') is not True:
        raise ValueError('STAC independent band selection is not declared.')
    if not MAIN_PRODUCTS.issubset(item.assets.keys()):
        raise ValueError('STAC omitted a scientific product.')
    for key, asset in item.assets.items():
        href = asset.href
        if Path(href).is_absolute() or '://' in href or '\\' in href:
            raise ValueError(f'Non-relative STAC asset: {key}')
        p = Path(asset.get_absolute_href()).resolve()
        if not p.is_relative_to(out) or not p.is_file():
            raise ValueError(f'Invalid STAC asset path: {key}')
        if key in MAIN_PRODUCTS and 'data' not in (asset.roles or []):
            raise ValueError(f'Missing scientific data role on asset: {key}')

    return {
        'status': 'success',
        'selection': 'FULL+MASK3',
        'full_endmembers': full.shape[1] - 1,
        'mask3_endmembers': mask3.shape[1] - 1,
        'complete_usable_wavelengths_both_modes': len(wl),
        'full_matching_bands': report['full_metric_bands'],
        'mask3_matching_bands': report['mask3_metric_bands'],
        'independent_selected_bands': len(selected),
        'stac_items_validated': validated,
        'stac_assets_checked': len(item.assets),
        'reduced_image_created': False,
        'fcls_executed': False,
    }


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python tools/validate_outputs.py OUTPUT_DIRECTORY')
    print(json.dumps(validate(Path(sys.argv[1])), indent=2))
