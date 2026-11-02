#!/usr/bin/env python3
"""Generate synthetic official-FCLS-shaped STAC outputs (NO FCLS is executed).

Used only for integration tests of the independently packaged material mapper.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pystac
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds


def main(output: Path) -> None:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fcls = output / "fcls"
    fcls.mkdir(exist_ok=True)
    names = [
        "asphalt_road_1", "asphalt_road_2", "asphalt_road_3",
        "concrete_1", "concrete_2", "concrete_3",
        "metal", "terracota", "vegetation",
    ]
    selected = output / "selected_endmembers_FULL.xlsx"
    pd.DataFrame({"wavelength_um": [0.50, 0.60, 0.70],
                  **{n: [0.2, 0.3, 0.4] for n in names}}).to_excel(selected, index=False)
    mapping = output / "endmember_classes.json"
    groups = {
        "asphalt_road": names[:3], "concrete": names[3:6],
        "metal": [names[6]], "terracota": [names[7]], "vegetation": [names[8]],
    }
    mapping.write_text(json.dumps({"classes_by_mode": {"FULL": groups, "MASK3": groups}}))
    classes = output / "class_names.json"
    classes.write_text(json.dumps({
        "nodata": 0, "classes": [{"label": i + 1, "name": n} for i, n in enumerate(names)]
    }))
    meta = output / "run_metadata.json"
    meta.write_text(json.dumps({
        "inputs": {"endmembers": selected.name},
        "endmembers": {"count": 9, "names": names},
        "fcls": {"min_abundance_for_classification": 0.0},
        "outputs": {"abundance_stack": "synthetic_abundance_stack_COG.tif",
                    "class_names": classes.name, "run_metadata": meta.name},
    }))
    stack = fcls / "synthetic_abundance_stack_COG.tif"
    arr = np.zeros((9, 2, 3), dtype="float32")
    arr[:, 0, 0] = [0.25, 0.20, 0.15, 0.40, 0, 0, 0, 0, 0]
    arr[:, 0, 1] = [0.08, 0.08, 0.04, 0.10, 0.10, 0.10, 0.50, 0, 0]
    arr[:, 0, 2] = -9999.0
    arr[:, 1, 0] = [0, 0, 0, 0, 0, 0, 0, 0, 1]
    arr[:, 1, 1] = [0.06, 0.06, 0.08, 0.40, 0.40, 0, 0, 0, 0]
    arr[:, 1, 2] = [0.10, 0, 0, 0, 0, 0, 0.20, 0.30, 0.40]
    transform = from_origin(700000, 4200000, 30, 30)
    with rasterio.open(stack, "w", driver="GTiff", width=3, height=2,
                       count=9, dtype="float32", nodata=-9999,
                       crs="EPSG:32634", transform=transform) as dst:
        dst.write(arr)
        for i, name in enumerate(names, start=1):
            dst.update_tags(i, class_name=name)

    bbox = list(transform_bounds("EPSG:32634", "EPSG:4326",
                                 *rasterio.open(stack).bounds, densify_pts=21))
    left, bottom, right, top = bbox
    geo = {"type": "Polygon", "coordinates": [[
        [left, bottom], [right, bottom], [right, top],
        [left, top], [left, bottom],
    ]]}
    item = pystac.Item("synthetic-fcls-output", geo, bbox,
                       datetime(2020, 7, 1, 10, tzinfo=timezone.utc), {})
    item.add_asset("abundance", pystac.Asset("./" + stack.name,
                                             media_type="image/tiff; application=geotiff"))
    catalog = pystac.Catalog("synthetic-fcls", "Fake FCLS assets for postprocess packaging tests")
    catalog.add_item(item)
    catalog.set_self_href(str(fcls / "catalog.json"))
    item.set_self_href(str(fcls / "item.json"))
    catalog.make_all_asset_hrefs_relative()
    catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
    job = {
        "fcls_outputs": {"class": "Directory", "path": "fcls"},
        "selected_endmembers": {"class": "File", "path": selected.name},
        "class_mapping": {"class": "File", "path": mapping.name},
        "mode": "FULL",
        "fcls_class_names": {"class": "File", "path": classes.name},
        "fcls_metadata": {"class": "File", "path": meta.name},
        "acquisition_datetime": "2020-07-01T10:00:00Z",
        "output_prefix": "synthetic",
    }
    (output / "job_material_synthetic.yml").write_text(json.dumps(job, indent=2) + "\n")
    print(f"Wrote synthetic external-FCLS-shaped fixture and CWL job: {output}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/material-fixture"))
