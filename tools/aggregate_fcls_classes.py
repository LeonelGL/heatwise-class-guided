#!/usr/bin/env python3
"""Aggregate official HEATWISE FCLS endmember abundances into material classes.

Standalone downstream stage. Never executes or modifies ESA-Heatwise FCLS.
Requires explicit FULL/MASK3 linkage to the class-guided endmember workbook,
its class mapping, and official FCLS provenance metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import pystac
from rasterio.shutil import copy as rio_copy
from rasterio.warp import transform_bounds

NODATA_ABUNDANCE = -9999.0
NODATA_CLASS = 0


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def validate_contract(
    endmembers_xlsx: Path,
    groups_path: Path,
    mode: str,
    class_names_json: Path,
    fcls_metadata_json: Path,
) -> tuple[list[str], list[str], list[list[int]], dict]:
    """Fail closed if workbook, FULL/MASK3 mapping and FCLS band labels disagree."""
    if mode not in {"FULL", "MASK3"}:
        raise ValueError("mode must be FULL or MASK3")
    workbook = pd.read_excel(endmembers_xlsx, sheet_name=0, nrows=0)
    if workbook.columns.size < 3 or workbook.columns[0] != "wavelength_um":
        raise ValueError("Expected wavelength_um and at least two endmember columns")
    endmember_names = [str(c) for c in workbook.columns[1:]]
    if len(set(endmember_names)) != len(endmember_names):
        raise ValueError("Duplicate endmember names in workbook")

    label_payload = read_json(class_names_json)
    label_rows = label_payload.get("classes")
    if not isinstance(label_rows, list) or not label_rows:
        raise ValueError("FCLS class_names.json must have a nonempty classes list")
    labels = [r.get("label") for r in label_rows]
    fcls_names = [r.get("name") for r in label_rows]
    if labels != list(range(1, len(label_rows) + 1)):
        raise ValueError("FCLS labels are not consecutive 1-based indices")
    if fcls_names != endmember_names:
        raise ValueError("FCLS class names/order differ from selected endmember workbook")

    metadata = read_json(fcls_metadata_json)
    inputs = metadata.get("inputs", {})
    if inputs.get("endmembers") != endmembers_xlsx.name:
        raise ValueError("FCLS metadata names a different endmember input file")
    if metadata.get("endmembers", {}).get("names") != fcls_names:
        raise ValueError("FCLS metadata endmember names/order differ from its class_names.json")

    mapping = read_json(groups_path).get("classes_by_mode", {}).get(mode)
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError(f"Class mapping lacks classes_by_mode.{mode}")
    class_names = list(mapping)
    if any(not isinstance(group, str) or not group for group in class_names):
        raise ValueError("Invalid class name in material mapping")
    flattened = [name for group in class_names for name in mapping[group]]
    if len(flattened) != len(set(flattened)) or set(flattened) != set(fcls_names):
        raise ValueError("Mapping must cover each FCLS endmember exactly once")
    indices = [[fcls_names.index(name) for name in mapping[c]] for c in class_names]
    if any(not ii for ii in indices):
        raise ValueError("Every material must have at least one endmember")
    return fcls_names, class_names, indices, metadata


def aggregate_array(
    abundance: np.ndarray,
    class_indices: list[list[int]],
    min_abundance: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Aggregate a (endmember, row, col) array; invalid FCLS pixels remain nodata."""
    if abundance.ndim != 3:
        raise ValueError("Abundance raster must have (endmember, row, col) dimensions")
    if not np.isfinite(min_abundance) or not 0 <= min_abundance <= 1:
        raise ValueError("min_abundance must lie between 0 and 1")
    valid = np.all(np.isfinite(abundance), axis=0)
    invalid_range = valid & (
        np.any(abundance < -1e-5, axis=0) | np.any(abundance > 1.00001, axis=0)
    )
    if invalid_range.any():
        raise ValueError("FCLS abundances outside [0,1] beyond numerical tolerance")
    material = np.full((len(class_indices), *abundance.shape[1:]), np.nan, dtype=np.float32)
    for i, members in enumerate(class_indices):
        material[i, valid] = np.sum(abundance[members][:, valid], axis=0)
    labels = np.zeros(abundance.shape[1:], dtype=np.uint16)
    if valid.any():
        max_aggregate = np.nanmax(material[:, valid], axis=0)
        eligible = valid.copy()
        eligible[valid] = max_aggregate >= min_abundance
        labels[eligible] = np.argmax(material[:, eligible], axis=0).astype(np.uint16) + 1
    return material, labels, valid




