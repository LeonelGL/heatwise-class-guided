"""Deterministic synthetic fixture for HEATWISE, not real GUSL/Sepolia data.

Generates a standalone single-Item STAC input catalog. Do NOT call the output
catalog writer: in v0.3.0 that writer requires the two scientific products.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pystac
import rasterio
from rasterio.shutil import copy as raster_copy
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds


def make(root, band_count=120):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    wavelengths = np.linspace(.4, 2.5, band_count)
    rng = np.random.default_rng(913)
    names = ['Asphalt_1', 'Concrete_1', 'Metal_1', 'Terracotta_1', 'Vegetation_1']
    signatures = []
    for j in range(4):
        spec = (
            .10 + .07 * j + .06 * np.sin(wavelengths * (3 + j * 2) + j)
            + .04 * np.exp(-((wavelengths - (.8 + .3 * j)) / .12) ** 2)
        )
        signatures.append(spec)
    signatures.append(
        .07 + .4 / (1 + np.exp(-(wavelengths - .72) * 35))
        - .1 * np.exp(-((wavelengths - 1.9) / .2) ** 2)
    )
    signatures = np.asarray(signatures)
    cube = np.empty((band_count, 40, 50), np.float32)
    for row in range(40):
        for col in range(50):
            cls = col // 10
            cube[:, row, col] = (
                signatures[cls] * (.9 + .2 * row / 39)
                + .009 * np.sin(wavelengths * (2 + row % 8) + row * .15)
                + rng.normal(0, .0005, band_count)
            )
    cube[:, 0, :] = np.nan
    cube[18, :, :] = np.nan
    cube[45, 15, 15] = np.nan

    image = root / 'scene.tif'
    with rasterio.open(
        image, 'w', driver='GTiff', height=40, width=50,
        count=band_count, dtype='float32', crs='EPSG:32634',
        transform=from_origin(730000, 4210000, 30, 30), nodata=np.nan,
    ) as dst:
        dst.write(cube)
        for i, wl in enumerate(wavelengths, 1):
            dst.update_tags(i, wavelength_um=str(wl))

    # A COG is the EOAP staged raster input.
    cloud_optimized_image = root / 'scene_COG.tif'
    raster_copy(image, cloud_optimized_image, driver='COG')

    with pd.ExcelWriter(root / 'gusl_synthetic.xlsx') as writer:
        for sheet in ['BRUSSELS_APEX_GENLIB', 'DLR']:
            frame = pd.DataFrame({
                'wavelength_um': wavelengths,
                **{name: value for name, value in zip(names, signatures)},
            })
            frame.iloc[::-1].to_excel(writer, sheet_name=sheet, index=False)

    with rasterio.open(cloud_optimized_image) as src:
        bbox = [float(v) for v in transform_bounds(
            src.crs, 'EPSG:4326', *src.bounds, densify_pts=21
        )]
    left, bottom, right, top = bbox
    geometry = {
        'type': 'Polygon',
        'coordinates': [[
            [left, bottom], [right, bottom], [right, top],
            [left, top], [left, bottom],
        ]],
    }
    item = pystac.Item(
        id='synthetic-scene', geometry=geometry, bbox=bbox,
        datetime=datetime(2020, 7, 1, 10, 0, tzinfo=timezone.utc),
        properties={},
    )
    item.add_asset(
        'image', pystac.Asset(
            href='./scene_COG.tif', media_type=pystac.MediaType.COG,
            roles=['data'],
        )
    )
    catalog = pystac.Catalog('heatwise-synthetic-input', 'Synthetic STAC input.')
    catalog.add_item(item)
    catalog.set_self_href(str(root / 'catalog.json'))
    item.set_self_href(str(root / 'item.json'))
    catalog.make_all_asset_hrefs_relative()
    catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)

    # Matches the legacy test fixture's path expectations.
    shutil.copy2(root / 'gusl_synthetic.xlsx', root.parent / 'gusl_synthetic.xlsx')
    return root


if __name__ == '__main__':
    make(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / 'synthetic')
