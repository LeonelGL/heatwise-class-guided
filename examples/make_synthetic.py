"""Deterministic test fixture only; not a real GUSL or validated urban scene."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from class_guided_processor import write_stac

def make(root, band_count=120):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    wl=np.linspace(.4,2.5,band_count);rng=np.random.default_rng(913)
    names=['Asphalt_1','Concrete_1','Metal_1','Terracotta_1','Vegetation_1']
    specs=[]
    for j in range(4):
        s=.10+.07*j+.06*np.sin(wl*(3+j*2)+j)+.04*np.exp(-((wl-(.8+.3*j))/.12)**2)
        specs.append(s)
    specs.append(.07+.4/(1+np.exp(-(wl-.72)*35))-.1*np.exp(-((wl-1.9)/.2)**2))
    specs=np.array(specs)
    cube=np.empty((band_count,40,50),np.float32)
    for r in range(40):
        for c in range(50):
            j=c//10
            cube[:,r,c]=specs[j]*(.9+.2*r/39)+.009*np.sin(wl*(2+r%8)+r*.15)+rng.normal(0,.0005,band_count)
    cube[:,0,:]=np.nan;cube[18,:,:]=np.nan;cube[45,15,15]=np.nan
    with rasterio.open(root/'scene.tif','w',driver='GTiff',height=40,width=50,count=band_count,dtype='float32',crs='EPSG:32634',transform=from_origin(730000,4210000,30,30),nodata=np.nan) as dst:
        dst.write(cube)
        for i,w in enumerate(wl,1):dst.update_tags(i,wavelength_um=str(w))
    with pd.ExcelWriter(root/'gusl_synthetic.xlsx') as writer:
        for sheet in ['BRUSSELS_APEX_GENLIB','DLR']:
            df=pd.DataFrame({'wavelength_um':wl,**{n:s for n,s in zip(names,specs)}})
            # Deliberately descending rows to exercise the reader correction.
            df.iloc[::-1].to_excel(writer,sheet_name=sheet,index=False)
    write_stac(root,root/'scene.tif',wl,'2020-07-01T10:00:00Z')
    # Input TIFF is ordinary GeoTIFF; only its STAC media type is corrected below.
    # Generate an actual COG for the input catalog as well.
    from rasterio.shutil import copy
    copy(root/'scene.tif',root/'scene_COG.tif',driver='COG')
    item=json.loads((root/'item.json').read_text());item['assets']={'image':{'href':'./scene_COG.tif','type':'image/tiff; application=geotiff; profile=cloud-optimized','roles':['data']}}
    (root/'item.json').write_text(json.dumps(item,indent=2))
    import shutil
    shutil.copy2(root/"gusl_synthetic.xlsx",root.parent/"gusl_synthetic.xlsx")
    return root
if __name__=='__main__':make(sys.argv[1] if len(sys.argv)>1 else Path(__file__).parent/'synthetic')