def abundance_from_fcls_stac(directory: Path) -> Path:
    """Stage-in FCLS EO product through catalog.json, not a guessed raster path."""
    path = Path(directory) / "catalog.json"
    if not path.is_file():
        raise ValueError("FCLS output Directory must contain catalog.json")
    root = pystac.read_file(str(path))
    items = [root] if isinstance(root, pystac.Item) else list(root.get_all_items())
    if len(items) != 1:
        raise ValueError("FCLS output STAC must contain exactly one Item")
    assets = items[0].assets
    matched = [(key, asset) for key, asset in assets.items()
               if key in {"abundance", "abundance_stack"}]
    if len(matched) != 1:
        raise ValueError("FCLS STAC needs one abundance asset")
    href = matched[0][1].get_absolute_href()
    if not href or "://" in href:
        raise ValueError("FCLS staged abundance must be a local file")
    abundance = Path(href)
    if not abundance.is_file():
        raise ValueError(f"FCLS abundance asset unavailable: {abundance}")
    if not abundance.resolve().is_relative_to(Path(directory).resolve()):
        raise ValueError("FCLS STAC abundance points outside staged directory")
    return abundance


def _parse_acquisition_datetime(value: str | None) -> datetime:
    if not value:
        raise ValueError(
            "FCLS metadata has no acquisition time; provide --acquisition-datetime "
            "as an ISO8601 timestamp with explicit timezone."
        )
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Acquisition timestamp must be ISO8601") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Acquisition time must include a timezone")
    return dt.astimezone(timezone.utc)


def _sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _write_stac(output_dir: Path, abund: Path, top1: Path, summary: Path,
                bbox: list[float], acquired: datetime, mode: str) -> None:
    left, bottom, right, top = bbox
    geom = {"type": "Polygon", "coordinates": [[
        [left, bottom], [right, bottom], [right, top],
        [left, top], [left, bottom],
    ]]}
    item = pystac.Item("heatwise-fcls-materials-" + mode.lower(), geom, bbox, acquired,
                       {"heatwise:material_aggregation": "sum_fcls_endmember_abundances",
                        "heatwise:selection_mode": mode})
    for key, path in (("material_abundances", abund), ("material_top1", top1)):
        item.add_asset(key, pystac.Asset("./" + path.name,
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            roles=["data"]))
    item.add_asset("material_classes", pystac.Asset(
        "./" + summary.name, media_type="application/json", roles=["metadata"]))
    catalog = pystac.Catalog("heatwise-material-top1",
                            "Material abundance and Top-1 stage-out after official FCLS.")
    catalog.add_item(item)
    catalog.set_self_href(str((output_dir / "catalog.json").resolve()))
    item.set_self_href(str((output_dir / "item.json").resolve()))
    catalog.make_all_asset_hrefs_relative()
    catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
    catalog.validate_all()


def _write_cog(source_tif: Path, target_cog: Path, categorical: bool) -> None:
    if target_cog.exists():
        raise FileExistsError(f"Output already exists: {target_cog}")
    rio_copy(
        source_tif, target_cog, driver="COG", COMPRESS="DEFLATE",
        BLOCKSIZE="512", BIGTIFF="IF_SAFER",
        OVERVIEW_RESAMPLING="NEAREST" if categorical else "AVERAGE",
        **({} if categorical else {"PREDICTOR": "3"}),
    )


