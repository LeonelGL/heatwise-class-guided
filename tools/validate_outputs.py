"""Validate generated raster alignment, COG structure, STAC links."""
import sys,json
from pathlib import Path
import numpy as np,pandas as pd,rasterio,pystac
from rio_cogeo.cogeo import cog_validate
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from class_guided_processor import assert_alignment
out=Path(sys.argv[1]);checks={}
wl=np.loadtxt(out/'mask3_wavelengths_um.txt')
checks['spectral_alignment']=assert_alignment(out/'hyperspectral_mask3_COG.tif',out/'EndmembersFinales_mask3.xlsx',out/'mask3_wavelengths_um.txt',wl)
checks['cog']={}
for path in out.glob('*.tif'):
 ok,errors,warnings=cog_validate(path,strict=True);assert ok,(path,errors,warnings)
 checks['cog'][path.name]={'valid':ok,'errors':errors,'warnings':warnings}
cat=pystac.read_file(str((out/'catalog.json').resolve()))
checks['stac_schema_validated_items']=cat.validate_all()
assets=0
for item in cat.get_all_items():
 assert all(-180<=x<=180 for x in item.bbox[::2]) and all(-90<=x<=90 for x in item.bbox[1::2])
 for asset in item.assets.values():
  assert Path(asset.get_absolute_href()).exists(),asset.href
  assert not Path(asset.href).is_absolute(),asset.href
  assets+=1
checks['stac_assets_existing_and_relative']=assets
print(json.dumps(checks,indent=2))
