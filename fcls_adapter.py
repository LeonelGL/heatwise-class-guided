#!/usr/bin/env python3
"""Use the unchanged upstream FCLS and I/O; repair catalog metadata externally."""
import argparse,importlib.util,sys,shutil,json
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio

def main():
    p=argparse.ArgumentParser();p.add_argument('--prepared',required=True,type=Path);p.add_argument('--upstream',required=True,type=Path);p.add_argument('--output-dir',required=True,type=Path)
    a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
    if any(a.output_dir.iterdir()):raise ValueError('Output must be empty.')
    sys.path.insert(0,str(a.upstream/'src'))
    spec=importlib.util.spec_from_file_location('upstream_processor',a.upstream/'processor.py');up=importlib.util.module_from_spec(spec);spec.loader.exec_module(up)
    src=a.prepared;out=a.output_dir
    wl,E,names=up.read_endmembers(src/'EndmembersFinales_mask3.xlsx')
    cube,wi,info=up.read_input_raster(src/'hyperspectral_mask3_COG.tif',src/'mask3_wavelengths_um.txt',None,1.0)
    if not np.allclose(wl,wi,atol=1e-12,rtol=0) or E.shape[0]!=cube.shape[0]:raise ValueError('FCLS input alignment failed.')
    Y,valid=up.cube_to_matrix(cube)
    result=up.compute_fcls_abundances(Y,E,maxiter=200,ftol=1e-8,log_every=None)
    H,W=cube.shape[1:];ab=up.abundance_matrix_to_cube(result.abundances,valid,H,W)
    labels=up.labels_to_map(up.abundances_to_class_map(result.abundances),valid,H,W)
    up.write_float_cog(out/'abundances_COG.tif',ab,info['profile'],names)
    up.write_classification_cog(out/'classification_COG.tif',labels,info['profile'],names)
    # Material sums are additional outputs; never alter upstream bundle-level classification.
    groups=json.loads((src/'endmember_classes.json').read_text())['classes']
    material=np.stack([np.sum(ab[[names.index(n) for n in members]],axis=0) for members in groups.values()])
    up.write_float_cog(out/'material_abundances_COG.tif',material,info['profile'],list(groups))
    material_labels=np.zeros((H,W),np.uint16);material_labels.flat[np.flatnonzero(valid)]=np.argmax(material.reshape(len(groups),-1)[:,valid],axis=0)+1
    up.write_classification_cog(out/'material_classification_COG.tif',material_labels,info['profile'],list(groups))
    for path in src.iterdir():
        if path.is_dir():shutil.copytree(path,out/path.name)
        if path.is_file() and path.name not in ('catalog.json','item.json'):shutil.copy2(path,out/path.name)
    item=json.loads((src/'item.json').read_text());item['id']='class-guided-fcls'
    for key,bands in [('abundances',names),('material_abundances',list(groups)),('classification',['endmember_label']),('material_classification',['material_label'])]:
        item['assets'][key]={'href':f'./{key}_COG.tif','type':'image/tiff; application=geotiff; profile=cloud-optimized','roles':['data'],'bands':[{'name':n} for n in bands]}
    item['links']=[{'rel':'root','href':'./catalog.json','type':'application/json'},{'rel':'parent','href':'./catalog.json','type':'application/json'}]
    (out/'item.json').write_text(json.dumps(item,indent=2))
    catalog=json.loads((src/'catalog.json').read_text());catalog['links']=[{'rel':'root','href':'./catalog.json','type':'application/json'},{'rel':'item','href':'./item.json','type':'application/json'}]
    (out/'catalog.json').write_text(json.dumps(catalog,indent=2))
    report={'upstream_commit':'c97ae3d3c0d8140069733750f448521b30b920ed','fcls_success_rate':result.success_rate,'failed_pixels':result.failed_pixels,'valid_pixels':int(valid.sum()),'endmember_labels':{i+1:n for i,n in enumerate(names)},'material_labels':{i+1:n for i,n in enumerate(groups)}}
    (out/'fcls_run.json').write_text(json.dumps(report,indent=2))
    item['assets']['fcls_run']={'href':'./fcls_run.json','type':'application/json','roles':['metadata']}
    (out/'item.json').write_text(json.dumps(item,indent=2))
if __name__=='__main__':main()
