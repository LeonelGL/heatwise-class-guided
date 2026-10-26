#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Extractor de candidatos a endmembers urbanos para Sepolia (CHIME-like)

Qué cambia respecto de la versión anterior:
- mantiene el manejo robusto de GDAL / PROJ para Windows/Conda
- respeta el gap espectral real de Thermopolis / Sepolia
- construye una máscara URBANA previa usando NDVI
- excluye vegetación antes de seleccionar candidatos
- estratifica el dominio urbano en dark / mid / bright según brillo
- ejecuta la selección PPI-like por estrato
- hace pruning local por estrato
- deduplica primero por estrato y luego globalmente
- guarda mapas auxiliares: urban_mask y urban_strata_map

Salida principal:
- Sepolia_urban_scene_candidates.xlsx
- Sepolia_urban_scene_candidates_metadata.csv
- Sepolia_urban_scene_candidates_RGB.png
- Sepolia_urban_scene_candidates_spectra.png
- Sepolia_urban_mask.png
- Sepolia_urban_strata_map.png
- Sepolia_urban_scene_candidates.npz
"""

import os
import sys
import re
import traceback
import warnings
import ctypes
import faulthandler
from pathlib import Path

faulthandler.enable()
warnings.filterwarnings("ignore")

print("[BOOT] Iniciando script...")

# ============================================================================
# CONFIGURACIÓN PRINCIPAL
# ============================================================================

IMAGE_PATH = Path(r"C:\Users\Gateway\Desktop\PaviaPosition\Entregables_V2\Athens\Sepolia\Sepolia_CHIME_Thermopolis_v2.tif")
OUTPUT_DIR = Path(r"C:\Users\Gateway\Desktop\PaviaPosition\Resultados\EndmemberCandidates\Sepolia_urban")

MIN_FINAL = 100
MAX_FINAL = 200

MAX_SAMPLED_PIXELS_PER_STRATUM = 100000
N_RANDOM_PROJECTIONS = 2000
TOP_PPI_CANDIDATES_PER_STRATUM = 500
N_PCA_COMPONENTS = 16

WINDOW_RADIUS = 1
SAM_NEIGHBOR_DEG = 14
MIN_SUPPORT_NEIGHBORS = 1
MIN_SUPPORT_RATIO = 0.10
MAX_LOCAL_STD = 0.2

DEDUP_SAM_DEG = 1.2

LOW_BRIGHTNESS_PCTL = 2.0
HIGH_BRIGHTNESS_PCTL = 99.8

# Gap real de Thermopolis / Sepolia
GAPS_UM = [(0.9960, 1.9714)]

RGB_TARGETS_UM = (0.640, 0.550, 0.470)
RANDOM_SEED = 42

# Máscara urbana
NDVI_URBAN_MAX = 0.30
RED_TARGET_UM = 0.675
NIR_TARGET_UM = 0.846

# Filtro adicional de brillo dentro de lo urbano
URBAN_BRIGHTNESS_PCTL_LOW = 2.0
URBAN_BRIGHTNESS_PCTL_HIGH = 99.0

# Estratos urbanos por brillo
STRATUM_QUOTAS = {
    "dark": 12,
    "mid": 12,
    "bright": 16,
}

STRATUM_COLORS = {
    "dark": (1.0, 0.2, 0.2),   # rojo
    "mid": (1.0, 1.0, 0.0),    # amarillo
    "bright": (0.0, 1.0, 1.0), # cian
}


# ============================================================================
# CONFIGURACIÓN ROBUSTA DE GDAL / PROJ (ANTES DE IMPORTAR RASTERIO)
# ============================================================================

def _candidate_env_roots():
    roots = []
    env_cp = os.environ.get("CONDA_PREFIX", "").strip()
    if env_cp:
        roots.append(Path(env_cp))

    try:
        roots.append(Path(sys.prefix))
    except Exception:
        pass

    try:
        roots.append(Path(sys.executable).resolve().parent.parent)
    except Exception:
        pass

    uniq = []
    seen = set()
    for r in roots:
        try:
            s = str(r.resolve())
        except Exception:
            s = str(r)
        if s not in seen and s.strip():
            uniq.append(r)
            seen.add(s)
    return uniq


def setup_gdal_proj_env_preimport():
    print("[BOOT] Configurando entorno GDAL/PROJ...")
    roots = _candidate_env_roots()

    chosen = None
    for root in roots:
        proj_dir = root / "Library" / "share" / "proj"
        gdal_dir = root / "Library" / "share" / "gdal"
        bin_dir = root / "Library" / "bin"

        if proj_dir.exists() and gdal_dir.exists():
            chosen = root
            os.environ["PROJ_DATA"] = str(proj_dir)
            os.environ["PROJ_LIB"] = str(proj_dir)
            os.environ["GDAL_DATA"] = str(gdal_dir)

            if os.name == "nt" and bin_dir.exists():
                try:
                    os.add_dll_directory(str(bin_dir))
                    print(f"[INFO] DLL dir agregado: {bin_dir}")
                except Exception as e:
                    print(f"[WARN] No pude agregar DLL dir: {e}")

            if os.name == "nt" and bin_dir.exists():
                dll_names = [
                    "gdal.dll", "gdal308.dll", "gdal309.dll", "gdal310.dll",
                    "proj_9_3.dll", "proj_9_4.dll", "proj.dll"
                ]
                for dlln in dll_names:
                    p = bin_dir / dlln
                    if p.exists():
                        try:
                            ctypes.WinDLL(str(p))
                            print(f"[INFO] DLL cargada: {p.name}")
                            break
                        except Exception:
                            pass
            break

    print(f"[INFO] Python exe = {sys.executable}")
    print(f"[INFO] sys.prefix = {sys.prefix}")
    if chosen is not None:
        print(f"[INFO] Entorno elegido = {chosen}")
    else:
        print("[WARN] No encontré automáticamente un entorno con Library/share/proj y gdal.")

    print(f"[INFO] PROJ_DATA = {os.environ.get('PROJ_DATA', '(unset)')}")
    print(f"[INFO] PROJ_LIB  = {os.environ.get('PROJ_LIB', '(unset)')}")
    print(f"[INFO] GDAL_DATA = {os.environ.get('GDAL_DATA', '(unset)')}")

    proj_db = Path(os.environ["PROJ_LIB"]) / "proj.db" if "PROJ_LIB" in os.environ else None
    if proj_db is not None:
        print(f"[INFO] proj.db exists? {proj_db.exists()} -> {proj_db}")


setup_gdal_proj_env_preimport()

# ============================================================================
# IMPORTS PESADOS (DESPUÉS DEL SETUP DE ENTORNO)
# ============================================================================

try:
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    import rasterio
    from rasterio.errors import NotGeoreferencedWarning
    from sklearn.decomposition import PCA
    import pyproj

    warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)

    try:
        if "PROJ_LIB" in os.environ:
            pyproj.datadir.set_data_dir(os.environ["PROJ_LIB"])
        _ = pyproj.CRS.from_epsg(32634)
        print("[INFO] pyproj CRS check OK (EPSG:32634)")
    except Exception as e:
        print(f"[WARN] pyproj CRS check falló: {e}")

    print(f"[diag] rasterio {rasterio.__version__} GDAL {rasterio.__gdal_version__}")
except Exception:
    print("[FATAL] Falló import de paquetes.")
    traceback.print_exc()
    raise


# ============================================================================
# UTILIDADES ESPECTRALES
# ============================================================================

def l2_normalize_rows(X, eps=1e-12):
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms = np.maximum(norms, eps)
    return X / norms


def l2_normalize_vec(x, eps=1e-12):
    n = np.linalg.norm(x)
    return x / max(n, eps)


def robust_scale01(img):
    arr = img.astype(np.float32).copy()
    valid = np.isfinite(arr)
    if not np.any(valid):
        return np.zeros_like(arr, dtype=np.float32)
    p2, p98 = np.percentile(arr[valid], [2, 98])
    if p98 <= p2:
        return np.zeros_like(arr, dtype=np.float32)
    arr = (arr - p2) / (p98 - p2)
    arr = np.clip(arr, 0, 1)
    arr[~valid] = 0
    return arr


def extract_wavelengths_um(src):
    wl = []

    descriptions = src.descriptions
    if descriptions and any(d is not None for d in descriptions):
        for d in descriptions:
            if d is None:
                wl.append(np.nan)
                continue
            m = re.search(r"([-+]?\d*\.?\d+)", str(d).replace(",", "."))
            if m:
                val = float(m.group(1))
                if val > 50:
                    val /= 1000.0
                wl.append(val)
            else:
                wl.append(np.nan)

    if len(wl) != src.count or np.sum(np.isfinite(wl)) < max(5, src.count // 3):
        wl = []
        for i in range(1, src.count + 1):
            tags = src.tags(i)
            val = None
            for key in ["wavelength", "WAVELENGTH", "center_wavelength", "CENTER_WAVELENGTH"]:
                if key in tags:
                    s = str(tags[key]).replace(",", ".")
                    m = re.search(r"([-+]?\d*\.?\d+)", s)
                    if m:
                        val = float(m.group(1))
                        if val > 50:
                            val /= 1000.0
                        break
            wl.append(np.nan if val is None else val)

    wl = np.array(wl, dtype=np.float32)

    if wl.size != src.count or np.sum(np.isfinite(wl)) < max(5, src.count // 3):
        print("[WARN] No pude extraer wl de metadata. Uso fallback lineal 0.400-2.500 um.")
        wl = np.linspace(0.4, 2.5, src.count, dtype=np.float32)

    finite = np.isfinite(wl)
    if np.sum(finite) >= 2 and not np.all(finite):
        idx = np.arange(wl.size)
        wl = np.interp(idx, idx[finite], wl[finite]).astype(np.float32)

    return wl


def nearest_band_idx(wl_um, target_um):
    return int(np.argmin(np.abs(wl_um - target_um)))


def build_gap_mask(wl_um, gaps_um):
    gap_mask = np.zeros(wl_um.shape, dtype=bool)
    for a, b in gaps_um:
        gap_mask |= (wl_um >= a) & (wl_um <= b)
    return gap_mask


def angular_distance_deg(x, y):
    xn = l2_normalize_vec(x)
    yn = l2_normalize_vec(y)
    return float(np.degrees(np.arccos(np.clip(np.dot(xn, yn), -1.0, 1.0))))


# ============================================================================
# LECTURA Y PREPARACIÓN
# ============================================================================

def read_cube(image_path):
    print(f"[INFO] Abriendo imagen: {image_path}")
    with rasterio.open(image_path) as src:
        cube = src.read().astype(np.float32)  # (L, H, W)
        profile = src.profile
        transform = src.transform
        crs = src.crs
        nodata = src.nodata
        wl_um = extract_wavelengths_um(src)

    L, H, W = cube.shape
    print(f"[INFO] Cube size: H={H}, W={W}, L={L}")
    print(f"[INFO] wl range: [{wl_um.min():.4f}, {wl_um.max():.4f}] um")
    print(f"[INFO] nodata reported: {nodata}")

    cube = np.transpose(cube, (1, 2, 0))  # -> (H, W, L)

    if nodata is not None and np.isfinite(nodata):
        cube[cube == nodata] = np.nan

    return cube, wl_um, profile, transform, crs


def detect_usable_bands(cube, wl_um):
    finite_frac = np.mean(np.isfinite(cube), axis=(0, 1))
    gap_mask = build_gap_mask(wl_um, GAPS_UM)
    non_gap = ~gap_mask

    print(f"[INFO] GAPS_UM = {GAPS_UM}")
    print(f"[INFO] Bandas en gap: {np.sum(gap_mask)} / {cube.shape[2]}")

    if not np.any(non_gap):
        raise RuntimeError("Todas las bandas quedaron dentro del gap. Revisar wl_um o GAPS_UM.")

    finite_frac_nongap = finite_frac[non_gap]
    max_frac = float(np.max(finite_frac_nongap))
    med_frac = float(np.median(finite_frac_nongap))

    print(
        f"[INFO] finite_frac (sin gaps) -> min={finite_frac_nongap.min():.4f}, "
        f"median={med_frac:.4f}, max={max_frac:.4f}"
    )

    if max_frac <= 0:
        raise RuntimeError("Las bandas fuera del gap tienen fracción finita nula. Revisar nodata o lectura del raster.")

    adaptive_thr = max(0.02, 0.20 * max_frac)
    usable = non_gap & (finite_frac >= adaptive_thr)

    print(f"[INFO] Umbral adaptativo para bandas usables = {adaptive_thr:.4f}")
    print(f"[INFO] Bandas usables (sin gaps): {np.sum(usable)} / {cube.shape[2]}")

    if np.sum(usable) < 20:
        fallback_thr = max(0.005, 0.05 * max_frac)
        usable = non_gap & (finite_frac >= fallback_thr)
        print(f"[WARN] Muy pocas bandas en 1ra pasada. Uso fallback_thr = {fallback_thr:.4f}")
        print(f"[INFO] Bandas usables (fallback, sin gaps): {np.sum(usable)} / {cube.shape[2]}")

    if np.sum(usable) < 20:
        raise RuntimeError(
            "Muy pocas bandas usables detectadas incluso excluyendo gaps. "
            "Revisar si el raster tiene nodata masivo o si las bandas están mal leídas."
        )

    removed = np.where(~usable)[0]
    if removed.size > 0:
        print(f"[INFO] Bandas excluidas totales: {removed.size}")
        print(f"       Primeras 10 wl excluidas: {wl_um[removed[:10]]}")

    return usable


def build_base_valid_mask(cube, usable_bands):
    """
    Máscara de validez radiométrica general, antes del filtro urbano.
    """
    X = cube[:, :, usable_bands]
    valid = np.all(np.isfinite(X), axis=2)

    if np.sum(valid) == 0:
        finite_count = np.sum(np.isfinite(X), axis=2)
        min_required = int(np.ceil(0.98 * X.shape[2]))
        valid = finite_count >= min_required
        print(f"[WARN] 'all finite' dejó 0 píxeles. Relajo a >= {min_required}/{X.shape[2]} bandas finitas.")

    brightness = np.full(valid.shape, np.nan, dtype=np.float32)
    if np.any(valid):
        brightness[valid] = np.nanmean(X[valid], axis=1)
        low_thr = np.nanpercentile(brightness[valid], LOW_BRIGHTNESS_PCTL)
        high_thr = np.nanpercentile(brightness[valid], HIGH_BRIGHTNESS_PCTL)
        valid &= brightness >= low_thr
        valid &= brightness <= high_thr
        print(f"[INFO] Brightness thresholds base: low={low_thr:.5f}, high={high_thr:.5f}")

    print(f"[INFO] Píxeles válidos base: {np.sum(valid)} / {valid.size}")
    return valid, brightness


def build_urban_masks(cube, wl_um, usable_bands, valid_base, brightness):
    """
    Construye la máscara urbana excluyendo vegetación con NDVI y luego divide
    el dominio urbano en dark / mid / bright según brillo.
    """
    red_idx = nearest_band_idx(wl_um, RED_TARGET_UM)
    nir_idx = nearest_band_idx(wl_um, NIR_TARGET_UM)

    print(
        f"[INFO] NDVI bands -> red target={RED_TARGET_UM:.3f} selected={wl_um[red_idx]:.4f} | "
        f"nir target={NIR_TARGET_UM:.3f} selected={wl_um[nir_idx]:.4f}"
    )

    red = cube[:, :, red_idx].astype(np.float32)
    nir = cube[:, :, nir_idx].astype(np.float32)

    ndvi = np.full(valid_base.shape, np.nan, dtype=np.float32)
    denom = nir + red
    good = valid_base & np.isfinite(red) & np.isfinite(nir) & (np.abs(denom) > 1e-12)
    ndvi[good] = (nir[good] - red[good]) / denom[good]

    urban_mask = valid_base & np.isfinite(ndvi) & (ndvi <= NDVI_URBAN_MAX)

    if np.sum(urban_mask) == 0:
        raise RuntimeError("La máscara urbana quedó vacía. Relajar NDVI_URBAN_MAX.")

    urb_b = brightness[urban_mask]
    b_low = np.nanpercentile(urb_b, URBAN_BRIGHTNESS_PCTL_LOW)
    b_high = np.nanpercentile(urb_b, URBAN_BRIGHTNESS_PCTL_HIGH)
    urban_mask &= brightness >= b_low
    urban_mask &= brightness <= b_high

    print(f"[INFO] NDVI_URBAN_MAX = {NDVI_URBAN_MAX:.3f}")
    print(f"[INFO] Píxeles urbanos tras NDVI: {np.sum(np.isfinite(ndvi) & (ndvi <= NDVI_URBAN_MAX) & valid_base)}")
    print(f"[INFO] Urban brightness thresholds: low={b_low:.5f}, high={b_high:.5f}")
    print(f"[INFO] Píxeles urbanos finales: {np.sum(urban_mask)} / {urban_mask.size}")

    urb_b = brightness[urban_mask]
    q1, q2 = np.nanpercentile(urb_b, [33.333, 66.667])
    print(f"[INFO] Estratos urbanos por brillo: q33={q1:.5f}, q67={q2:.5f}")

    strata_masks = {}
    strata_masks["dark"] = urban_mask & (brightness <= q1)
    strata_masks["mid"] = urban_mask & (brightness > q1) & (brightness <= q2)
    strata_masks["bright"] = urban_mask & (brightness > q2)

    for sname in ["dark", "mid", "bright"]:
        print(f"[INFO] Urban stratum '{sname}': {np.sum(strata_masks[sname])} pix")

    return ndvi, urban_mask, strata_masks


# ============================================================================
# SELECCIÓN INICIAL POR ESTRATO
# ============================================================================

def sample_valid_pixels(valid_mask, max_samples, rng):
    rows, cols = np.where(valid_mask)
    n = rows.size
    if n == 0:
        raise RuntimeError("No hay píxeles válidos en la máscara dada.")
    if n <= max_samples:
        idx = np.arange(n)
    else:
        idx = rng.choice(n, size=max_samples, replace=False)
    return rows[idx], cols[idx]


def ppi_like_candidates(cube_use, valid_mask, rng, label=""):
    rows_s, cols_s = sample_valid_pixels(valid_mask, MAX_SAMPLED_PIXELS_PER_STRATUM, rng)
    Xs = cube_use[rows_s, cols_s]
    Xs_norm = l2_normalize_rows(Xs)

    n_comp = min(N_PCA_COMPONENTS, Xs_norm.shape[1], max(2, Xs_norm.shape[0] - 1))
    pca = PCA(n_components=n_comp, random_state=RANDOM_SEED)
    Z = pca.fit_transform(Xs_norm)

    print(f"[INFO] [{label}] PCA components usadas: {n_comp}")
    print(f"[INFO] [{label}] Varianza explicada acumulada: {np.sum(pca.explained_variance_ratio_):.4f}")

    Zm = Z - np.mean(Z, axis=0, keepdims=True)
    Zs = np.std(Zm, axis=0, keepdims=True)
    Zs[Zs == 0] = 1.0
    Zm = Zm / Zs

    N = Zm.shape[0]
    counts = np.zeros(N, dtype=np.int32)

    for _ in range(N_RANDOM_PROJECTIONS):
        v = rng.normal(size=Zm.shape[1]).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-12
        proj = Zm @ v
        imin = int(np.argmin(proj))
        imax = int(np.argmax(proj))
        counts[imin] += 1
        counts[imax] += 1

    order = np.argsort(counts)[::-1]
    top_idx = order[:min(TOP_PPI_CANDIDATES_PER_STRATUM, order.size)]

    cand_rows = rows_s[top_idx]
    cand_cols = cols_s[top_idx]
    cand_counts = counts[top_idx]

    print(f"[INFO] [{label}] Candidatos PPI-like iniciales: {top_idx.size}")
    return cand_rows, cand_cols, cand_counts


# ============================================================================
# LOCAL PRUNING
# ============================================================================

def get_window_bounds(r, c, H, W, radius):
    r0 = max(0, r - radius)
    r1 = min(H, r + radius + 1)
    c0 = max(0, c - radius)
    c1 = min(W, c + radius + 1)
    return r0, r1, c0, c1


def medoid_spectrum(X):
    Xn = l2_normalize_rows(X)
    sims = np.clip(Xn @ Xn.T, -1.0, 1.0)
    ang = np.arccos(sims)
    mean_ang = np.mean(ang, axis=1)
    return int(np.argmin(mean_ang))


def local_pruning(cube_use, valid_mask, brightness, cand_rows, cand_cols, cand_counts, stratum_name):
    H, W, _ = cube_use.shape
    accepted = []

    for r, c, ppi_count in zip(cand_rows, cand_cols, cand_counts):
        if not valid_mask[r, c]:
            continue

        spec_center = cube_use[r, c]
        if not np.all(np.isfinite(spec_center)):
            continue

        spec_center_n = l2_normalize_vec(spec_center)

        r0, r1, c0, c1 = get_window_bounds(r, c, H, W, WINDOW_RADIUS)
        patch = cube_use[r0:r1, c0:c1, :]
        patch_valid = valid_mask[r0:r1, c0:c1]

        rr, cc = np.where(patch_valid)
        if rr.size == 0:
            continue

        Xpatch = patch[rr, cc, :]
        Xpatch_n = l2_normalize_rows(Xpatch)

        sims = np.clip(Xpatch_n @ spec_center_n, -1.0, 1.0)
        ang_deg = np.degrees(np.arccos(sims))

        support = ang_deg <= SAM_NEIGHBOR_DEG
        support_count = int(np.sum(support))
        support_ratio = float(support_count / max(1, rr.size))

        if support_count < MIN_SUPPORT_NEIGHBORS:
            continue
        if support_ratio < MIN_SUPPORT_RATIO:
            continue

        Xsupp = Xpatch[support]
        if Xsupp.shape[0] < MIN_SUPPORT_NEIGHBORS:
            continue

        local_std = float(np.mean(np.std(l2_normalize_rows(Xsupp), axis=0)))
        if local_std > MAX_LOCAL_STD:
            continue

        imed = medoid_spectrum(Xsupp)
        spec_repr = Xsupp[imed].astype(np.float32)

        supp_rr = rr[support]
        supp_cc = cc[support]
        med_r = int(r0 + supp_rr[imed])
        med_c = int(c0 + supp_cc[imed])

        mean_support_ang = float(np.mean(ang_deg[support]))
        score = (
            1.0 * float(ppi_count) +
            40.0 * float(support_ratio) +
            10.0 * float(support_count) -
            100.0 * float(local_std) -
            5.0 * float(mean_support_ang)
        )

        accepted.append({
            "row": med_r,
            "col": med_c,
            "row_seed": int(r),
            "col_seed": int(c),
            "ppi_count": int(ppi_count),
            "support_count": int(support_count),
            "support_ratio": float(support_ratio),
            "local_std": float(local_std),
            "mean_support_ang_deg": float(mean_support_ang),
            "brightness": float(brightness[med_r, med_c]) if np.isfinite(brightness[med_r, med_c]) else np.nan,
            "score": float(score),
            "stratum": stratum_name,
            "spectrum": spec_repr,
        })

    if not accepted:
        print(f"[WARN] [{stratum_name}] No quedaron candidatos tras local pruning.")
        return []

    print(f"[INFO] [{stratum_name}] Candidatos aceptados tras pruning local: {len(accepted)}")
    return accepted


# ============================================================================
# DEDUPLICACIÓN Y FUSIÓN
# ============================================================================

def deduplicate_candidates(candidates, limit=None, angle_deg=DEDUP_SAM_DEG):
    candidates = sorted(candidates, key=lambda d: d["score"], reverse=True)

    final = []
    final_specs_n = []

    for cand in candidates:
        xn = l2_normalize_vec(cand["spectrum"])
        duplicated = False
        for yn in final_specs_n:
            ang = np.degrees(np.arccos(np.clip(np.dot(xn, yn), -1.0, 1.0)))
            if ang <= angle_deg:
                duplicated = True
                break
        if not duplicated:
            final.append(cand)
            final_specs_n.append(xn)
        if limit is not None and len(final) >= limit:
            break
    return final


def interleave_lists(lists_dict, order=("dark", "mid", "bright")):
    lists = {k: list(v) for k, v in lists_dict.items()}
    out = []
    added = True
    while added:
        added = False
        for key in order:
            if lists.get(key):
                out.append(lists[key].pop(0))
                added = True
    return out


def build_final_candidates(accepted_by_stratum):
    per_stratum_selected = {}
    leftovers = []

    for sname in ["dark", "mid", "bright"]:
        acc = accepted_by_stratum.get(sname, [])
        sel = deduplicate_candidates(acc, limit=STRATUM_QUOTAS[sname], angle_deg=DEDUP_SAM_DEG)
        per_stratum_selected[sname] = sel

        used_ids = {id(x) for x in sel}
        rem = [x for x in sorted(acc, key=lambda d: d["score"], reverse=True) if id(x) not in used_ids]
        leftovers.extend(rem)

        print(f"[INFO] [{sname}] seleccionados tras dedup local: {len(sel)} / cuota {STRATUM_QUOTAS[sname]}")

    ordered_pool = interleave_lists(per_stratum_selected, order=("dark", "mid", "bright"))
    final = deduplicate_candidates(ordered_pool, limit=MAX_FINAL, angle_deg=DEDUP_SAM_DEG)

    if len(final) < MIN_FINAL and leftovers:
        supplement_pool = [x for x in sorted(leftovers, key=lambda d: d["score"], reverse=True)]
        merged = final + supplement_pool
        final = deduplicate_candidates(merged, limit=MAX_FINAL, angle_deg=DEDUP_SAM_DEG)

    if len(final) < MIN_FINAL:
        print(f"[WARN] Sólo quedaron {len(final)} candidatos únicos. Podés relajar DEDUP_SAM_DEG o el pruning local.")

    print(f"[INFO] Candidatos finales tras fusión global: {len(final)}")
    return final


# ============================================================================
# SALIDAS
# ============================================================================

def make_rgb(cube_use, wl_use):
    r_idx = nearest_band_idx(wl_use, RGB_TARGETS_UM[0])
    g_idx = nearest_band_idx(wl_use, RGB_TARGETS_UM[1])
    b_idx = nearest_band_idx(wl_use, RGB_TARGETS_UM[2])

    print("[INFO] RGB mapping:")
    print(f"   R target={RGB_TARGETS_UM[0]:.3f} -> selected={wl_use[r_idx]:.4f} um")
    print(f"   G target={RGB_TARGETS_UM[1]:.3f} -> selected={wl_use[g_idx]:.4f} um")
    print(f"   B target={RGB_TARGETS_UM[2]:.3f} -> selected={wl_use[b_idx]:.4f} um")

    rgb = np.dstack([
        robust_scale01(cube_use[:, :, r_idx]),
        robust_scale01(cube_use[:, :, g_idx]),
        robust_scale01(cube_use[:, :, b_idx]),
    ])
    return rgb


def save_mask_figures(out_dir, rgb, urban_mask, strata_masks, final_candidates):
    # urban mask
    fig, ax = plt.subplots(figsize=(11, 9))
    ax.imshow(rgb)
    overlay = np.zeros((*urban_mask.shape, 4), dtype=np.float32)
    overlay[urban_mask, 0] = 1.0
    overlay[urban_mask, 3] = 0.35
    ax.imshow(overlay)
    ax.set_title("Máscara urbana (NDVI + filtros de brillo)")
    ax.axis("off")
    fig.tight_layout()
    p = out_dir / "Sepolia_urban_mask.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Figura guardada: {p}")

    # strata map
    fig, ax = plt.subplots(figsize=(11, 9))
    ax.imshow(rgb)
    for sname, mask in strata_masks.items():
        rr, gg, bb = STRATUM_COLORS[sname]
        ov = np.zeros((*mask.shape, 4), dtype=np.float32)
        ov[mask, 0] = rr
        ov[mask, 1] = gg
        ov[mask, 2] = bb
        ov[mask, 3] = 0.28
        ax.imshow(ov)

    for i, cand in enumerate(final_candidates, start=1):
        r = cand["row"]
        c = cand["col"]
        color = STRATUM_COLORS.get(cand["stratum"], (1.0, 1.0, 1.0))
        ax.plot(c, r, marker="o", markersize=7, markeredgewidth=1.2,
                markerfacecolor="none", markeredgecolor=color)
        ax.text(c + 3, r + 3, f"{i}", color=color, fontsize=8, weight="bold")

    ax.set_title("Estratos urbanos y candidatos seleccionados")
    ax.axis("off")
    fig.tight_layout()
    p = out_dir / "Sepolia_urban_strata_map.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Figura guardada: {p}")


def expand_spectrum_to_full_grid(spectrum_use, usable_bands, n_full_bands):
    """
    Expande un espectro calculado sólo sobre las bandas usables a la grilla
    espectral completa de la imagen CHIME-like.

    Las bandas no usadas, por ejemplo las del gap espectral de Thermopolis /
    Sepolia o bandas sin datos válidos, quedan como NaN. Pandas las escribe
    como celdas en blanco en el Excel.
    """
    usable_bands = np.asarray(usable_bands, dtype=bool).ravel()
    spectrum_use = np.asarray(spectrum_use, dtype=np.float32).ravel()

    if usable_bands.size != n_full_bands:
        raise ValueError(
            f"usable_bands tiene longitud {usable_bands.size}, "
            f"pero la grilla completa tiene {n_full_bands} bandas."
        )

    if spectrum_use.size != int(np.sum(usable_bands)):
        raise ValueError(
            f"El espectro del candidato tiene {spectrum_use.size} bandas, "
            f"pero usable_bands marca {int(np.sum(usable_bands))} bandas."
        )

    spectrum_full = np.full(n_full_bands, np.nan, dtype=np.float32)
    spectrum_full[usable_bands] = spectrum_use
    return spectrum_full


def save_outputs(final_candidates, wl_use, cube_use, out_dir, wl_full=None, usable_bands=None):
    out_dir.mkdir(parents=True, exist_ok=True)

    # Por defecto conserva el comportamiento original. Si se pasan wl_full y
    # usable_bands, las salidas espectrales se escriben sobre la grilla completa
    # de la imagen CHIME-like, dejando NaN/blanco en las bandas no usadas.
    if wl_full is None or usable_bands is None:
        wl_out = np.asarray(wl_use, dtype=np.float32).ravel()
        spectra_out = [np.asarray(c["spectrum"], dtype=np.float32).ravel() for c in final_candidates]
    else:
        wl_out = np.asarray(wl_full, dtype=np.float32).ravel()
        spectra_out = [
            expand_spectrum_to_full_grid(c["spectrum"], usable_bands, wl_out.size)
            for c in final_candidates
        ]
        print(
            f"[INFO] Salidas espectrales en grilla completa: "
            f"{wl_out.size} bandas; bandas con valores: {int(np.sum(usable_bands))}; "
            f"bandas en blanco: {wl_out.size - int(np.sum(usable_bands))}"
        )

    spec_data = {"wavelength_um": wl_out}
    meta_rows = []

    for i, cand in enumerate(final_candidates, start=1):
        name = f"CAND_{i:02d}"
        spec_data[name] = spectra_out[i - 1]
        meta_rows.append({
            "candidate_id": name,
            "row": cand["row"],
            "col": cand["col"],
            "row_seed": cand["row_seed"],
            "col_seed": cand["col_seed"],
            "ppi_count": cand["ppi_count"],
            "support_count": cand["support_count"],
            "support_ratio": cand["support_ratio"],
            "local_std": cand["local_std"],
            "mean_support_ang_deg": cand["mean_support_ang_deg"],
            "brightness": cand["brightness"],
            "score": cand["score"],
            "stratum": cand["stratum"],
        })

    df_specs = pd.DataFrame(spec_data)
    df_meta = pd.DataFrame(meta_rows).sort_values(["stratum", "score"], ascending=[True, False])

    excel_path = out_dir / "Sepolia_urban_scene_candidates.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_specs.to_excel(writer, index=False, sheet_name="urban_scene_candidates", na_rep="")
        df_meta.to_excel(writer, index=False, sheet_name="candidate_metadata", na_rep="")
    print(f"[OK] Excel guardado: {excel_path}")

    csv_meta_path = out_dir / "Sepolia_urban_scene_candidates_metadata.csv"
    df_meta.to_csv(csv_meta_path, index=False)
    print(f"[OK] CSV metadata guardado: {csv_meta_path}")

    rgb = make_rgb(cube_use, wl_use)

    fig, ax = plt.subplots(figsize=(11, 9))
    ax.imshow(rgb)
    ax.set_title("Sepolia CHIME-like | candidatos urbanos seleccionados")
    ax.axis("off")
    for i, cand in enumerate(final_candidates, start=1):
        r = cand["row"]
        c = cand["col"]
        color = STRATUM_COLORS.get(cand["stratum"], (1.0, 1.0, 0.0))
        ax.plot(c, r, marker="o", markersize=7, markeredgewidth=1.2,
                markerfacecolor="none", markeredgecolor=color)
        ax.text(c + 3, r + 3, f"{i}", color=color, fontsize=8, weight="bold")
    fig.tight_layout()
    png_rgb = out_dir / "Sepolia_urban_scene_candidates_RGB.png"
    fig.savefig(png_rgb, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Figura RGB guardada: {png_rgb}")

    fig, ax = plt.subplots(figsize=(12, 7))
    for i, cand in enumerate(final_candidates, start=1):
        ax.plot(wl_out, spectra_out[i - 1], linewidth=1.5, label=f"CAND_{i:02d} [{cand['stratum']}]")
    ax.set_xlabel("Wavelength (um)")
    ax.set_ylabel("Reflectance")
    ax.set_title("Espectros urbanos seleccionados desde la escena")
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    png_specs = out_dir / "Sepolia_urban_scene_candidates_spectra.png"
    fig.savefig(png_specs, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Figura de espectros guardada: {png_specs}")

    npz_path = out_dir / "Sepolia_urban_scene_candidates.npz"
    np.savez_compressed(
        npz_path,
        wavelengths_um=wl_out,
        spectra=np.stack(spectra_out, axis=0),
        rows=np.array([c["row"] for c in final_candidates], dtype=np.int32),
        cols=np.array([c["col"] for c in final_candidates], dtype=np.int32),
        scores=np.array([c["score"] for c in final_candidates], dtype=np.float32),
        strata=np.array([c["stratum"] for c in final_candidates], dtype=object),
    )
    print(f"[OK] NPZ guardado: {npz_path}")

    return rgb


# ============================================================================
# MAIN
# ============================================================================

def main():
    rng = np.random.default_rng(RANDOM_SEED)

    print(f"[INFO] IMAGE_PATH = {IMAGE_PATH}")
    print(f"[INFO] OUTPUT_DIR = {OUTPUT_DIR}")

    if not IMAGE_PATH.exists():
        raise FileNotFoundError(f"No existe la imagen: {IMAGE_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cube, wl_um, profile, transform, crs = read_cube(IMAGE_PATH)
    usable_bands = detect_usable_bands(cube, wl_um)

    cube_use = cube[:, :, usable_bands]
    wl_use = wl_um[usable_bands]

    valid_base, brightness = build_base_valid_mask(cube, usable_bands)
    ndvi, urban_mask, strata_masks = build_urban_masks(cube, wl_um, usable_bands, valid_base, brightness)

    accepted_by_stratum = {}
    for sname in ["dark", "mid", "bright"]:
        smask = strata_masks[sname]
        if np.sum(smask) < 10:
            print(f"[WARN] [{sname}] Muy pocos píxeles ({np.sum(smask)}). Salteo estrato.")
            accepted_by_stratum[sname] = []
            continue

        cand_rows, cand_cols, cand_counts = ppi_like_candidates(cube_use, smask, rng, label=sname)
        accepted = local_pruning(cube_use, smask, brightness, cand_rows, cand_cols, cand_counts, stratum_name=sname)
        accepted_by_stratum[sname] = accepted

    final_candidates = build_final_candidates(accepted_by_stratum)

    if len(final_candidates) == 0:
        raise RuntimeError("No se generaron candidatos finales. Relajar NDVI, pruning o deduplicación.")

    rgb = save_outputs(final_candidates, wl_use, cube_use, OUTPUT_DIR, wl_full=wl_um, usable_bands=usable_bands)
    save_mask_figures(OUTPUT_DIR, rgb, urban_mask, strata_masks, final_candidates)

    print("\n======================")
    print("Resumen")
    print("======================")
    print(f"Imagen               : {IMAGE_PATH}")
    print(f"Bandas usables       : {np.sum(usable_bands)} / {cube.shape[2]}")
    print(f"Valid pixels base    : {np.sum(valid_base)} / {valid_base.size}")
    print(f"Urban pixels         : {np.sum(urban_mask)} / {urban_mask.size}")
    print(f"Urban dark pixels    : {np.sum(strata_masks['dark'])}")
    print(f"Urban mid pixels     : {np.sum(strata_masks['mid'])}")
    print(f"Urban bright pixels  : {np.sum(strata_masks['bright'])}")
    print(f"Final spectra        : {len(final_candidates)}")
    print(f"Salida               : {OUTPUT_DIR}")
    print("======================")
    print("[DONE]")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n[FATAL] El script terminó con error. Traceback completo:\n")
        traceback.print_exc()
        sys.exit(1)