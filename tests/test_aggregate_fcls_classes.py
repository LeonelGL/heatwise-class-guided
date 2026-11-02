"""Synthetic contract and GeoTIFF regression tests for FCLS material aggregation."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

SPEC = importlib.util.spec_from_file_location(
    "aggregate_fcls_classes", Path(__file__).resolve().parents[1] / "tools" / "aggregate_fcls_classes.py"
)
assert SPEC and SPEC.loader
ag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ag)


@pytest.fixture
def fixture(tmp_path):
    names = ["asphalt_road_1", "asphalt_road_2", "asphalt_road_3",
             "concrete_1", "concrete_2", "concrete_3", "metal", "terracota", "vegetation"]
    xlsx = tmp_path / "selected_endmembers_FULL.xlsx"
    pd.DataFrame({"wavelength_um": [.5, .6], **{n: [.1, .2] for n in names}}).to_excel(xlsx, index=False)
    groups = {"asphalt_road": names[:3], "concrete": names[3:6],
              "metal": [names[6]], "terracota": [names[7]], "vegetation": [names[8]]}
    mapping = tmp_path / "endmember_classes.json"
    mapping.write_text(json.dumps({"classes_by_mode": {"FULL": groups}}))
    classnames = tmp_path / "class_names.json"
    classnames.write_text(json.dumps({"classes": [
        {"label": i+1, "name": n} for i, n in enumerate(names)]}))
    meta = tmp_path / "run_metadata.json"
    meta.write_text(json.dumps({"inputs": {"endmembers": xlsx.name, "acquisition_datetime": "2020-07-01T10:00:00Z"},
                                "endmembers": {"names": names},
                                "fcls": {"min_abundance_for_classification": 0.0}}))
    tif = tmp_path / "abundance_stack_COG.tif"
    cube = np.zeros((9, 1, 3), dtype="float32")
    cube[:, 0, 0] = [.25, .20, .15, .40, 0, 0, 0, 0, 0]
    cube[:, 0, 1] = [.08, .08, .04, .10, .10, .10, .50, 0, 0]
    cube[:, 0, 2] = -9999
    with rasterio.open(tif, "w", driver="GTiff", count=9, width=3, height=1,
                       dtype="float32", nodata=-9999, crs="EPSG:32634",
                       transform=from_origin(0, 1, 30, 30)) as dst:
        dst.write(cube)
        for i, n in enumerate(names, 1):
            dst.update_tags(i, class_name=n)
    return xlsx, mapping, classnames, meta, tif


def test_aggregation_selects_material_not_signature(fixture, tmp_path):
    xlsx, mapping, classes, meta, tif = fixture
    summary = ag.process(tif, xlsx, mapping, "FULL", classes, meta, tmp_path / "out", "test")
    assert summary["valid_fcls_pixels"] == 2
    assert summary["classified_pixels"] == 2
    out = tmp_path / "out"
    with rasterio.open(out / "test_material_top1_COG.tif") as dst:
        assert dst.count == 1
        assert dst.crs.to_epsg() == 32634
        np.testing.assert_array_equal(dst.read(1), [[1, 3, 0]])
    with rasterio.open(out / "test_class_abundances_COG.tif") as dst:
        assert dst.count == 5
        assert dst.read(masked=True).mask[:, 0, 2].all()
        np.testing.assert_allclose(dst.read()[:2, 0, 0], [.60, .40], rtol=0, atol=1e-6)
    summary_file = out / "test_material_classes.json"
    assert summary_file.exists()
    data = json.loads(summary_file.read_text())
    assert len(data["input_sha256"]["endmember_workbook"]) == 64
    import pystac
    cat = pystac.read_file(str(out / "catalog.json"))
    assert len(list(cat.get_all_items())) == 1
    assert cat.validate_all() >= 1
    item = next(cat.get_all_items())
    assert item.geometry["type"] == "Polygon"
    assert item.bbox is not None
    assert set(item.assets) == {"material_abundances", "material_top1", "material_classes"}
    for asset in item.assets.values():
        assert Path(asset.get_absolute_href()).is_file()


def test_rejects_wrong_endmember_order(fixture):
    xlsx, mapping, classes, meta, _ = fixture
    payload = json.loads(classes.read_text())
    payload["classes"][0]["name"] = "wrong"
    classes.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="class names/order"):
        ag.validate_contract(xlsx, mapping, "FULL", classes, meta)


def test_rejects_wrong_fcls_input(fixture):
    xlsx, mapping, classes, meta, _ = fixture
    payload = json.loads(meta.read_text())
    payload["inputs"]["endmembers"] = "old_library.xlsx"
    meta.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="different endmember input"):
        ag.validate_contract(xlsx, mapping, "FULL", classes, meta)


def test_rejects_missing_group_and_wrong_mode(fixture):
    xlsx, mapping, classes, meta, _ = fixture
    with pytest.raises(ValueError, match="MASK3"):
        ag.validate_contract(xlsx, mapping, "MASK3", classes, meta)
    payload = json.loads(mapping.read_text())
    del payload["classes_by_mode"]["FULL"]["vegetation"]
    mapping.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="exactly once"):
        ag.validate_contract(xlsx, mapping, "FULL", classes, meta)


def test_threshold_applies_to_summed_class():
    a = np.zeros((3, 1, 2), dtype=float)
    a[:, 0, 0] = [0.3, 0.3, 0.4]
    a[:, 0, 1] = [0.1, 0.1, 0.8]
    grouped, labels, valid = ag.aggregate_array(a, [[0, 1], [2]], min_abundance=0.5)
    np.testing.assert_array_equal(labels, [[1, 2]])
    np.testing.assert_array_equal(valid, [[True, True]])
    np.testing.assert_allclose(grouped[:, 0, 0], [0.6, 0.4])


def test_invalid_data_not_classified():
    a = np.array([[[np.nan, 0.6]], [[0.4, 0.4]]])
    out, labels, valid = ag.aggregate_array(a, [[0], [1]])
    assert not valid[0, 0] and labels[0, 0] == 0
    assert np.isnan(out[:, 0, 0]).all()


def test_requires_real_acquisition_time(fixture):
    xlsx, mapping, classes, meta, tif = fixture
    payload = json.loads(meta.read_text())
    del payload["inputs"]["acquisition_datetime"]
    meta.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="acquisition time"):
        ag.process(tif, xlsx, mapping, "FULL", classes, meta, tif.parent / "no_time", "test")


def test_invalid_naive_time_rejected():
    with pytest.raises(ValueError, match="timezone"):
        ag._parse_acquisition_datetime("2009-07-18T12:00:00")
