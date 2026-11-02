#!/usr/bin/env python3
"""Independent structural/STAC validation for post-FCLS material-map outputs.

Does not run FCLS or validate the scientific accuracy of material assignment.
Usage: python tools/validate_material_outputs.py OUTPUT_DIR [PREFIX]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pystac
import rasterio


def validate(folder: Path, prefix: str = "synthetic") -> dict:
    folder = Path(folder).resolve()
    summary_file = folder / f"{prefix}_material_classes.json"
    if not summary_file.is_file():
        raise ValueError(f"Missing metadata: {summary_file}")
    meta = json.loads(summary_file.read_text(encoding="utf-8"))
    classes = meta.get("classes", [])
    if not classes or any(c["label"] != i + 1 for i, c in enumerate(classes)):
        raise ValueError("Invalid numeric class labels")
    for c in classes:
        if not c["name"] or not c["endmembers"]:
            raise ValueError("Class labels and memberships must not be empty")
    sources = meta.get("input_sha256", {})
    if set(sources) != {"fcls_abundance_stack", "endmember_workbook",
                        "class_mapping", "fcls_metadata", "fcls_class_names"}:
        raise ValueError("Missing FCLS provenance source hashes")
    if any(len(s) != 64 for s in sources.values()):
        raise ValueError("Invalid provenance digest")
    products = meta.get("outputs", {})
    abund_path = folder / products["class_abundances"]
    top1_path = folder / products["material_top1"]
    if not abund_path.is_file() or not top1_path.is_file():
        raise ValueError("Missing material GeoTIFF products")
    with rasterio.open(abund_path) as a, rasterio.open(top1_path) as c:
        if a.count != len(classes) or c.count != 1:
            raise ValueError("Incorrect number of material bands")
        if a.transform != c.transform or a.crs != c.crs or a.shape != c.shape:
            raise ValueError("Output products do not share georeferencing")
        if a.crs is None or a.nodata is None or c.nodata != 0:
            raise ValueError("Missing CRS or nodata")
        if any(a.tags(i + 1).get("class_name") != row["name"]
               for i, row in enumerate(classes)):
            raise ValueError("Abundance GeoTIFF bands missing material names")
        abundance = a.read(masked=True)
        labels = c.read(1)
        valid = ~np.any(np.ma.getmaskarray(abundance), axis=0)
        if not np.array_equal(valid, labels != 0) and meta["min_aggregated_abundance_for_classification"] == 0.0:
            raise ValueError("Classification nodata mask differs from abundances")
        if np.any(labels > len(classes)):
            raise ValueError("Top-1 label exceeds class count")
        if valid.any():
            data = np.ma.getdata(abundance)
            sums = np.sum(data[:, valid], axis=0)
            if not np.allclose(sums, 1.0, atol=2e-2):
                raise ValueError("Material abundances fail approximate sum-to-one")
            argmax = np.argmax(data[:, valid], axis=0) + 1
            classified = labels[valid] != 0
            if np.any(labels[valid][classified] != argmax[classified]):
                raise ValueError("Top-1 differs from grouped abundance argmax")
        assert meta["valid_fcls_pixels"] == int(valid.sum())
        assert meta["classified_pixels"] == int((labels != 0).sum())
    catalog = pystac.read_file(str(folder / "catalog.json"))
    catalog.validate_all()
    items = list(catalog.get_all_items())
    if len(items) != 1 or not items[0].geometry or not items[0].bbox:
        raise ValueError("Missing STAC Item footprint")
    assets = items[0].assets
    if set(assets) != {"material_abundances", "material_top1", "material_classes"}:
        raise ValueError("Unexpected STAC material assets")
    if any(not Path(asset.get_absolute_href()).is_file() for asset in assets.values()):
        raise ValueError("Broken STAC asset references")
    return {"status": "success", "classes": len(classes),
            "valid_pixels": meta["valid_fcls_pixels"],
            "classified_pixels": meta["classified_pixels"],
            "stac_assets": len(assets)}


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("Usage: python tools/validate_material_outputs.py OUTPUT_DIR [PREFIX]")
    print(json.dumps(validate(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) == 3 else "synthetic"), indent=2))
