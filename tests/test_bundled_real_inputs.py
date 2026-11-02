"""Integrity and accessibility checks for bundled, real HEATWISE reference inputs.

These checks DO NOT run the computationally expensive real-scene pipeline
and DO NOT execute the external ESA FCLS processor.
"""
from pathlib import Path
import subprocess

import pandas as pd
import pystac
import rasterio
import yaml

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "examples/sepolia/Sepolia_CHIME_Thermopolis_v2_COG.tif"
GUSL = ROOT / "examples/resources/GUSL_spectra_by_material_headers.xlsx"
JOB = ROOT / "examples/job_sepolia.yml"

# Exact original binary blobs restored from the project's historical
# successful Sepolia/GUSL integration commit, not synthetic substitutions.
GIT_BLOBS = {
    "examples/resources/GUSL_spectra_by_material_headers.xlsx":
        "b3fa9cd9f00d9661280bd0ec6852c17515ee961f",
    "examples/sepolia/Sepolia_CHIME_Thermopolis_v2_COG.tif":
        "4b5f833cbffd7073b749345a041c0758d3df1fd2",
}


def test_bundled_real_binary_integrity():
    for name, expected_blob in GIT_BLOBS.items():
        path = ROOT / name
        assert path.is_file(), f"Missing bundled input: {name}"
        result = subprocess.check_output(["git", "hash-object", str(path)], cwd=ROOT)
        assert result.decode("ascii").strip() == expected_blob, f"Unexpected binary: {name}"
    assert IMAGE.stat().st_size == 2596071
    assert GUSL.stat().st_size == 8330528


def test_stac_image_and_gusl_sheets():
    cat = pystac.read_file(str(ROOT / "examples/sepolia/catalog.json"))
    items = list(cat.get_all_items())
    assert len(items) == 1
    item = items[0]
    assert item.datetime is None  # exact acquisition time is unknown
    assert item.properties["start_datetime"].startswith("2009-07-18")
    assert item.properties["end_datetime"].startswith("2009-07-18")
    assert Path(item.assets["image"].get_absolute_href()).resolve() == IMAGE.resolve()
    with rasterio.open(IMAGE) as src:
        assert src.count == 250
        assert src.crs is not None
        assert src.width > 0 and src.height > 0
    with pd.ExcelFile(GUSL) as excel:
        assert {"BRUSSELS_APEX_GENLIB", "DLR"}.issubset(excel.sheet_names)


def test_real_cwl_job_resolves_bundled_paths():
    job = yaml.safe_load(JOB.read_text(encoding="utf-8"))
    assert (JOB.parent / job["input_catalog"]["path"] / "catalog.json").is_file()
    assert (JOB.parent / job["gusl"]["path"]).resolve() == GUSL.resolve()
    assert (JOB.parent / job["config"]["path"]).is_file()
    assert set(job) == {"input_catalog", "gusl", "config"}