def process(
    abundance_path: Path,
    endmembers_xlsx: Path,
    class_mapping_path: Path,
    mode: str,
    class_names_json: Path,
    fcls_metadata_json: Path,
    output_dir: Path,
    output_prefix: str,
    min_abundance: float | None = None,
    acquisition_datetime: str | None = None,
) -> dict:
    fcls_names, classes, indices, fcls_meta = validate_contract(
        endmembers_xlsx, class_mapping_path, mode, class_names_json, fcls_metadata_json,
    )
    if not output_prefix or "/" in output_prefix or "\\" in output_prefix or output_prefix in {".", ".."}:
        raise ValueError("output_prefix must be a single safe filename prefix")
    if min_abundance is None:
        min_abundance = float(fcls_meta.get("fcls", {}).get("min_abundance_for_classification", 0.0))
    if not np.isfinite(min_abundance) or not 0 <= min_abundance <= 1:
        raise ValueError("Classification threshold must be between zero and one")
    acq_dt = _parse_acquisition_datetime(acquisition_datetime or fcls_meta.get('inputs', {}).get('acquisition_datetime'))
    output_dir.mkdir(parents=True, exist_ok=True)
    abundance_cog = output_dir / f"{output_prefix}_class_abundances_COG.tif"
    top1_cog = output_dir / f"{output_prefix}_material_top1_COG.tif"
    summary_path = output_dir / f"{output_prefix}_material_classes.json"
    for path in (abundance_cog, top1_cog, summary_path, output_dir / 'catalog.json', output_dir / 'item.json'):
        if path.exists():
            raise FileExistsError(f"Output already exists: {path}")

    temp_abund = output_dir / f".{output_prefix}_class_abundances_tmp.tif"
    temp_top1 = output_dir / f".{output_prefix}_material_top1_tmp.tif"
    n_valid = 0
    n_assigned = 0
    bbox = None
    try:
        with rasterio.open(abundance_path) as src:
            if src.count != len(fcls_names):
                raise ValueError("FCLS abundance raster count disagrees with FCLS class labels")
            if src.crs is None:
                raise ValueError("FCLS raster must be georeferenced with a CRS")
            named = [src.tags(i).get("class_name") for i in range(1, src.count + 1)]
            if any(n is not None for n in named) and named != fcls_names:
                raise ValueError("FCLS raster per-band class_name tags disagree with labels")
            bbox = list(transform_bounds(src.crs, 'EPSG:4326', *src.bounds, densify_pts=21))
            profile = src.profile.copy()
            profile.update(driver="GTiff", count=len(classes), dtype="float32",
                           nodata=NODATA_ABUNDANCE, compress="deflate", predictor=3)
            label_profile = src.profile.copy()
            label_profile.update(driver="GTiff", count=1, dtype="uint16",
                                 nodata=NODATA_CLASS, compress="deflate")
            with rasterio.open(temp_abund, "w", **profile) as dst_a, rasterio.open(temp_top1, "w", **label_profile) as dst_c:
                for i, material_name in enumerate(classes, start=1):
                    dst_a.update_tags(i, class_name=material_name)
                dst_c.update_tags(class_mapping=json.dumps({str(i+1): c for i, c in enumerate(classes)}))
                for _, window in src.block_windows(1):
                    # read masked to respect the nodata sentinel written by official FCLS
                    raw = src.read(window=window, masked=True).astype("float64").filled(np.nan)
                    grouped, labels, valid = aggregate_array(raw, indices, min_abundance)
                    n_valid += int(valid.sum())
                    n_assigned += int((labels != 0).sum())
                    dst_a.write(np.nan_to_num(grouped, nan=NODATA_ABUNDANCE), window=window)
                    dst_c.write(labels, 1, window=window)
        _write_cog(temp_abund, abundance_cog, categorical=False)
        _write_cog(temp_top1, top1_cog, categorical=True)
    finally:
        temp_abund.unlink(missing_ok=True)
        temp_top1.unlink(missing_ok=True)
    summary = {
        "selection_mode": mode,
        "acquisition_datetime": acq_dt.isoformat(),
        "source_abundance_stack": str(abundance_path),
        "source_fcls_metadata": str(fcls_metadata_json),
        "input_sha256": {
            "fcls_abundance_stack": _sha256(abundance_path),
            "endmember_workbook": _sha256(endmembers_xlsx),
            "class_mapping": _sha256(class_mapping_path),
            "fcls_metadata": _sha256(fcls_metadata_json),
            "fcls_class_names": _sha256(class_names_json),
        },
        "selected_endmembers": str(endmembers_xlsx),
        "class_mapping_source": str(class_mapping_path),
        "endmember_names": fcls_names,
        "classes": [{"label": i + 1, "name": cls, "endmembers": [fcls_names[j] for j in indices[i]]}
                    for i, cls in enumerate(classes)],
        "min_aggregated_abundance_for_classification": min_abundance,
        "valid_fcls_pixels": n_valid,
        "classified_pixels": n_assigned,
        "outputs": {"class_abundances": abundance_cog.name, "material_top1": top1_cog.name},
        "limitations": [
            "The FCLS processor does not record an endmember workbook content hash."
            " Matching names and input basename cannot prove identical spectral values.",
            "A material Top-1 differs from endmember Top-1; validation must be repeated.",
        ],
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_stac(output_dir, abundance_cog, top1_cog, summary_path, bbox, acq_dt, mode)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--abundances", type=Path, help="ESA FCLS *_abundance_stack_COG.tif (local direct CLI)")
    src_group.add_argument("--fcls-output-dir", type=Path, help="Staged official FCLS Directory containing catalog.json")
    parser.add_argument("--selected-endmembers", type=Path, required=True, help="Exactly the XLSX used by official FCLS")
    parser.add_argument("--class-mapping", type=Path, required=True, help="class-guided diagnostics/endmember_classes.json")
    parser.add_argument("--mode", required=True, choices=("FULL", "MASK3"))
    parser.add_argument("--fcls-class-names", type=Path, required=True)
    parser.add_argument("--fcls-metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-prefix", default="HEATWISE_FCLS")
    parser.add_argument("--acquisition-datetime", default=None,
                        help="Real scene acquisition ISO8601 time with explicit timezone")
    parser.add_argument("--min-abundance", type=float, default=None,
                        help="Override official FCLS threshold for aggregated-class Top-1")
    args = parser.parse_args()
    abundances = abundance_from_fcls_stac(args.fcls_output_dir) if args.fcls_output_dir else args.abundances
    print(json.dumps(process(
        abundances, args.selected_endmembers, args.class_mapping, args.mode,
        args.fcls_class_names, args.fcls_metadata, args.output_dir,
        args.output_prefix, args.min_abundance, args.acquisition_datetime,
    ), indent=2))


if __name__ == "__main__":
    main()
