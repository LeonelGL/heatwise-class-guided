import ast,copy,math,random,re,sys
from itertools import combinations
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from scipy.interpolate import PchipInterpolator
from sklearn.decomposition import PCA
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import class_guided_processor as p
ROOT=Path(__file__).resolve().parents[1]

def original(pattern):
    """Load source definitions only: never execute original Windows boot/main."""
    tree=ast.parse(next((ROOT/'reference').glob(pattern)).read_text())
    keep=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.Assign))]
    ns=dict(np=np,pd=pd,Path=Path,re=re,math=math,random=random,combinations=combinations,PchipInterpolator=PchipInterpolator,PCA=PCA)
    exec(compile(ast.Module(body=keep,type_ignores=[]),'original','exec'),ns)
    return ns

def test_material_grouping():
    names=['asphalt_road_1','asphalt_road_2','asphalt_road_3','concrete_1','concrete_2','concrete_3','metal','metal_roof','roof_dark_1','roof_light_1']
    groups=p.infer_groups(names)
    assert len(groups['asphalt_road'])==3 and len(groups['concrete'])==3
    assert 'metal_roof' in groups and 'roof_dark_1' in groups
    assert p.infer_groups(['concrete__1','concrete__2'])=={'concrete':['concrete__1','concrete__2']}

def test_excel_order_and_original_bug(tmp_path):
    path=tmp_path/'spectra.xlsx';pd.DataFrame({'wavelength_um':[.8,.4,.6],'Asphalt':[8,4,6]}).to_excel(path,index=False)
    w,x,*_=p.Matching().read_spectral_library_excel(path)
    np.testing.assert_allclose(w,[.4,.6,.8]);np.testing.assert_equal(x,[[4,6,8]])
    _,wrong,*_=original('Comparar*')['read_spectral_library_excel'](path)
    assert not np.array_equal(wrong,x)

def test_pchip_no_extrapolation_parity():
    wl=np.array([.4,.6,.8,1.]);x=np.array([[.1,np.nan,.4,.3],[.2,.3,.4,.5]])
    target=np.array([.3,.4,.5,.7,1.,1.2]);m=p.Matching()
    got=m.pchip_library_to_target_grid(wl,x,target)
    expected=original('Comparar*')['pchip_library_to_target_grid'](wl,x,target)
    np.testing.assert_equal(got,expected);assert np.isnan(got[:,[0,-1]]).all()

def test_global_finite_intersection_parity():
    scene=np.array([[.1,.2,.3,.4],[.4,.3,.2,.1]])
    lib=np.array([[np.nan,.2,.3,.5],[.1,.3,.4,.6]])
    got=p.Matching().compute_similarity_matrices(scene,lib)
    expected=original('Comparar*')['compute_similarity_matrices'](scene,lib)
    for a,b in zip(got,expected):np.testing.assert_equal(a,b)
    np.testing.assert_equal(got[2],[False,True,True,True])

def test_insufficient_overlap():
    with pytest.raises(RuntimeError):p.Matching().compute_similarity_matrices(np.ones((2,3)),np.array([[np.nan,np.nan,1]]))

@pytest.mark.parametrize('exact',[False,True])
def test_band_metrics_and_fast_combinations_parity(exact):
    old=original('select*');rng=np.random.default_rng(4);wl=np.linspace(.4,2.5,24)
    groups={k:rng.uniform(.1,.8,(3 if exact else 1,24)).astype('float32') for k in ['a','b','c']}
    selector=p.BandSelection();combos=list(combinations(range(8),4))
    expected=old['evaluate_combinations'](wl,groups,combos,exact)
    got=p.evaluate_combinations_fast(selector,wl,groups,combos,exact)
    np.testing.assert_allclose(got[['avg_sep','min_sep']],expected[['avg_sep','min_sep']],rtol=2e-6,atol=1e-7)
    a=selector.compute_single_band_scores(wl,groups,exact);b=old['compute_single_band_scores'](wl,groups,exact)
    pd.testing.assert_frame_equal(a,b)

def test_ppi_and_pruning_parity():
    old=original('Extraer*');old.update(N_RANDOM_PROJECTIONS=20,TOP_PPI_CANDIDATES_PER_STRATUM=20,N_PCA_COMPONENTS=5)
    ex=p.Extraction({k:old[k] for k in ['N_RANDOM_PROJECTIONS','TOP_PPI_CANDIDATES_PER_STRATUM','N_PCA_COMPONENTS']})
    cube=np.random.default_rng(7).uniform(.1,.8,(8,8,24)).astype('float32');valid=np.ones((8,8),bool)
    got=ex.ppi_like_candidates(cube,valid,np.random.default_rng(42));expected=old['ppi_like_candidates'](cube,valid,np.random.default_rng(42))
    for a,b in zip(got,expected):np.testing.assert_equal(a,b)
    a=ex.local_pruning(cube,valid,cube.mean(2),*got,'dark');b=old['local_pruning'](cube,valid,cube.mean(2),*expected,'dark')
    assert len(a)==len(b)
    for x,y in zip(a,b):
        for key in x:np.testing.assert_equal(x[key],y[key])

