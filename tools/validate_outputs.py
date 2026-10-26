"""Validate FULL-only HEATWISE scientific output contract and stage-out STAC.

Run: python tools/validate_outputs.py results/ci/results
Does not execute FCLS or constitute validation on real Sepolia data.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pystac


def validate(output_directory: Path):
    out = Path(output_directory).resolve()
    if not out.is_dir():
        raise ValueError(f'Output directory not found: {out}')

    expected = {'selected_endmembers.xlsx', 'selected_bands.json'}
    for name in expected:
        if not (out / name).is_file():
            raise ValueError(f'Missing scientific product: {name}')

    obsolete = {
        'EndmembersFinales_mask3.xlsx', 'hyperspectral_mask3_COG.tif',
        'mask3_wavelengths_um.txt', 'unmixing_inputs.json',
    }
    if any((out / name).exists() for name in obsolete):
        raise ValueError('Obsolete MASK3/legacy outputs are present.')
    if list(out.rglob('*.tif')):
        raise ValueError('A new raster was generated; only two scientific products are allowed.')

    with (out / 'selected_bands.json').open(encoding='utf-8') as f:
        bands = json.load(f)
    with (out / 'run_summary.json').open(encoding='utf-8') as f:
        report = json.load(f)
    df = pd.read_excel(out / 'selected_endmembers.xlsx', sheet_name='endmembers')
    if df.columns[0] != 'wavelength_um' or df.shape[1] < 3:
        raise ValueError('Expected wavelength_um followed by at least two endmember columns.')
    data = df.to_numpy(dtype=float)
    if not np.isfinite(data).all():
        raise ValueError('Endmember table contains NaN/Inf values.')
    wavelengths = df['wavelength_um'].to_numpy(dtype=float)
    if len(wavelengths) < 10 or not np.all(np.diff(wavelengths) > 0):
        raise ValueError('Expected at least ten strictly increasing wavelengths.')

    if report['status'] != 'success' or report['endmember_selection'] != 'FULL':
        raise ValueError('The summary does not describe successful FULL selection.')
    if report['mask3_reselection'] is not False:
        raise ValueError('Unexpected MASK3 re-selection.')
    if report['band_selection_independent'] is not True:
        raise ValueError('Band selection is not declared independent.')
    if report['unmixing_executed'] is not False:
        raise ValueError('FCLS unexpectedly executed.')
    if df.columns[1:].tolist() != report['final_endmembers']:
        raise ValueError('Exported endmember order differs from run summary.')
    if len(wavelengths) != report['endmember_spectral_bands']:
        raise ValueError('Excel wavelength rows differ from the run summary.')
    if len(wavelengths) != report['usable_image_bands']:
        raise ValueError('FULL endmembers do not cover all reported usable bands.')
    if not 10 <= report['full_metric_bands'] <= len(wavelengths):
        raise ValueError('Invalid common-band matching count.')

    chosen = np.asarray(bands['wavelengths_um'], dtype=float)
    indices = np.asarray(bands['selected_usable_grid_indices_base0'], dtype=int)
    originals = np.asarray(bands['original_band_indices_base0'], dtype=int)
    if not (len(chosen) == len(indices) == len(originals) == report['selected_bands']):
        raise ValueError('Band-index lists and selected-band count do not agree.')
    if not np.isfinite(chosen).all() or not len(chosen):
        raise ValueError('Selected wavelengths are invalid or empty.')
    if np.any(indices < 0) or np.any(indices >= len(wavelengths)):
        raise ValueError('Selected-band index outside exported wavelength grid.')
    np.testing.assert_allclose(chosen, wavelengths[indices], rtol=0, atol=1e-9)
    if np.any(np.diff(chosen) < -1e-12):
        raise ValueError('Selected wavelengths not in ascending spectral order.')
    min_spacing = float(bands['configuration']['MIN_SPACING_UM'])
    if np.any(np.diff(chosen) < min_spacing - 1e-9):
        raise ValueError('Selected-band spacing violates configuration.')
    if bands['mask3_reselection'] is not False:
        raise ValueError('Band product wrongly describes MASK3 reselection.')
    if bands['band_selection_independent'] is not True:
        raise ValueError('Band product not declared independent.')

    catalog_path = out / 'catalog.json'
    if not catalog_path.exists():
        raise ValueError('Missing STAC catalog.json')
    catalog = pystac.read_file(str(catalog_path))
    validated_items = catalog.validate_all()
    items = list(catalog.get_all_items())
    if len(items) != 1:
        raise ValueError(f'Expected one STAC Item, found {len(items)}')
    item = items[0]
    if item.id != 'class-guided-full':
        raise ValueError('Unexpected STAC Item id.')
    if item.properties.get('heatwise:endmember_selection') != 'FULL':
        raise ValueError('STAC does not declare FULL processing.')
    if item.properties.get('heatwise:band_selection_independent') is not True:
        raise ValueError('STAC does not declare independent band selection.')
    if item.bbox is None or len(item.bbox) != 4:
        raise ValueError('Missing spatial bounding box.')
    if not (-180 <= item.bbox[0] <= item.bbox[2] <= 180):
        raise ValueError('Invalid longitude bounds.')
    if not (-90 <= item.bbox[1] <= item.bbox[3] <= 90):
        raise ValueError('Invalid latitude bounds.')

    missing_assets = expected - set(item.assets)
    if missing_assets:
        raise ValueError(f'STAC omits scientific assets: {sorted(missing_assets)}')
    asset_count = 0
    for key, asset in item.assets.items():
        href = asset.href
        if Path(href).is_absolute() or '://' in href or '\\' in href:
            raise ValueError(f'Asset not a relative local path: {key} -> {href}')
        abs_path = Path(asset.get_absolute_href()).resolve()
        if not abs_path.is_relative_to(out):
            raise ValueError(f'STAC asset escapes stage-out directory: {key}')
        if not abs_path.is_file():
            raise ValueError(f'STAC references a missing file: {abs_path}')
        if key in expected and 'data' not in (asset.roles or []):
            raise ValueError(f'Main scientific asset lacks data role: {key}')
        asset_count += 1

    return {
        'status': 'success',
        'selection': 'FULL',
        'endmembers': df.shape[1] - 1,
        'usable_endmember_bands': len(wavelengths),
        'full_matching_bands': report['full_metric_bands'],
        'independent_selected_bands': len(chosen),
        'stac_items_validated': validated_items,
        'stac_assets_checked': asset_count,
        'reduced_image_created': False,
        'fcls_executed': False,
    }


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python tools/validate_outputs.py OUTPUT_DIRECTORY')
    print(json.dumps(validate(Path(sys.argv[1])), indent=2))