def test_matching_bundle_parity():
    old=original('Comparar*');m=p.Matching();rng=np.random.default_rng(7)
    X=rng.uniform(.1,.7,(18,30)).astype('float32');lib=X.copy()
    names=[f'CAND_{i:02d}' for i in range(18)];ln=[('Asphalt' if i<6 else 'Concrete' if i<12 else 'Metal')+f'_{i}' for i in range(18)]
    sam,mbd,_=m.compute_similarity_matrices(X,lib)
    top=m.build_top_matches_dataframe(names,ln,sam,mbd,'sam',50)
    a=m.add_acceptance_flags(m.summarize_candidates_by_target_class(top,m.TARGET_CLASS_PREFIXES))
    b=old['add_acceptance_flags'](old['summarize_candidates_by_target_class'](top,m.TARGET_CLASS_PREFIXES))
    pd.testing.assert_frame_equal(a,b)
    aa=m.select_asphalt_concrete_x3('FULL',a,names,X,X,np.arange(30));bb=old['select_asphalt_concrete_x3']('FULL',b,names,X,X,np.arange(30))
    for x,y in zip(aa,bb):pd.testing.assert_frame_equal(x,y)

def test_spacing():
    s=p.BandSelection();wl=np.linspace(.4,2.5,120);f=pd.DataFrame({'band_idx':range(120),'wavelength_um':wl,'freq_total':np.arange(120),'freq_top_min':0,'freq_top_avg':0})
    out=s.recommend_bands_from_frequency(f,15,.04)
    assert len(out)==15 and np.all(np.diff(out.wavelength_um)>=.04)

@pytest.mark.parametrize('values',[[.4,.4],[.4,np.nan],[-.4,.5],[.4]])
def test_bad_wavelengths(values):
    with pytest.raises(ValueError):p.validate_wavelengths(values,2)

def test_missing_metadata_and_mask_scale(tmp_path):
    path=tmp_path/'image.tif'
    with rasterio.open(path,'w',driver='GTiff',height=2,width=2,count=2,dtype='uint16',crs='EPSG:32634',transform=from_origin(0,100,30,30),nodata=65535) as dst:
        dst.write(np.array([[[100,65535],[200,300]],[[400,500],[600,700]]],dtype='uint16'))
        dst.scales=(.001,.001);dst.offsets=(0.,0.)
    with pytest.raises(ValueError):p.read_image(path)
    txt=tmp_path/'wl.txt';np.savetxt(txt,[.8,.5]);cube,wl,order,_=p.read_image(path,txt)
    np.testing.assert_equal(order,[1,0]);assert np.isnan(cube[0,1,1]);assert cube[0,0,1]==pytest.approx(.1)
    out=tmp_path/'out.tif';p.write_reduced_cog(path,out,order,wl)
    with rasterio.open(out) as src:
        np.testing.assert_allclose(src.read(),cube.transpose(2,0,1),equal_nan=True)
        assert src.tags(ns='IMAGE_STRUCTURE')['LAYOUT']=='COG'

def test_alignment_mismatch(tmp_path):
    image=ROOT/'examples/output/hyperspectral_mask3_COG.tif'
    if not image.exists():pytest.skip('Generate example outputs first')
    excel=ROOT/'examples/output/EndmembersFinales_mask3.xlsx';wl=pd.read_excel(excel).iloc[:,0].to_numpy()
    txt=tmp_path/'bad.txt';np.savetxt(txt,wl+.01)
    with pytest.raises(ValueError):p.assert_alignment(image,excel,txt,wl)

def test_unknown_config(tmp_path):
    f=tmp_path/'bad.json';f.write_text('{"bands":{"BAND_TYPO":3}}')
    with pytest.raises(ValueError):p.load_config(f)

def test_no_acceptance_thresholds_default():
    assert p.Matching().USE_ACCEPTANCE_THRESHOLDS is False
    assert p.Matching().CLASS_ASSIGNMENT_METRIC=='sam'
    assert p.Matching().MATCH_RANK_METRIC=='mbdsa'

def test_end_to_end_reproducible_and_physical_values(tmp_path):
    from examples.make_synthetic import make
    source=make(tmp_path/'input')
    cfg=p.load_config(ROOT/'examples/synthetic_config.json')
    cfg['bands']['N_RANDOM_COMBINATIONS']=200
    cfg['extraction']['N_RANDOM_PROJECTIONS']=25
    image,item=p.resolve_stac(source)
    a=tmp_path/'a';b=tmp_path/'b'
    ra=p.run(image,source/'gusl_synthetic.xlsx',a,cfg,source_item=item)
    rb=p.run(image,source/'gusl_synthetic.xlsx',b,cfg,source_item=item)
    import json
    sa=json.loads((a/'selected_bands.json').read_text());sb=json.loads((b/'selected_bands.json').read_text())
    assert sa==sb and ra==rb
    assert 'vegetation' in ra['final_endmembers']
    assert len(sa['wavelengths_um'])==15
    pd.testing.assert_frame_equal(pd.read_excel(a/'EndmembersFinales_mask3.xlsx'),pd.read_excel(b/'EndmembersFinales_mask3.xlsx'))
    indices=np.array(sa['original_band_indices_base0'])
    with rasterio.open(image) as src,rasterio.open(a/'hyperspectral_mask3_COG.tif') as dst:
        expected=src.read((indices+1).tolist(),masked=True).filled(np.nan)
        np.testing.assert_array_equal(dst.read(),expected)
        assert src.crs==dst.crs and src.transform==dst.transform and src.shape==dst.shape
    assert 18 not in indices # all-nodata band excluded
    actual=p.infer_groups(ra['final_endmembers'])
    assert len(actual)>=2
    with pytest.raises(ValueError,match='empty'):p.run(image,source/'gusl_synthetic.xlsx',a,cfg,source_item=item)
