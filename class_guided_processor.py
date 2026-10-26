#!/usr/bin/env python3
"""HEATWISE scene-specific class-guided processor, Python 3.11.
Scientific kernels ported from the three supplied scripts; see docs/CHANGES.md.
No runtime dependency on those scripts and no subprocess scientific stages.
"""
from __future__ import annotations
import argparse, copy, hashlib, importlib.metadata, json, logging, math, random, re, sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from rasterio.shutil import copy as rio_copy
from rasterio.warp import transform_bounds
from scipy.interpolate import PchipInterpolator
from sklearn.decomposition import PCA
import yaml
VERSION = "0.2.0"

class Configurable:
    def __init__(self, overrides=None):
        self.config = copy.deepcopy(self.DEFAULTS)
        for key, value in (overrides or {}).items():
            if key not in self.DEFAULTS:
                raise ValueError(f"Unknown {type(self).__name__} setting: {key}")
            self.config[key] = value
        for key,value in self.config.items():
            setattr(self,key,value)

class Extraction(Configurable):
    DEFAULTS = {'MIN_FINAL': 100, 'MAX_FINAL': 200, 'MAX_SAMPLED_PIXELS_PER_STRATUM': 100000, 'N_RANDOM_PROJECTIONS': 2000, 'TOP_PPI_CANDIDATES_PER_STRATUM': 500, 'N_PCA_COMPONENTS': 16, 'WINDOW_RADIUS': 1, 'SAM_NEIGHBOR_DEG': 14, 'MIN_SUPPORT_NEIGHBORS': 1, 'MIN_SUPPORT_RATIO': 0.1, 'MAX_LOCAL_STD': 0.2, 'DEDUP_SAM_DEG': 1.2, 'LOW_BRIGHTNESS_PCTL': 2.0, 'HIGH_BRIGHTNESS_PCTL': 99.8, 'GAPS_UM': [], 'RANDOM_SEED': 42, 'NDVI_URBAN_MAX': 0.3, 'RED_TARGET_UM': 0.675, 'NIR_TARGET_UM': 0.846, 'URBAN_BRIGHTNESS_PCTL_LOW': 2.0, 'URBAN_BRIGHTNESS_PCTL_HIGH': 99.0, 'STRATUM_QUOTAS': {'dark': 12, 'mid': 12, 'bright': 16}}

    def l2_normalize_rows(self, X, eps=1e-12):
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        norms = np.maximum(norms, eps)
        return X / norms

    def l2_normalize_vec(self, x, eps=1e-12):
        n = np.linalg.norm(x)
        return x / max(n, eps)

    def nearest_band_idx(self, wl_um, target_um):
        return int(np.argmin(np.abs(wl_um - target_um)))

    def build_gap_mask(self, wl_um, gaps_um):
        gap_mask = np.zeros(wl_um.shape, dtype=bool)
        for a, b in gaps_um:
            gap_mask |= (wl_um >= a) & (wl_um <= b)
        return gap_mask

    def angular_distance_deg(self, x, y):
        xn = self.l2_normalize_vec(x)
        yn = self.l2_normalize_vec(y)
        return float(np.degrees(np.arccos(np.clip(np.dot(xn, yn), -1.0, 1.0))))

    def detect_usable_bands(self, cube, wl_um):
        finite_frac = np.mean(np.isfinite(cube), axis=(0, 1))
        gap_mask = self.build_gap_mask(wl_um, self.GAPS_UM)
        non_gap = ~gap_mask
        print(f'[INFO] GAPS_UM = {self.GAPS_UM}')
        print(f'[INFO] Bandas en gap: {np.sum(gap_mask)} / {cube.shape[2]}')
        if not np.any(non_gap):
            raise RuntimeError('Todas las bandas quedaron dentro del gap. Revisar wl_um o GAPS_UM.')
        finite_frac_nongap = finite_frac[non_gap]
        max_frac = float(np.max(finite_frac_nongap))
        med_frac = float(np.median(finite_frac_nongap))
        print(f'[INFO] finite_frac (sin gaps) -> min={finite_frac_nongap.min():.4f}, median={med_frac:.4f}, max={max_frac:.4f}')
        if max_frac <= 0:
            raise RuntimeError('Las bandas fuera del gap tienen fracción finita nula. Revisar nodata o lectura del raster.')
        adaptive_thr = max(0.02, 0.2 * max_frac)
        usable = non_gap & (finite_frac >= adaptive_thr)
        print(f'[INFO] Umbral adaptativo para bandas usables = {adaptive_thr:.4f}')
        print(f'[INFO] Bandas usables (sin gaps): {np.sum(usable)} / {cube.shape[2]}')
        if np.sum(usable) < 20:
            fallback_thr = max(0.005, 0.05 * max_frac)
            usable = non_gap & (finite_frac >= fallback_thr)
            print(f'[WARN] Muy pocas bandas en 1ra pasada. Uso fallback_thr = {fallback_thr:.4f}')
            print(f'[INFO] Bandas usables (fallback, sin gaps): {np.sum(usable)} / {cube.shape[2]}')
        if np.sum(usable) < 20:
            raise RuntimeError('Muy pocas bandas usables detectadas incluso excluyendo gaps. Revisar si el raster tiene nodata masivo o si las bandas están mal leídas.')
        removed = np.where(~usable)[0]
        if removed.size > 0:
            print(f'[INFO] Bandas excluidas totales: {removed.size}')
            print(f'       Primeras 10 wl excluidas: {wl_um[removed[:10]]}')
        return usable

    def build_base_valid_mask(self, cube, usable_bands):
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
            low_thr = np.nanpercentile(brightness[valid], self.LOW_BRIGHTNESS_PCTL)
            high_thr = np.nanpercentile(brightness[valid], self.HIGH_BRIGHTNESS_PCTL)
            valid &= brightness >= low_thr
            valid &= brightness <= high_thr
            print(f'[INFO] Brightness thresholds base: low={low_thr:.5f}, high={high_thr:.5f}')
        print(f'[INFO] Píxeles válidos base: {np.sum(valid)} / {valid.size}')
        return (valid, brightness)

    def build_urban_masks(self, cube, wl_um, usable_bands, valid_base, brightness):
        """
        Construye la máscara urbana excluyendo vegetación con NDVI y luego divide
        el dominio urbano en dark / mid / bright según brillo.
        """
        red_idx = self.nearest_band_idx(wl_um, self.RED_TARGET_UM)
        nir_idx = self.nearest_band_idx(wl_um, self.NIR_TARGET_UM)
        print(f'[INFO] NDVI bands -> red target={self.RED_TARGET_UM:.3f} selected={wl_um[red_idx]:.4f} | nir target={self.NIR_TARGET_UM:.3f} selected={wl_um[nir_idx]:.4f}')
        red = cube[:, :, red_idx].astype(np.float32)
        nir = cube[:, :, nir_idx].astype(np.float32)
        ndvi = np.full(valid_base.shape, np.nan, dtype=np.float32)
        denom = nir + red
        good = valid_base & np.isfinite(red) & np.isfinite(nir) & (np.abs(denom) > 1e-12)
        ndvi[good] = (nir[good] - red[good]) / denom[good]
        urban_mask = valid_base & np.isfinite(ndvi) & (ndvi <= self.NDVI_URBAN_MAX)
        if np.sum(urban_mask) == 0:
            raise RuntimeError('La máscara urbana quedó vacía. Relajar NDVI_URBAN_MAX.')
        urb_b = brightness[urban_mask]
        b_low = np.nanpercentile(urb_b, self.URBAN_BRIGHTNESS_PCTL_LOW)
        b_high = np.nanpercentile(urb_b, self.URBAN_BRIGHTNESS_PCTL_HIGH)
        urban_mask &= brightness >= b_low
        urban_mask &= brightness <= b_high
        print(f'[INFO] NDVI_URBAN_MAX = {self.NDVI_URBAN_MAX:.3f}')
        print(f'[INFO] Píxeles urbanos tras NDVI: {np.sum(np.isfinite(ndvi) & (ndvi <= self.NDVI_URBAN_MAX) & valid_base)}')
        print(f'[INFO] Urban brightness thresholds: low={b_low:.5f}, high={b_high:.5f}')
        print(f'[INFO] Píxeles urbanos finales: {np.sum(urban_mask)} / {urban_mask.size}')
        urb_b = brightness[urban_mask]
        q1, q2 = np.nanpercentile(urb_b, [33.333, 66.667])
        print(f'[INFO] Estratos urbanos por brillo: q33={q1:.5f}, q67={q2:.5f}')
        strata_masks = {}
        strata_masks['dark'] = urban_mask & (brightness <= q1)
        strata_masks['mid'] = urban_mask & (brightness > q1) & (brightness <= q2)
        strata_masks['bright'] = urban_mask & (brightness > q2)
        for sname in ['dark', 'mid', 'bright']:
            print(f"[INFO] Urban stratum '{sname}': {np.sum(strata_masks[sname])} pix")
        return (ndvi, urban_mask, strata_masks)

    def sample_valid_pixels(self, valid_mask, max_samples, rng):
        rows, cols = np.where(valid_mask)
        n = rows.size
        if n == 0:
            raise RuntimeError('No hay píxeles válidos en la máscara dada.')
        if n <= max_samples:
            idx = np.arange(n)
        else:
            idx = rng.choice(n, size=max_samples, replace=False)
        return (rows[idx], cols[idx])

    def ppi_like_candidates(self, cube_use, valid_mask, rng, label=''):
        rows_s, cols_s = self.sample_valid_pixels(valid_mask, self.MAX_SAMPLED_PIXELS_PER_STRATUM, rng)
        Xs = cube_use[rows_s, cols_s]
        Xs_norm = self.l2_normalize_rows(Xs)
        n_comp = min(self.N_PCA_COMPONENTS, Xs_norm.shape[1], max(2, Xs_norm.shape[0] - 1))
        pca = PCA(n_components=n_comp, random_state=self.RANDOM_SEED)
        Z = pca.fit_transform(Xs_norm)
        print(f'[INFO] [{label}] PCA components usadas: {n_comp}')
        print(f'[INFO] [{label}] Varianza explicada acumulada: {np.sum(pca.explained_variance_ratio_):.4f}')
        Zm = Z - np.mean(Z, axis=0, keepdims=True)
        Zs = np.std(Zm, axis=0, keepdims=True)
        Zs[Zs == 0] = 1.0
        Zm = Zm / Zs
        N = Zm.shape[0]
        counts = np.zeros(N, dtype=np.int32)
        for _ in range(self.N_RANDOM_PROJECTIONS):
            v = rng.normal(size=Zm.shape[1]).astype(np.float32)
            v /= np.linalg.norm(v) + 1e-12
            proj = Zm @ v
            imin = int(np.argmin(proj))
            imax = int(np.argmax(proj))
            counts[imin] += 1
            counts[imax] += 1
        order = np.argsort(counts)[::-1]
        top_idx = order[:min(self.TOP_PPI_CANDIDATES_PER_STRATUM, order.size)]
        cand_rows = rows_s[top_idx]
        cand_cols = cols_s[top_idx]
        cand_counts = counts[top_idx]
        print(f'[INFO] [{label}] Candidatos PPI-like iniciales: {top_idx.size}')
        return (cand_rows, cand_cols, cand_counts)

    def get_window_bounds(self, r, c, H, W, radius):
        r0 = max(0, r - radius)
        r1 = min(H, r + radius + 1)
        c0 = max(0, c - radius)
        c1 = min(W, c + radius + 1)
        return (r0, r1, c0, c1)

    def medoid_spectrum(self, X):
        Xn = self.l2_normalize_rows(X)
        sims = np.clip(Xn @ Xn.T, -1.0, 1.0)
        ang = np.arccos(sims)
        mean_ang = np.mean(ang, axis=1)
        return int(np.argmin(mean_ang))

    def local_pruning(self, cube_use, valid_mask, brightness, cand_rows, cand_cols, cand_counts, stratum_name):
        H, W, _ = cube_use.shape
        accepted = []
        for r, c, ppi_count in zip(cand_rows, cand_cols, cand_counts):
            if not valid_mask[r, c]:
                continue
            spec_center = cube_use[r, c]
            if not np.all(np.isfinite(spec_center)):
                continue
            spec_center_n = self.l2_normalize_vec(spec_center)
            r0, r1, c0, c1 = self.get_window_bounds(r, c, H, W, self.WINDOW_RADIUS)
            patch = cube_use[r0:r1, c0:c1, :]
            patch_valid = valid_mask[r0:r1, c0:c1]
            rr, cc = np.where(patch_valid)
            if rr.size == 0:
                continue
            Xpatch = patch[rr, cc, :]
            Xpatch_n = self.l2_normalize_rows(Xpatch)
            sims = np.clip(Xpatch_n @ spec_center_n, -1.0, 1.0)
            ang_deg = np.degrees(np.arccos(sims))
            support = ang_deg <= self.SAM_NEIGHBOR_DEG
            support_count = int(np.sum(support))
            support_ratio = float(support_count / max(1, rr.size))
            if support_count < self.MIN_SUPPORT_NEIGHBORS:
                continue
            if support_ratio < self.MIN_SUPPORT_RATIO:
                continue
            Xsupp = Xpatch[support]
            if Xsupp.shape[0] < self.MIN_SUPPORT_NEIGHBORS:
                continue
            local_std = float(np.mean(np.std(self.l2_normalize_rows(Xsupp), axis=0)))
            if local_std > self.MAX_LOCAL_STD:
                continue
            imed = self.medoid_spectrum(Xsupp)
            spec_repr = Xsupp[imed].astype(np.float32)
            supp_rr = rr[support]
            supp_cc = cc[support]
            med_r = int(r0 + supp_rr[imed])
            med_c = int(c0 + supp_cc[imed])
            mean_support_ang = float(np.mean(ang_deg[support]))
            score = 1.0 * float(ppi_count) + 40.0 * float(support_ratio) + 10.0 * float(support_count) - 100.0 * float(local_std) - 5.0 * float(mean_support_ang)
            accepted.append({'row': med_r, 'col': med_c, 'row_seed': int(r), 'col_seed': int(c), 'ppi_count': int(ppi_count), 'support_count': int(support_count), 'support_ratio': float(support_ratio), 'local_std': float(local_std), 'mean_support_ang_deg': float(mean_support_ang), 'brightness': float(brightness[med_r, med_c]) if np.isfinite(brightness[med_r, med_c]) else np.nan, 'score': float(score), 'stratum': stratum_name, 'spectrum': spec_repr})
        if not accepted:
            print(f'[WARN] [{stratum_name}] No quedaron candidatos tras local pruning.')
            return []
        print(f'[INFO] [{stratum_name}] Candidatos aceptados tras pruning local: {len(accepted)}')
        return accepted

    def deduplicate_candidates(self, candidates, limit=None, angle_deg=1.2):
        candidates = sorted(candidates, key=lambda d: d['score'], reverse=True)
        final = []
        final_specs_n = []
        for cand in candidates:
            xn = self.l2_normalize_vec(cand['spectrum'])
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

    def interleave_lists(self, lists_dict, order=('dark', 'mid', 'bright')):
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

    def build_final_candidates(self, accepted_by_stratum):
        per_stratum_selected = {}
        leftovers = []
        for sname in ['dark', 'mid', 'bright']:
            acc = accepted_by_stratum.get(sname, [])
            sel = self.deduplicate_candidates(acc, limit=self.STRATUM_QUOTAS[sname], angle_deg=self.DEDUP_SAM_DEG)
            per_stratum_selected[sname] = sel
            used_ids = {id(x) for x in sel}
            rem = [x for x in sorted(acc, key=lambda d: d['score'], reverse=True) if id(x) not in used_ids]
            leftovers.extend(rem)
            print(f'[INFO] [{sname}] seleccionados tras dedup local: {len(sel)} / cuota {self.STRATUM_QUOTAS[sname]}')
        ordered_pool = self.interleave_lists(per_stratum_selected, order=('dark', 'mid', 'bright'))
        final = self.deduplicate_candidates(ordered_pool, limit=self.MAX_FINAL, angle_deg=self.DEDUP_SAM_DEG)
        if len(final) < self.MIN_FINAL and leftovers:
            supplement_pool = [x for x in sorted(leftovers, key=lambda d: d['score'], reverse=True)]
            merged = final + supplement_pool
            final = self.deduplicate_candidates(merged, limit=self.MAX_FINAL, angle_deg=self.DEDUP_SAM_DEG)
        if len(final) < self.MIN_FINAL:
            print(f'[WARN] Sólo quedaron {len(final)} candidatos únicos. Podés relajar DEDUP_SAM_DEG o el pruning local.')
        print(f'[INFO] Candidatos finales tras fusión global: {len(final)}')
        return final

class Matching(Configurable):
    DEFAULTS = {'MATCH_RANK_METRIC': 'mbdsa', 'CLASS_ASSIGNMENT_METRIC': 'sam', 'USE_ACCEPTANCE_THRESHOLDS': False, 'MAX_ACCEPTED_SAM_DEG': 8.0, 'MAX_ACCEPTED_MBDSA': 0.12, 'MIN_MARGIN_TO_2ND_SAM_DEG': 1.0, 'MIN_MARGIN_TO_2ND_MBDSA': 0.01, 'X3_WEIGHT_CLASS_SCORE': 0.5, 'X3_WEIGHT_PAIR_MARGIN': 0.35, 'X3_WEIGHT_DIVERSITY': 0.15}

    def normalize_name(self, s):
        s = str(s).strip()
        s = s.replace('\n', ' ').replace('\r', ' ')
        s = re.sub('\\s+', ' ', s)
        return s

    def find_wavelength_column(self, columns):
        lower = [self.normalize_name(c).lower() for c in columns]
        preferred_patterns = ['wavelength_um', 'wavelength', 'wavelength [', 'lambda', 'wl', 'longitud']
        for patt in preferred_patterns:
            for orig, low in zip(columns, lower):
                if patt in low:
                    return orig
        return columns[0]

    def read_spectral_library_excel(self, xlsx_path, preferred_sheet=None):
        """
        Lee un Excel con formato:
    
            wavelength_um | Spectrum_1 | Spectrum_2 | ...
    
        Retorna:
            wl:         (L,)
            X:          (N_spectra, L)
            names:      list[str]
            sheet_name: str
            wl_col:     str
        """
        xls = pd.ExcelFile(xlsx_path)
        sheet_name = preferred_sheet if preferred_sheet is not None and preferred_sheet in xls.sheet_names else xls.sheet_names[0]
        df = pd.read_excel(xlsx_path, sheet_name=sheet_name)
        df = df.dropna(axis=0, how='all').dropna(axis=1, how='all')
        wl_col = self.find_wavelength_column(df.columns)
        wl = pd.to_numeric(df[wl_col], errors='coerce').to_numpy(dtype=float)
        valid_rows = np.isfinite(wl)
        df = df.loc[valid_rows].copy()
        wl = wl[valid_rows]
        order = np.argsort(wl)
        wl = wl[order]
        df = df.iloc[order].reset_index(drop=True)
        spec_cols = [c for c in df.columns if c != wl_col]
        if len(spec_cols) == 0:
            raise ValueError(f'No encontré columnas espectrales en {xlsx_path}, hoja {sheet_name}')
        X = []
        names = []
        for c in spec_cols:
            vals = pd.to_numeric(df[c], errors='coerce').to_numpy(dtype=float)
            if np.all(~np.isfinite(vals)):
                continue
            X.append(vals)
            names.append(self.normalize_name(c))
        if len(X) == 0:
            raise ValueError(f'No encontré espectros válidos en {xlsx_path}, hoja {sheet_name}')
        X = np.vstack(X)
        return (wl.astype(np.float32), X.astype(np.float32), names, sheet_name, wl_col)

    def read_multiple_gusl_sheets(self, xlsx_path, sheet_names):
        """
        Lee múltiples hojas GUSL desde el mismo Excel.
    
        Cada hoja puede tener una grilla espectral distinta.
        Por eso esta función NO concatena todavía las matrices espectrales.
        Devuelve una lista de diccionarios, uno por hoja.
    
        Para evitar nombres duplicados entre Brussels y DLR, agrega el sufijo:
            __BRUSSELS_APEX_GENLIB
            __DLR
    
        Ejemplo:
            Asphalt_1__BRUSSELS_APEX_GENLIB
            Asphalt_1__DLR
    
        Esto conserva el prefijo del material, por lo que sigue funcionando:
            material_prefix_match("Asphalt_1__DLR", ["Asphalt"])
        """
        out = []
        xls = pd.ExcelFile(xlsx_path)
        available_sheets = xls.sheet_names
        for sheet in sheet_names:
            if sheet not in available_sheets:
                raise ValueError(f"La hoja '{sheet}' no existe en {xlsx_path}. Hojas disponibles: {available_sheets}")
            wl, X, names, sheet_name, wl_col = self.read_spectral_library_excel(xlsx_path, preferred_sheet=sheet)
            names_with_source = [f'{name}__{sheet_name}' for name in names]
            out.append({'sheet_name': sheet_name, 'wl_col': wl_col, 'wl': wl, 'X': X, 'names': names_with_source})
        return out

    def l2_normalize_rows(self, X, eps=1e-12):
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        norms = np.maximum(norms, eps)
        return X / norms

    def pchip_library_to_target_grid(self, lib_wl, lib_X, target_wl):
        """
        Interpola cada espectro de la biblioteca a la grilla objetivo usando PCHIP,
        pero NO extrapola.
    
        Decisión metodológica:
        - Las bandas objetivo dentro del rango espectral real de cada firma GUSL se
          interpolan con PCHIP.
        - Las bandas objetivo fuera del rango real de cada firma GUSL se dejan como
          NaN.
        - Las métricas espectrales posteriores descartan automáticamente las bandas
          que no sean finitas en candidatos y GUSL.
    
        Esto evita introducir valores artificiales en los extremos espectrales o en
        regiones que no fueron realmente medidas por la librería original.
        """
        lib_wl = np.asarray(lib_wl, dtype=float).ravel()
        target_wl = np.asarray(target_wl, dtype=float).ravel()
        out = np.full((lib_X.shape[0], target_wl.size), np.nan, dtype=np.float32)
        for i in range(lib_X.shape[0]):
            y = np.asarray(lib_X[i, :], dtype=float).ravel()
            good = np.isfinite(lib_wl) & np.isfinite(y)
            if np.sum(good) < 2:
                continue
            xg = lib_wl[good]
            yg = y[good]
            order = np.argsort(xg)
            xg = xg[order]
            yg = yg[order]
            x_unique, unique_idx = np.unique(xg, return_index=True)
            y_unique = yg[unique_idx]
            if x_unique.size < 2:
                continue
            inside = (target_wl >= x_unique[0]) & (target_wl <= x_unique[-1])
            if not np.any(inside):
                continue
            yi = np.full(target_wl.shape, np.nan, dtype=np.float64)
            if x_unique.size >= 3:
                interpolator = PchipInterpolator(x_unique, y_unique, extrapolate=False)
                yi[inside] = interpolator(target_wl[inside])
            else:
                yi[inside] = np.interp(target_wl[inside], x_unique, y_unique)
            out[i, :] = yi.astype(np.float32)
        return out

    def compute_similarity_matrices(self, scene_X, lib_X, eps=1e-12):
        """
        Calcula SAM y MBDSA entre candidatos de escena y firmas de librería.
    
        scene_X: (Nc, L)
        lib_X:   (Nl, L)
    
        Retorna:
            sam_deg:     (Nc, Nl)
            mbdsa:       (Nc, Nl)
            valid_bands: (L,)
    
        MBDSA:
            SAM_rad = spectral angle in radians
            MBD = |mean(scene) - mean(lib)| / (mean(scene) + mean(lib) + eps)
            MBDSA = (1 + MBD) * (1 + sin(SAM_rad)) - 1
    
        Nota:
        - Si hay NaN, se eliminan bandas globalmente, de modo que todas las
          comparaciones se calculen en el mismo subconjunto espectral común.
        - Las firmas finales se siguen guardando en la grilla completa.
        - En esta versión, los NaN pueden aparecer porque GUSL se interpola sin
          extrapolar fuera de su rango espectral real.
        """
        valid_bands = np.all(np.isfinite(scene_X), axis=0) & np.all(np.isfinite(lib_X), axis=0)
        n_valid = int(np.sum(valid_bands))
        if n_valid < 2:
            raise RuntimeError(f'No hay suficientes bandas finitas para calcular métricas. Bandas válidas: {n_valid}')
        scene_valid = scene_X[:, valid_bands].astype(np.float64)
        lib_valid = lib_X[:, valid_bands].astype(np.float64)
        scene_n = self.l2_normalize_rows(scene_valid, eps=eps)
        lib_n = self.l2_normalize_rows(lib_valid, eps=eps)
        dots = np.clip(scene_n @ lib_n.T, -1.0, 1.0)
        sam_rad = np.arccos(dots)
        sam_deg = np.degrees(sam_rad)
        scene_mean = np.nanmean(scene_valid, axis=1, keepdims=True)
        lib_mean = np.nanmean(lib_valid, axis=1, keepdims=True).T
        mbd = np.abs(scene_mean - lib_mean) / (np.abs(scene_mean) + np.abs(lib_mean) + eps)
        mbdsa = (1.0 + mbd) * (1.0 + np.sin(sam_rad)) - 1.0
        return (sam_deg.astype(np.float32), mbdsa.astype(np.float32), valid_bands)

    def get_rank_column(self):
        metric = str(self.MATCH_RANK_METRIC).strip().lower()
        if metric == 'sam':
            return 'sam_deg'
        if metric == 'mbdsa':
            return 'mbdsa'
        raise ValueError(f"MATCH_RANK_METRIC inválida: {self.MATCH_RANK_METRIC}. Usar 'sam' o 'mbdsa'.")

    def get_metric_column(self, metric_name):
        metric = str(metric_name).strip().lower()
        if metric == 'sam':
            return 'sam_deg'
        if metric == 'mbdsa':
            return 'mbdsa'
        raise ValueError(f"Métrica inválida: {metric_name}. Usar 'sam' o 'mbdsa'.")

    def material_prefix_match(self, name, prefixes):
        n = self.normalize_name(name).lower()
        for p in prefixes:
            pp = self.normalize_name(p).lower()
            if n == pp:
                return True
            if n.startswith(pp + '_'):
                return True
            if n.startswith(pp + ' '):
                return True
        return False

    def summarize_candidates_by_target_class(self, df_top, target_class_prefixes):
        """
        Para cada candidato:
          - busca el mejor match dentro de cada clase objetivo usando la métrica
            definida por CLASS_ASSIGNMENT_METRIC;
          - determina la clase objetivo ganadora;
          - calcula margen respecto de la segunda clase.
    
        Retorna un DataFrame con una fila por candidato.
        """
        rank_col = self.get_metric_column(self.CLASS_ASSIGNMENT_METRIC)
        rows = []
        for cand, sub in df_top.groupby('candidate', sort=False):
            rec = {'candidate': cand}
            class_scores = []
            for cls, prefixes in target_class_prefixes.items():
                class_mask = sub['library_match'].apply(lambda x: self.material_prefix_match(x, prefixes))
                s = sub[class_mask].sort_values([rank_col, 'rank'], ascending=[True, True])
                if s.empty:
                    rec[f'{cls}_match'] = None
                    rec[f'{cls}_sam'] = np.nan
                    rec[f'{cls}_mbdsa'] = np.nan
                    rec[f'{cls}_score'] = np.nan
                    rec[f'{cls}_rank'] = np.nan
                else:
                    best = s.iloc[0]
                    rec[f'{cls}_match'] = str(best['library_match'])
                    rec[f'{cls}_sam'] = float(best['sam_deg'])
                    rec[f'{cls}_mbdsa'] = float(best['mbdsa'])
                    rec[f'{cls}_score'] = float(best[rank_col])
                    rec[f'{cls}_rank'] = int(best['rank'])
                    class_scores.append((cls, float(best[rank_col]), float(best['sam_deg']), float(best['mbdsa'])))
            if len(class_scores) == 0:
                rec['best_target_class'] = None
                rec['best_target_score'] = np.nan
                rec['best_target_sam'] = np.nan
                rec['best_target_mbdsa'] = np.nan
                rec['second_target_class'] = None
                rec['second_target_score'] = np.nan
                rec['second_target_sam'] = np.nan
                rec['second_target_mbdsa'] = np.nan
                rec['margin_to_2nd_score'] = np.nan
                rec['margin_to_2nd_sam'] = np.nan
                rec['margin_to_2nd_mbdsa'] = np.nan
            else:
                class_scores = sorted(class_scores, key=lambda x: x[1])
                best_cls, best_score, best_sam, best_mbdsa = class_scores[0]
                if len(class_scores) >= 2:
                    second_cls, second_score, second_sam, second_mbdsa = class_scores[1]
                else:
                    second_cls = None
                    second_score = np.nan
                    second_sam = np.nan
                    second_mbdsa = np.nan
                rec['best_target_class'] = best_cls
                rec['best_target_score'] = best_score
                rec['best_target_sam'] = best_sam
                rec['best_target_mbdsa'] = best_mbdsa
                rec['second_target_class'] = second_cls
                rec['second_target_score'] = second_score
                rec['second_target_sam'] = second_sam
                rec['second_target_mbdsa'] = second_mbdsa
                rec['margin_to_2nd_score'] = second_score - best_score if pd.notna(second_score) else np.nan
                rec['margin_to_2nd_sam'] = second_sam - best_sam if pd.notna(second_sam) else np.nan
                rec['margin_to_2nd_mbdsa'] = second_mbdsa - best_mbdsa if pd.notna(second_mbdsa) else np.nan
            rows.append(rec)
        return pd.DataFrame(rows)

    def add_acceptance_flags(self, df_summary):
        """
        Agrega columnas:
            accepted_by_thresholds
            acceptance_reason
    
        Si USE_ACCEPTANCE_THRESHOLDS=False, marca True para todo candidato con clase.
        """
        df = df_summary.copy()
        metric = str(self.MATCH_RANK_METRIC).strip().lower()
        accepted = []
        reasons = []
        for _, row in df.iterrows():
            best_cls = row.get('best_target_class', None)
            best_sam = row.get('best_target_sam', np.nan)
            best_mbdsa = row.get('best_target_mbdsa', np.nan)
            margin_sam = row.get('margin_to_2nd_sam', np.nan)
            margin_mbdsa = row.get('margin_to_2nd_mbdsa', np.nan)
            if best_cls is None or pd.isna(best_cls):
                accepted.append(False)
                reasons.append('NO_TARGET_CLASS')
                continue
            if not self.USE_ACCEPTANCE_THRESHOLDS:
                accepted.append(True)
                reasons.append('ACCEPTED_NO_THRESHOLDS')
                continue
            if pd.isna(best_sam):
                accepted.append(False)
                reasons.append('NO_BEST_SAM')
                continue
            if pd.isna(best_mbdsa):
                accepted.append(False)
                reasons.append('NO_BEST_MBDSA')
                continue
            if best_sam > self.MAX_ACCEPTED_SAM_DEG:
                accepted.append(False)
                reasons.append(f'SAM_TOO_HIGH>{self.MAX_ACCEPTED_SAM_DEG}')
                continue
            if best_mbdsa > self.MAX_ACCEPTED_MBDSA:
                accepted.append(False)
                reasons.append(f'MBDSA_TOO_HIGH>{self.MAX_ACCEPTED_MBDSA}')
                continue
            if metric == 'sam':
                if pd.isna(margin_sam):
                    accepted.append(False)
                    reasons.append('NO_SAM_MARGIN')
                    continue
                if margin_sam < self.MIN_MARGIN_TO_2ND_SAM_DEG:
                    accepted.append(False)
                    reasons.append(f'SAM_MARGIN_TOO_LOW<{self.MIN_MARGIN_TO_2ND_SAM_DEG}')
                    continue
            elif metric == 'mbdsa':
                if pd.isna(margin_mbdsa):
                    accepted.append(False)
                    reasons.append('NO_MBDSA_MARGIN')
                    continue
                if margin_mbdsa < self.MIN_MARGIN_TO_2ND_MBDSA:
                    accepted.append(False)
                    reasons.append(f'MBDSA_MARGIN_TOO_LOW<{self.MIN_MARGIN_TO_2ND_MBDSA}')
                    continue
            accepted.append(True)
            reasons.append('ACCEPTED_BY_THRESHOLDS')
        df['accepted_by_thresholds'] = accepted
        df['acceptance_reason'] = reasons
        return df

    def collect_candidates_for_class_average(self, df_summary, scene_names, scene_full_for_average, final_target_classes, top_x_for_average):
        """
        Construye los endmembers finales promediados por clase.
    
        Cambio principal:
        - Se promedian solo los TOP X candidatos mejor matcheados para cada clase.
        - El ranking se hace con MATCH_RANK_METRIC:
              "mbdsa" -> menor MBDSA
              "sam"   -> menor SAM
    
        Importante:
        - La selección puede venir de FULL o MASK3.
        - El promedio se hace siempre usando scene_full_for_average, es decir,
          las firmas completas, no las firmas recortadas por MASK3.
        """
        name_to_idx = {name: i for i, name in enumerate(scene_names)}
        metric = str(self.MATCH_RANK_METRIC).strip().lower()
        if metric == 'sam':
            sort_col = None
            sort_col_suffix = 'sam'
            margin_col = 'margin_to_2nd_sam'
        elif metric == 'mbdsa':
            sort_col = None
            sort_col_suffix = 'mbdsa'
            margin_col = 'margin_to_2nd_mbdsa'
        else:
            raise ValueError(f"MATCH_RANK_METRIC inválida: {self.MATCH_RANK_METRIC}. Usar 'sam' o 'mbdsa'.")
        rows_summary = []
        rows_used = []
        averaged_endmembers = {}
        top_x_for_average = int(top_x_for_average)
        if top_x_for_average < 1:
            raise ValueError(f'top_x_for_average debe ser >= 1. Valor recibido: {top_x_for_average}')
        for cls in final_target_classes:
            class_sam_col = f'{cls}_sam'
            class_mbdsa_col = f'{cls}_mbdsa'
            class_score_col = f'{cls}_score'
            match_col = f'{cls}_match'
            if metric == 'sam':
                sort_col = class_sam_col
            else:
                sort_col = class_mbdsa_col
            if sort_col not in df_summary.columns:
                valid = pd.DataFrame()
            else:
                valid = df_summary[(df_summary['best_target_class'] == cls) & df_summary[sort_col].notna() & (df_summary['accepted_by_thresholds'] == True)].copy()
            if not valid.empty:
                valid = valid.sort_values(by=[sort_col, margin_col, 'candidate'], ascending=[True, False, True]).reset_index(drop=True)
                valid_for_average = valid.head(top_x_for_average).copy()
            else:
                valid_for_average = pd.DataFrame()
            if valid_for_average.empty:
                averaged_endmembers[cls] = np.full(scene_full_for_average.shape[1], np.nan, dtype=np.float32)
                rows_summary.append({'class_name': cls, 'ranking_metric': metric, 'top_x_requested': top_x_for_average, 'n_candidates_available': int(len(valid)), 'n_candidates_used': 0, 'mean_class_sam_deg': np.nan, 'best_class_sam_deg': np.nan, 'mean_class_mbdsa': np.nan, 'best_class_mbdsa': np.nan, 'mean_class_score': np.nan, 'best_class_score': np.nan, 'mean_margin_to_2nd_sam_deg': np.nan, 'mean_margin_to_2nd_mbdsa': np.nan, 'candidates_used': None, 'matches_used': None, 'status': 'NO_VALID_CANDIDATE'})
                continue
            idxs = []
            cand_names = []
            match_names = []
            for _, row in valid_for_average.iterrows():
                cand = str(row['candidate'])
                if cand not in name_to_idx:
                    continue
                idxs.append(name_to_idx[cand])
                cand_names.append(cand)
                match_names.append(str(row[match_col]) if pd.notna(row[match_col]) else '')
                rows_used.append({'class_name': cls, 'ranking_metric': metric, 'top_x_requested': top_x_for_average, 'candidate': cand, 'class_match': row[match_col], 'class_sam_deg': float(row[class_sam_col]) if pd.notna(row[class_sam_col]) else np.nan, 'class_mbdsa': float(row[class_mbdsa_col]) if pd.notna(row[class_mbdsa_col]) else np.nan, 'class_score': float(row[class_score_col]) if pd.notna(row[class_score_col]) else np.nan, 'best_target_class': row['best_target_class'], 'best_target_score': float(row['best_target_score']) if pd.notna(row['best_target_score']) else np.nan, 'best_target_sam_deg': float(row['best_target_sam']) if pd.notna(row['best_target_sam']) else np.nan, 'best_target_mbdsa': float(row['best_target_mbdsa']) if pd.notna(row['best_target_mbdsa']) else np.nan, 'second_target_class': row['second_target_class'], 'second_target_score': float(row['second_target_score']) if pd.notna(row['second_target_score']) else np.nan, 'second_target_sam_deg': float(row['second_target_sam']) if pd.notna(row['second_target_sam']) else np.nan, 'second_target_mbdsa': float(row['second_target_mbdsa']) if pd.notna(row['second_target_mbdsa']) else np.nan, 'margin_to_2nd_score': float(row['margin_to_2nd_score']) if pd.notna(row['margin_to_2nd_score']) else np.nan, 'margin_to_2nd_sam_deg': float(row['margin_to_2nd_sam']) if pd.notna(row['margin_to_2nd_sam']) else np.nan, 'margin_to_2nd_mbdsa': float(row['margin_to_2nd_mbdsa']) if pd.notna(row['margin_to_2nd_mbdsa']) else np.nan, 'acceptance_reason': row.get('acceptance_reason', '')})
            if len(idxs) == 0:
                averaged_endmembers[cls] = np.full(scene_full_for_average.shape[1], np.nan, dtype=np.float32)
                rows_summary.append({'class_name': cls, 'ranking_metric': metric, 'top_x_requested': top_x_for_average, 'n_candidates_available': int(len(valid)), 'n_candidates_used': 0, 'mean_class_sam_deg': np.nan, 'best_class_sam_deg': np.nan, 'mean_class_mbdsa': np.nan, 'best_class_mbdsa': np.nan, 'mean_class_score': np.nan, 'best_class_score': np.nan, 'mean_margin_to_2nd_sam_deg': np.nan, 'mean_margin_to_2nd_mbdsa': np.nan, 'candidates_used': None, 'matches_used': None, 'status': 'NO_VALID_CANDIDATE_IN_SCENE_NAMES'})
                continue
            spectra = scene_full_for_average[idxs, :]
            avg_spec = np.nanmean(spectra, axis=0).astype(np.float32)
            averaged_endmembers[cls] = avg_spec
            rows_summary.append({'class_name': cls, 'ranking_metric': metric, 'top_x_requested': top_x_for_average, 'n_candidates_available': int(len(valid)), 'n_candidates_used': len(idxs), 'mean_class_sam_deg': float(np.nanmean(valid_for_average[class_sam_col].to_numpy(dtype=float))), 'best_class_sam_deg': float(np.nanmin(valid_for_average[class_sam_col].to_numpy(dtype=float))), 'mean_class_mbdsa': float(np.nanmean(valid_for_average[class_mbdsa_col].to_numpy(dtype=float))), 'best_class_mbdsa': float(np.nanmin(valid_for_average[class_mbdsa_col].to_numpy(dtype=float))), 'mean_class_score': float(np.nanmean(valid_for_average[class_score_col].to_numpy(dtype=float))), 'best_class_score': float(np.nanmin(valid_for_average[class_score_col].to_numpy(dtype=float))), 'mean_margin_to_2nd_sam_deg': float(np.nanmean(valid_for_average['margin_to_2nd_sam'].to_numpy(dtype=float))), 'mean_margin_to_2nd_mbdsa': float(np.nanmean(valid_for_average['margin_to_2nd_mbdsa'].to_numpy(dtype=float))), 'candidates_used': '; '.join(cand_names), 'matches_used': '; '.join(match_names), 'status': 'OK'})
        df_avg_summary = pd.DataFrame(rows_summary)
        df_used = pd.DataFrame(rows_used)
        return (df_avg_summary, df_used, averaged_endmembers)

    def _normalize_cost(self, values):
        """
        Normaliza valores donde menor es mejor.
        Retorna costos en [0, 1], donde 0 es el mejor valor.
        """
        arr = np.asarray(values, dtype=float)
        out = np.full(arr.shape, 0.5, dtype=float)
        finite = np.isfinite(arr)
        if not np.any(finite):
            return out
        vals = arr[finite]
        vmin = np.nanmin(vals)
        vmax = np.nanmax(vals)
        if abs(vmax - vmin) < 1e-12:
            out[finite] = 0.0
        else:
            out[finite] = (vals - vmin) / (vmax - vmin)
        return out

    def _normalize_benefit(self, values):
        """
        Normaliza valores donde mayor es mejor.
        Retorna beneficios en [0, 1], donde 1 es el mejor valor.
        """
        arr = np.asarray(values, dtype=float)
        out = np.full(arr.shape, 0.5, dtype=float)
        finite = np.isfinite(arr)
        if not np.any(finite):
            return out
        vals = arr[finite]
        vmin = np.nanmin(vals)
        vmax = np.nanmax(vals)
        if abs(vmax - vmin) < 1e-12:
            out[finite] = 1.0
        else:
            out[finite] = (vals - vmin) / (vmax - vmin)
        return out

    def _sam_between_spectra_deg(self, x, y, eps=1e-12):
        """
        SAM entre dos firmas 1D. Usa solo bandas finitas en ambas.
        """
        x = np.asarray(x, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
        good = np.isfinite(x) & np.isfinite(y)
        if np.sum(good) < 2:
            return np.nan
        xx = x[good]
        yy = y[good]
        nx = np.linalg.norm(xx)
        ny = np.linalg.norm(yy)
        if nx < eps or ny < eps:
            return np.nan
        dot = np.clip(np.dot(xx, yy) / (nx * ny), -1.0, 1.0)
        return float(np.degrees(np.arccos(dot)))

    def _add_pairwise_asphalt_concrete_margins(self, df_summary):
        """
        Agrega márgenes dirigidos asphalt/concrete:
    
            asphalt_road:
                concrete_sam - asphalt_road_sam
                concrete_mbdsa - asphalt_road_mbdsa
    
            concrete:
                asphalt_road_sam - concrete_sam
                asphalt_road_mbdsa - concrete_mbdsa
    
        Estos márgenes son distintos del margen general contra la segunda clase:
        aquí se mide explícitamente la distancia respecto de la clase que más se
        está confundiendo.
        """
        df = df_summary.copy()
        required = ['asphalt_road_sam', 'concrete_sam', 'asphalt_road_mbdsa', 'concrete_mbdsa', 'asphalt_road_score', 'concrete_score']
        for col in required:
            if col not in df.columns:
                df[col] = np.nan
        df['margin_asphalt_vs_concrete_sam'] = df['concrete_sam'] - df['asphalt_road_sam']
        df['margin_asphalt_vs_concrete_mbdsa'] = df['concrete_mbdsa'] - df['asphalt_road_mbdsa']
        df['margin_asphalt_vs_concrete_score'] = df['concrete_score'] - df['asphalt_road_score']
        df['margin_concrete_vs_asphalt_sam'] = df['asphalt_road_sam'] - df['concrete_sam']
        df['margin_concrete_vs_asphalt_mbdsa'] = df['asphalt_road_mbdsa'] - df['concrete_mbdsa']
        df['margin_concrete_vs_asphalt_score'] = df['asphalt_road_score'] - df['concrete_score']
        return df

    def _fill_missing_pair_margin_for_ranking(self, margins):
        """
        Si el match de la clase opuesta no aparece entre los TOP_K, el margen queda NaN.
        En ese caso se interpreta como 'oponente no cercano dentro del TOP_K' y se le
        asigna el mejor margen finito disponible para el ranking interno.
        """
        arr = np.asarray(margins, dtype=float).copy()
        finite = np.isfinite(arr)
        if np.any(finite):
            arr[~finite] = np.nanmax(arr[finite])
        else:
            arr[:] = 0.0
        return arr

    def select_asphalt_concrete_x3(self, mode_name, df_summary, scene_names, scene_cmp, scene_full_for_average, wavelength_um, top_n=3):
        """
        Selecciona 3 candidatos de asphalt_road y 3 de concrete.
    
        La selección NO modifica el promedio final del script. Solo construye una
        salida diagnóstica adicional.
    
        Lógica:
        - El candidato debe tener best_target_class == asphalt_road o concrete.
        - Debe estar aceptado por la lógica existente del script.
        - Se favorece:
            a) menor score/SAM/MBDSA de la clase propia;
            b) mayor margen explícito contra la clase opuesta;
            c) mayor diversidad espectral respecto de los ya seleccionados.
        """
        metric = str(self.MATCH_RANK_METRIC).strip().lower()
        if metric == 'sam':
            metric_suffix = 'sam'
        elif metric == 'mbdsa':
            metric_suffix = 'mbdsa'
        else:
            raise ValueError(f"MATCH_RANK_METRIC inválida: {self.MATCH_RANK_METRIC}. Usar 'sam' o 'mbdsa'.")
        df = self._add_pairwise_asphalt_concrete_margins(df_summary)
        name_to_idx = {name: i for i, name in enumerate(scene_names)}
        selection_rows = []
        selected_for_spectra = []
        selection_plan = [{'class_name': 'asphalt_road', 'opponent_class': 'concrete', 'pair_margin_sam_col': 'margin_asphalt_vs_concrete_sam', 'pair_margin_mbdsa_col': 'margin_asphalt_vs_concrete_mbdsa', 'pair_margin_score_col': 'margin_asphalt_vs_concrete_score'}, {'class_name': 'concrete', 'opponent_class': 'asphalt_road', 'pair_margin_sam_col': 'margin_concrete_vs_asphalt_sam', 'pair_margin_mbdsa_col': 'margin_concrete_vs_asphalt_mbdsa', 'pair_margin_score_col': 'margin_concrete_vs_asphalt_score'}]
        for plan in selection_plan:
            cls = plan['class_name']
            opponent = plan['opponent_class']
            class_sam_col = f'{cls}_sam'
            class_mbdsa_col = f'{cls}_mbdsa'
            class_score_col = f'{cls}_score'
            class_match_col = f'{cls}_match'
            opponent_sam_col = f'{opponent}_sam'
            opponent_mbdsa_col = f'{opponent}_mbdsa'
            opponent_score_col = f'{opponent}_score'
            opponent_match_col = f'{opponent}_match'
            if metric_suffix == 'sam':
                class_metric_col = class_sam_col
                pair_margin_metric_col = plan['pair_margin_sam_col']
            else:
                class_metric_col = class_mbdsa_col
                pair_margin_metric_col = plan['pair_margin_mbdsa_col']
            needed_cols = ['candidate', 'best_target_class', 'accepted_by_thresholds', class_metric_col]
            missing_cols = [c for c in needed_cols if c not in df.columns]
            if missing_cols:
                continue
            valid = df[(df['best_target_class'] == cls) & (df['accepted_by_thresholds'] == True) & df[class_metric_col].notna()].copy()
            valid = valid[valid['candidate'].apply(lambda x: str(x) in name_to_idx)].copy()
            if valid.empty:
                continue
            valid = valid.reset_index(drop=True)
            quality_values = valid[class_metric_col].to_numpy(dtype=float)
            pair_margin_values = self._fill_missing_pair_margin_for_ranking(valid[pair_margin_metric_col].to_numpy(dtype=float))
            quality_cost_all = self._normalize_cost(quality_values)
            pair_margin_benefit_all = self._normalize_benefit(pair_margin_values)
            selected_positions = []
            while len(selected_positions) < int(top_n):
                remaining_positions = [i for i in range(len(valid)) if i not in selected_positions]
                if len(remaining_positions) == 0:
                    break
                quality_cost = quality_cost_all[remaining_positions]
                pair_margin_benefit = pair_margin_benefit_all[remaining_positions]
                if len(selected_positions) == 0:
                    diversity_benefit = np.ones(len(remaining_positions), dtype=float)
                    selection_score = 0.6 * quality_cost + 0.4 * (1.0 - pair_margin_benefit)
                else:
                    diversity_values = []
                    selected_candidate_indices = [name_to_idx[str(valid.loc[pos, 'candidate'])] for pos in selected_positions]
                    for pos in remaining_positions:
                        cand_idx = name_to_idx[str(valid.loc[pos, 'candidate'])]
                        dists = [self._sam_between_spectra_deg(scene_cmp[cand_idx, :], scene_cmp[sel_idx, :]) for sel_idx in selected_candidate_indices]
                        if np.any(np.isfinite(dists)):
                            diversity_values.append(float(np.nanmin(dists)))
                        else:
                            diversity_values.append(np.nan)
                    diversity_benefit = self._normalize_benefit(diversity_values)
                    selection_score = self.X3_WEIGHT_CLASS_SCORE * quality_cost + self.X3_WEIGHT_PAIR_MARGIN * (1.0 - pair_margin_benefit) + self.X3_WEIGHT_DIVERSITY * (1.0 - diversity_benefit)
                order = np.lexsort((valid.loc[remaining_positions, 'candidate'].astype(str).to_numpy(), selection_score))
                chosen_local = int(order[0])
                chosen_pos = int(remaining_positions[chosen_local])
                selected_positions.append(chosen_pos)
                row = valid.loc[chosen_pos].copy()
                cand = str(row['candidate'])
                cand_idx = name_to_idx[cand]
                selected_for_spectra.append({'mode': mode_name, 'class_name': cls, 'x3_rank': len(selected_positions), 'candidate': cand, 'scene_index': cand_idx})
                selection_rows.append({'mode': mode_name, 'class_name': cls, 'opponent_class': opponent, 'x3_rank': len(selected_positions), 'candidate': cand, 'selection_score': float(selection_score[chosen_local]), 'ranking_metric': metric, 'class_match': str(row[class_match_col]) if class_match_col in row and pd.notna(row[class_match_col]) else '', 'opponent_match': str(row[opponent_match_col]) if opponent_match_col in row and pd.notna(row[opponent_match_col]) else '', 'class_sam_deg': float(row[class_sam_col]) if class_sam_col in row and pd.notna(row[class_sam_col]) else np.nan, 'opponent_sam_deg': float(row[opponent_sam_col]) if opponent_sam_col in row and pd.notna(row[opponent_sam_col]) else np.nan, 'margin_vs_opponent_sam_deg': float(row[plan['pair_margin_sam_col']]) if plan['pair_margin_sam_col'] in row and pd.notna(row[plan['pair_margin_sam_col']]) else np.nan, 'class_mbdsa': float(row[class_mbdsa_col]) if class_mbdsa_col in row and pd.notna(row[class_mbdsa_col]) else np.nan, 'opponent_mbdsa': float(row[opponent_mbdsa_col]) if opponent_mbdsa_col in row and pd.notna(row[opponent_mbdsa_col]) else np.nan, 'margin_vs_opponent_mbdsa': float(row[plan['pair_margin_mbdsa_col']]) if plan['pair_margin_mbdsa_col'] in row and pd.notna(row[plan['pair_margin_mbdsa_col']]) else np.nan, 'class_score': float(row[class_score_col]) if class_score_col in row and pd.notna(row[class_score_col]) else np.nan, 'opponent_score': float(row[opponent_score_col]) if opponent_score_col in row and pd.notna(row[opponent_score_col]) else np.nan, 'margin_vs_opponent_score': float(row[plan['pair_margin_score_col']]) if plan['pair_margin_score_col'] in row and pd.notna(row[plan['pair_margin_score_col']]) else np.nan, 'best_target_class': row.get('best_target_class', ''), 'second_target_class': row.get('second_target_class', ''), 'margin_to_2nd_sam_deg': float(row['margin_to_2nd_sam']) if 'margin_to_2nd_sam' in row and pd.notna(row['margin_to_2nd_sam']) else np.nan, 'margin_to_2nd_mbdsa': float(row['margin_to_2nd_mbdsa']) if 'margin_to_2nd_mbdsa' in row and pd.notna(row['margin_to_2nd_mbdsa']) else np.nan, 'quality_cost_normalized': float(quality_cost_all[chosen_pos]), 'pair_margin_benefit_normalized': float(pair_margin_benefit_all[chosen_pos]), 'diversity_benefit_normalized': float(diversity_benefit[chosen_local]), 'n_valid_candidates_for_class': int(len(valid)), 'accepted_by_thresholds': bool(row.get('accepted_by_thresholds', False)), 'acceptance_reason': row.get('acceptance_reason', '')})
        df_selection = pd.DataFrame(selection_rows)
        df_spectra = pd.DataFrame({'wavelength_um': np.asarray(wavelength_um, dtype=float).ravel()})
        for item in selected_for_spectra:
            cand = item['candidate']
            cand_idx = int(item['scene_index'])
            col_name = f"{item['mode']}_{item['class_name']}_x{item['x3_rank']}_{cand}"
            df_spectra[col_name] = scene_full_for_average[cand_idx, :]
        return (df_selection, df_spectra)

    def build_top_matches_dataframe(self, scene_names, lib_names_valid, sam_mat, mbdsa_mat, metric_name, top_k):
        """
        Construye un DataFrame de top matches usando la métrica indicada.
    
        Se usa internamente para que la asignación de clase pueda hacerse con SAM,
        aunque el ranking principal y los outputs Top/Best se mantengan con MBDSA.
        """
        rank_col = self.get_metric_column(metric_name)
        if rank_col == 'sam_deg':
            rank_mat = sam_mat
        elif rank_col == 'mbdsa':
            rank_mat = mbdsa_mat
        else:
            raise RuntimeError(f'rank_col inesperada: {rank_col}')
        rows_top = []
        for i, cname in enumerate(scene_names):
            order = np.argsort(rank_mat[i, :])
            top_idx = order[:min(top_k, len(order))]
            for rank, j in enumerate(top_idx, start=1):
                rows_top.append({'candidate': cname, 'rank': rank, 'ranking_metric': metric_name, 'library_match': lib_names_valid[j], 'score': float(rank_mat[i, j]), 'sam_deg': float(sam_mat[i, j]), 'mbdsa': float(mbdsa_mat[i, j])})
        return pd.DataFrame(rows_top)

class BandSelection(Configurable):
    DEFAULTS = {'REG_EPS': 1e-06}

    def preprocess_matrix(self, X, mode='none'):
        X = np.asarray(X, dtype=float).copy()
        if mode == 'none':
            return X.astype(np.float32)
        if mode == 'l2':
            n = np.linalg.norm(X, axis=1, keepdims=True)
            n[n == 0] = 1.0
            return (X / n).astype(np.float32)
        if mode == 'snv':
            mu = np.nanmean(X, axis=1, keepdims=True)
            sd = np.nanstd(X, axis=1, keepdims=True)
            sd[sd == 0] = 1.0
            return ((X - mu) / sd).astype(np.float32)
        raise ValueError(f'PREPROCESS_MODE no reconocido: {mode}')

    def build_group_arrays(self, names, X, groups):
        name_to_idx = {n: i for i, n in enumerate(names)}
        out = {}
        for g, cols in groups.items():
            idx = [name_to_idx[c] for c in cols]
            out[g] = np.asarray(X[idx, :], dtype=np.float32)
        return out

    def pairwise_standardized_euclidean(self, class_means, band_idx, band_scales, eps=1e-12):
        """
        class_means: dict {class_name: 1D spectrum}
        band_idx   : iterable de índices de bandas
        band_scales: 1D array con escala por banda
        """
        keys = list(class_means.keys())
        vals = []
        band_idx = np.asarray(list(band_idx), dtype=int)
        denom = band_scales[band_idx].copy()
        denom[denom < eps] = 1.0
        for i in range(len(keys)):
            xi = class_means[keys[i]][band_idx]
            for j in range(i + 1, len(keys)):
                xj = class_means[keys[j]][band_idx]
                d = np.sqrt(np.sum(((xi - xj) / denom) ** 2))
                vals.append(d)
        vals = np.asarray(vals, dtype=float)
        return (float(np.mean(vals)), float(np.min(vals)))

    def bhattacharyya_distance_diag(self, mu1, var1, mu2, var2, eps=1e-12):
        """
        Bhattacharyya distance con covarianzas diagonales.
        """
        mu1 = np.asarray(mu1, dtype=float)
        mu2 = np.asarray(mu2, dtype=float)
        var1 = np.asarray(var1, dtype=float)
        var2 = np.asarray(var2, dtype=float)
        var1 = np.maximum(var1, eps)
        var2 = np.maximum(var2, eps)
        avg = 0.5 * (var1 + var2)
        term1 = 0.125 * np.sum((mu1 - mu2) ** 2 / avg)
        term2 = 0.5 * np.sum(np.log(avg / np.sqrt(var1 * var2)))
        return float(term1 + term2)

    def pairwise_bhattacharyya_diag(self, group_arrays, band_idx, reg_eps=1e-06):
        """
        group_arrays: dict {class_name: (n_samples, n_bands)}
        """
        keys = list(group_arrays.keys())
        vals = []
        band_idx = np.asarray(list(band_idx), dtype=int)
        stats = {}
        for k in keys:
            X = group_arrays[k][:, band_idx]
            mu = np.nanmean(X, axis=0)
            if X.shape[0] >= 2:
                var = np.nanvar(X, axis=0, ddof=1)
            else:
                var = np.zeros(X.shape[1], dtype=float)
            var = np.maximum(var, reg_eps)
            stats[k] = (mu, var)
        for i in range(len(keys)):
            mu1, var1 = stats[keys[i]]
            for j in range(i + 1, len(keys)):
                mu2, var2 = stats[keys[j]]
                vals.append(self.bhattacharyya_distance_diag(mu1, var1, mu2, var2, eps=reg_eps))
        vals = np.asarray(vals, dtype=float)
        return (float(np.mean(vals)), float(np.min(vals)))

    def compute_single_band_scores(self, wl, group_arrays, use_exact_bdistance):
        """
        Score por banda individual: avg separability y min separability.
        """
        class_means = {k: np.nanmean(v, axis=0) for k, v in group_arrays.items()}
        all_means = np.vstack([class_means[k] for k in class_means.keys()])
        band_scales = np.nanstd(all_means, axis=0)
        band_scales[band_scales == 0] = 1.0
        rows = []
        for b in range(len(wl)):
            if use_exact_bdistance:
                avg_s, min_s = self.pairwise_bhattacharyya_diag(group_arrays, [b], reg_eps=self.REG_EPS)
            else:
                avg_s, min_s = self.pairwise_standardized_euclidean(class_means, [b], band_scales)
            rows.append({'band_idx': b, 'wavelength_um': float(wl[b]), 'avg_sep': avg_s, 'min_sep': min_s, 'combo_score': 0.5 * (avg_s + min_s)})
        return pd.DataFrame(rows).sort_values(['combo_score', 'avg_sep', 'min_sep'], ascending=False).reset_index(drop=True)

    def sample_band_combinations(self, candidate_idx, k, n_random, seed=42):
        candidate_idx = list(candidate_idx)
        total_possible = math.comb(len(candidate_idx), k)
        if total_possible <= n_random:
            return list(combinations(candidate_idx, k))
        rng = random.Random(seed)
        combos = set()
        while len(combos) < n_random:
            comb = tuple(sorted(rng.sample(candidate_idx, k)))
            combos.add(comb)
        return sorted(combos)

    def evaluate_combinations(self, wl, group_arrays, combos, use_exact_bdistance):
        class_means = {k: np.nanmean(v, axis=0) for k, v in group_arrays.items()}
        all_means = np.vstack([class_means[k] for k in class_means.keys()])
        band_scales = np.nanstd(all_means, axis=0)
        band_scales[band_scales == 0] = 1.0
        rows = []
        for combo in combos:
            if use_exact_bdistance:
                avg_s, min_s = self.pairwise_bhattacharyya_diag(group_arrays, combo, reg_eps=self.REG_EPS)
            else:
                avg_s, min_s = self.pairwise_standardized_euclidean(class_means, combo, band_scales)
            rows.append({'band_indices': ','.join(map(str, combo)), 'wavelengths_um': ','.join((f'{wl[i]:.6f}' for i in combo)), 'avg_sep': avg_s, 'min_sep': min_s})
        return pd.DataFrame(rows)

    def build_frequency_table(self, wl, top_avg_df, top_min_df):
        freq = np.zeros(len(wl), dtype=int)
        freq_avg = np.zeros(len(wl), dtype=int)
        freq_min = np.zeros(len(wl), dtype=int)
        for _, row in top_avg_df.iterrows():
            idx = [int(x) for x in str(row['band_indices']).split(',')]
            for i in idx:
                freq[i] += 1
                freq_avg[i] += 1
        for _, row in top_min_df.iterrows():
            idx = [int(x) for x in str(row['band_indices']).split(',')]
            for i in idx:
                freq[i] += 1
                freq_min[i] += 1
        df = pd.DataFrame({'band_idx': np.arange(len(wl)), 'wavelength_um': wl, 'freq_total': freq, 'freq_top_avg': freq_avg, 'freq_top_min': freq_min}).sort_values(['freq_total', 'freq_top_min', 'freq_top_avg', 'wavelength_um'], ascending=[False, False, False, True]).reset_index(drop=True)
        return df

    def recommend_bands_from_frequency(self, freq_df, n_final=15, min_spacing_um=0.04):
        selected = []
        for _, row in freq_df.iterrows():
            wl = float(row['wavelength_um'])
            if all((abs(wl - s['wavelength_um']) >= min_spacing_um for s in selected)):
                selected.append({'band_idx': int(row['band_idx']), 'wavelength_um': wl, 'freq_total': int(row['freq_total']), 'freq_top_avg': int(row['freq_top_avg']), 'freq_top_min': int(row['freq_top_min'])})
            if len(selected) >= n_final:
                break
        return pd.DataFrame(selected).sort_values('wavelength_um').reset_index(drop=True)


Matching.DEFAULTS.update({'MATCH_RANK_METRIC': 'mbdsa', 'CLASS_ASSIGNMENT_METRIC': 'sam', 'USE_ACCEPTANCE_THRESHOLDS': False, 'MAX_ACCEPTED_SAM_DEG': 8.0, 'MAX_ACCEPTED_MBDSA': 0.12, 'MIN_MARGIN_TO_2ND_SAM_DEG': 1.0, 'MIN_MARGIN_TO_2ND_MBDSA': 0.01, 'X3_WEIGHT_CLASS_SCORE': 0.5, 'X3_WEIGHT_PAIR_MARGIN': 0.35, 'X3_WEIGHT_DIVERSITY': 0.15, 'GUSL_SHEETS': ['BRUSSELS_APEX_GENLIB', 'DLR'], 'TOP_K': 50, 'TOP_X_MATERIALS_FOR_AVERAGE': 3, 'FINAL_TARGET_CLASSES': ['asphalt_road', 'concrete', 'metal', 'terracota', 'vegetation'], 'ASPHALT_CONCRETE_X3_COUNT': 3})
BandSelection.DEFAULTS.update({'REG_EPS': 1e-06, 'PRESELECT_TOP_BANDS': 100, 'BANDS_PER_COMBO': 15, 'N_RANDOM_COMBINATIONS': 500000, 'TOP_N_COMBINATIONS': 100, 'N_FINAL_BANDS': 15, 'MIN_SPACING_UM': 0.04, 'PREPROCESS_MODE': 'none'})

Matching.DEFAULTS["TARGET_CLASS_PREFIXES"] = {'asphalt_road': ['Asphalt'], 'concrete': ['Concrete'], 'metal': ['Metal', 'Roof', 'Zinc'], 'terracota': ['Terracotta', 'Clay', 'Tile'], 'vegetation': ['Vegetation'], 'bitumen_aux': ['Bitumen'], 'soil_aux': ['Soil'], 'water_aux': ['Water']}

BandSelection.DEFAULTS.update(WL_MIN=None, WL_MAX=None, INVALID_INTERVALS_UM=[])

def infer_groups(names, known_classes=None, explicit=None):
    """Strip numeric replicate suffixes only from registered classes.

    Unknown names remain separate. No splitting of arbitrary material names.
    Explicit mappings take precedence and are recorded in selected_bands.json.
    """
    known = set(known_classes or ['asphalt_road','concrete','metal','terracota','vegetation'])
    result = {}
    for name in names:
        base = (explicit or {}).get(name, name)
        if name not in (explicit or {}):
            for cls in sorted(known, key=len, reverse=True):
                if name == cls or re.fullmatch(re.escape(cls) + r'(?:__|_)\d+', name):
                    base = cls
                    break
        result.setdefault(base, []).append(name)
    return result


def validate_wavelengths(wl, count):
    wl = np.asarray(wl, dtype=np.float64)
    if wl.ndim != 1 or len(wl) != count or not np.all(np.isfinite(wl)):
        raise ValueError('A finite wavelength in micrometers is required for every input band.')
    if len(np.unique(wl)) != count or np.any(wl <= 0):
        raise ValueError('Duplicate or nonpositive image wavelengths are ambiguous.')
    return wl


def read_image(path, wavelength_file=None):
    """Read physical reflectance with all GDAL masks, scale and offset applied.

    Metadata never invents or interpolates missing wavelength centers. Explicit
    text wavelengths are in micrometers. Numeric descriptions must be unambiguous.
    """
    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError('Input raster must have a CRS.')
        if wavelength_file:
            wl = np.loadtxt(wavelength_file, ndmin=1)
        else:
            wl = []
            for b in range(1, src.count+1):
                tags = {k.lower():v for k,v in src.tags(b).items()}
                value = next((tags[k] for k in ['wavelength_um','wavelength','center_wavelength'] if k in tags),None)
                unit = tags.get('wavelength_units',tags.get('units','')).lower()
                if value is None:
                    desc = src.descriptions[b-1] or ''
                    m = re.fullmatch(r'\s*([\d.]+)\s*(um|µm|nm)?\s*',desc)
                    if not m:
                        raise ValueError(f'Missing/ambiguous wavelength for band {b}; supply --wavelengths.')
                    value,unit=m.groups();unit=unit or ''
                value=float(value)
                if unit=='nm' or (not unit and value>50):value/=1000
                wl.append(value)
        wl=validate_wavelengths(wl,src.count)
        raw=src.read(masked=True).astype(np.float32).filled(np.nan)
        scales=np.asarray(src.scales,dtype=np.float64);offsets=np.asarray(src.offsets,dtype=np.float64)
        cube=(raw * scales[:,None,None]+offsets[:,None,None]).astype(np.float32)
        profile=src.profile.copy()
    order=np.argsort(wl,kind='stable')
    return cube[order].transpose(1,2,0),wl[order],order,profile


def extract_candidates(cube, wl, cfg):
    ex=Extraction(cfg['extraction']);ex.RANDOM_SEED=cfg['seed']
    usable=ex.detect_usable_bands(cube,wl)
    valid,brightness=ex.build_base_valid_mask(cube,usable)
    # The legacy 98%-finite fallback cannot feed PCA. Do not impute reflectance.
    valid &= np.all(np.isfinite(cube[:,:,usable]),axis=2)
    mode=cfg['vegetation_mode']
    if mode not in ('urban_only','separate','all'):
        raise ValueError('vegetation_mode must be urban_only, separate or all')
    ndvi=np.full(valid.shape,np.nan)
    if mode!='all':
        for target in [ex.RED_TARGET_UM,ex.NIR_TARGET_UM]:
            j=ex.nearest_band_idx(wl,target)
            if not usable[j] or abs(wl[j]-target)>cfg['ndvi_max_delta_um']:
                raise ValueError('NDVI requires valid red and NIR bands within configured tolerance; use all explicitly for other sensors.')
        # Handle scenes with no urban pixels without discarding vegetation.
        red=cube[:,:,ex.nearest_band_idx(wl,ex.RED_TARGET_UM)]
        nir=cube[:,:,ex.nearest_band_idx(wl,ex.NIR_TARGET_UM)]
        good=valid & (np.abs(red+nir)>1e-12)
        ndvi[good]=(nir[good]-red[good])/(nir[good]+red[good])
        if np.any(valid & (ndvi<=ex.NDVI_URBAN_MAX)):
            ndvi,urban,strata=ex.build_urban_masks(cube,wl,usable,valid,brightness)
        else:
            strata={k:np.zeros(valid.shape,bool) for k in ('dark','mid','bright')}
    else:
        if not valid.any():raise ValueError('No complete finite pixels available.')
        q1,q2=np.percentile(brightness[valid],[33.333,66.667])
        strata={'dark':valid&(brightness<=q1),'mid':valid&(brightness>q1)&(brightness<=q2),'bright':valid&(brightness>q2)}
    rng=np.random.default_rng(cfg['seed']);accepted={}
    if mode=='separate':strata['vegetation']=valid & (ndvi>ex.NDVI_URBAN_MAX)
    for name,mask in strata.items():
        if mask.sum()<10:
            accepted[name]=[];continue
        rr,cc,counts=ex.ppi_like_candidates(cube[:,:,usable],mask,rng,label=name)
        accepted[name]=ex.local_pruning(cube[:,:,usable],mask,brightness,rr,cc,counts,name)
    final=ex.build_final_candidates(accepted)
    if mode=='separate':
        # Preserve the legacy urban pool, then append a separately pruned/deduped
        # vegetation pool. No ground-truth or class labels are used here.
        veg=ex.deduplicate_candidates(accepted['vegetation'],limit=cfg['vegetation_quota'],angle_deg=ex.DEDUP_SAM_DEG)
        final=ex.deduplicate_candidates(final+veg,limit=ex.MAX_FINAL+cfg['vegetation_quota'],angle_deg=ex.DEDUP_SAM_DEG)
    if not final:raise ValueError('No spectral candidates survived extraction.')
    return final,usable,strata


def match_candidates(m, X, wl, names, library, library_names, mode, output, export):
    """Reselect classes and bundles in the supplied metric space (FULL/MASK3)."""
    valid_lib=np.any(np.isfinite(library),axis=1)
    library=library[valid_lib]
    library_names=[n for n,ok in zip(library_names,valid_lib) if ok]
    if not len(library):raise ValueError(f'{mode}: no GUSL spectra with coverage.')
    sam,mbdsa,metric_mask=m.compute_similarity_matrices(X,library)
    if metric_mask.sum() < (10 if mode=='FULL' else len(wl)):
        raise ValueError(f'{mode}: insufficient common GUSL coverage: {metric_mask.sum()}/{len(wl)} bands. MASK3 must use every selected band.')
    top=m.build_top_matches_dataframe(names,library_names,sam,mbdsa,m.CLASS_ASSIGNMENT_METRIC,m.TOP_K)
    summary=m.add_acceptance_flags(m.summarize_candidates_by_target_class(top,m.TARGET_CLASS_PREFIXES))
    avg_summary,used,averages=m.collect_candidates_for_class_average(summary,names,X,m.FINAL_TARGET_CLASSES,m.TOP_X_MATERIALS_FOR_AVERAGE)
    x3,_=m.select_asphalt_concrete_x3(mode,summary,names,X,X,wl,m.ASPHALT_CONCRETE_X3_COUNT)
    endmembers={};name_to_i={n:i for i,n in enumerate(names)}
    for cls in m.FINAL_TARGET_CLASSES:
        if cls in ('asphalt_road','concrete'):
            if not x3.empty:
                selected=x3[x3.class_name==cls].sort_values(['x3_rank','candidate'])
                for j,(_,row) in enumerate(selected.iterrows(),1):endmembers[f'{cls}_{j}']=X[name_to_i[row.candidate]].copy()
        elif cls in averages and np.all(np.isfinite(averages[cls])):
            endmembers[cls]=averages[cls]
    if len(endmembers)<2:raise ValueError(f'{mode}: fewer than two endmembers selected; inspect candidate classes and GUSL.')
    output.mkdir(parents=True,exist_ok=True)
    for filename,frame in [('class_assignments',summary),('average_summary',avg_summary),('candidates_used',used),('bundle_selection',x3)]:frame.to_csv(output/f'{mode}_{filename}.csv',index=False)
    if export:
        np.savez_compressed(output/f'{mode}_metrics.npz',sam=sam,mbdsa=mbdsa,metric_mask=metric_mask,library_names=np.array(library_names),candidate_names=np.array(names))
    return endmembers,metric_mask


def evaluate_combinations_fast(selector, wl, groups, combos, exact):
    """Algebraically identical diagonal/pairwise scores, computed in batches.

    Accumulate squared Euclidean pair distances before sqrt; accumulate diagonal
    Bhattacharyya contributions before averaging/minimizing class pairs.
    """
    keys=list(groups);means={k:np.nanmean(v,axis=0) for k,v in groups.items()}
    scales=np.nanstd(np.vstack(list(means.values())),axis=0);scales[scales<1e-12]=1
    pair=[]
    for i,a in enumerate(keys):
        for b in keys[i+1:]:
            if exact:
                va=np.maximum(np.nanvar(groups[a],axis=0,ddof=1),selector.REG_EPS).astype(float)
                vb=np.maximum(np.nanvar(groups[b],axis=0,ddof=1),selector.REG_EPS).astype(float)
                mu_a=means[a].astype(float);mu_b=means[b].astype(float);avg=.5*(va+vb)
                pair.append(.125*(mu_a-mu_b)**2/avg+.5*np.log(avg/np.sqrt(va*vb)))
            else:pair.append(((means[a]-means[b])/scales)**2)
    pair=np.array(pair);out=[]
    for start in range(0,len(combos),4096):
        ids=np.asarray(combos[start:start+4096],int)
        scores=pair[:,ids].sum(axis=2)
        if not exact:scores=np.sqrt(scores)
        for ids1,avg1,min1 in zip(ids,scores.mean(axis=0),scores.min(axis=0)):
            out.append({'band_indices':','.join(map(str,ids1)),'avg_sep':float(avg1),'min_sep':float(min1)})
    return pd.DataFrame(out)


def select_bands(endmembers, wl, eligible, cfg, output):
    selector=BandSelection(cfg['bands'])
    names=list(endmembers);X=np.stack(list(endmembers.values()))
    groups=infer_groups(names,cfg['matching']['FINAL_TARGET_CLASSES'],cfg.get('class_mapping'))
    if len(groups)<2:raise ValueError('Band selection requires at least two material classes, not just replicates.')
    domain=eligible.copy()
    if selector.WL_MIN is not None:domain &= wl>=selector.WL_MIN
    if selector.WL_MAX is not None:domain &= wl<=selector.WL_MAX
    for low,high in selector.INVALID_INTERVALS_UM:domain &= ~((wl>=low)&(wl<=high))
    idx=np.flatnonzero(domain & np.all(np.isfinite(X),axis=0))
    w=wl[idx];X=selector.preprocess_matrix(X[:,idx],selector.PREPROCESS_MODE)
    arrays=selector.build_group_arrays(names,X,groups)
    exact=all(len(v)>=2 for v in arrays.values())
    per=selector.compute_single_band_scores(w,arrays,exact)
    pool=per.band_idx.iloc[:selector.PRESELECT_TOP_BANDS].astype(int).tolist()
    if not 1<=selector.BANDS_PER_COMBO<=len(pool):raise ValueError('Combination size exceeds eligible preselection pool.')
    if selector.N_RANDOM_COMBINATIONS<1 or selector.TOP_N_COMBINATIONS<1:raise ValueError('Combination counts must be positive.')
    combos=selector.sample_band_combinations(pool,selector.BANDS_PER_COMBO,selector.N_RANDOM_COMBINATIONS,cfg['seed'])
    evaluated=evaluate_combinations_fast(selector,w,arrays,combos,exact)
    top_avg=evaluated.sort_values(['avg_sep','min_sep','band_indices'],ascending=[False,False,True]).head(selector.TOP_N_COMBINATIONS)
    top_min=evaluated.sort_values(['min_sep','avg_sep','band_indices'],ascending=[False,False,True]).head(selector.TOP_N_COMBINATIONS)
    frequency=selector.build_frequency_table(w,top_avg,top_min)
    rec=selector.recommend_bands_from_frequency(frequency,selector.N_FINAL_BANDS,selector.MIN_SPACING_UM)
    if len(rec)!=selector.N_FINAL_BANDS:
        raise ValueError(f'Spacing/ranking yielded {len(rec)} of {selector.N_FINAL_BANDS} requested bands; no silent relaxation.')
    selected=idx[rec.band_idx.to_numpy(int)]
    with pd.ExcelWriter(output/'band_selection.xlsx') as writer:
        for name,frame in [('per_band_scores',per),('top_avg_combinations',top_avg),('top_min_combinations',top_min),('band_frequency',frequency),('recommended_bands',rec)]:frame.to_excel(writer,sheet_name=name,index=False)
    details={'method':'bhattacharyya_diagonal_regularized' if exact else 'standardized_euclidean_proxy','groups':groups,'class_sample_counts':{k:len(v) for k,v in arrays.items()},'evaluated_combinations':len(combos),'eligible_full_grid_indices_base0':idx.tolist(),'selected_scores':rec.merge(per,on=['band_idx','wavelength_um']).to_dict('records')}
    return selected,details


def write_reduced_cog(image, output, original_indices, wavelengths):
    """Copy selected pixels in windows; apply declared source scale/offset only."""
    tmp=output.with_suffix('.temporary.tif')
    with rasterio.open(image) as src:
        profile=src.profile.copy();profile.update(driver='GTiff',count=len(original_indices),dtype='float32',nodata=np.nan,tiled=True,blockxsize=256,blockysize=256,compress='deflate')
        with rasterio.open(tmp,'w',**profile) as dst:
            # Dataset tags excluding stale full-grid spectral vectors.
            dst.update_tags(**{k:v for k,v in src.tags().items() if not any(s in k.lower() for s in ('wavelength','fwhm','band'))})
            for j,(i,wl) in enumerate(zip(original_indices,wavelengths),1):
                tags=src.tags(int(i)+1)
                for key in list(tags):
                    if key.lower() in ('wavelength','wavelength_um','center_wavelength','units','wavelength_units'):del tags[key]
                dst.update_tags(j,**tags,wavelength_um=format(float(wl),'.17g'),wavelength_units='um',source_band_index_base1=str(int(i)+1))
                dst.set_band_description(j,f'{wl:.9f} um')
            for _,window in src.block_windows(1):
                data=src.read((original_indices+1).tolist(),window=window,masked=True).astype(np.float32).filled(np.nan)
                scales=np.array(src.scales)[original_indices,None,None];offsets=np.array(src.offsets)[original_indices,None,None]
                dst.write((data*scales+offsets).astype(np.float32),window=window)
    try:rio_copy(tmp,output,driver='COG',COMPRESS='DEFLATE',BLOCKSIZE=256,OVERVIEW_RESAMPLING='AVERAGE')
    finally:tmp.unlink(missing_ok=True)


def assert_alignment(image, excel, wavelength_file, expected):
    with rasterio.open(image) as src:
        image_wl=np.array([float(src.tags(b)['wavelength_um']) for b in range(1,src.count+1)])
    df=pd.read_excel(excel);end_wl=df.iloc[:,0].to_numpy(float);txt=np.loadtxt(wavelength_file,ndmin=1)
    for label,values in [('image',image_wl),('endmembers',end_wl),('text',txt)]:
        if values.shape!=np.asarray(expected).shape or not np.allclose(values,expected,rtol=0,atol=1e-12):raise ValueError(f'{label} wavelengths do not align.')
    if df.shape[1]<3 or not np.all(np.isfinite(df.iloc[:,1:].to_numpy(float))):raise ValueError('Invalid FCLS endmember matrix.')
    return True


def write_json(path,value):
    def clean(x):
        if isinstance(x,np.ndarray):return clean(x.tolist())
        if isinstance(x,np.generic):return clean(x.item())
        if isinstance(x,float) and not math.isfinite(x):return None
        if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
        if isinstance(x,(list,tuple)):return [clean(v) for v in x]
        return x
    Path(path).write_text(json.dumps(clean(value),indent=2,allow_nan=False)+'\n')


def resolve_stac(directory,asset_key=None):
    """Resolve a single staged Item/COG, with relative hrefs anchored to the Item."""
    import pystac
    obj=pystac.read_file(str(Path(directory)/'catalog.json'))
    items=[obj] if isinstance(obj,pystac.Item) else list(obj.get_all_items())
    if len(items)!=1:raise ValueError('Input STAC must contain exactly one item.')
    item=items[0]
    assets=[a for key,a in item.assets.items() if (key==asset_key if asset_key else a.media_type==pystac.MediaType.COG)]
    if len(assets)!=1:raise ValueError('Select exactly one COG asset with --asset-key if needed.')
    href=assets[0].get_absolute_href()
    if not href or '://' in href:raise ValueError('EOAP requires locally staged input assets.')
    return Path(href),item


def write_stac(out,image,wl,acquisition_datetime,source_item=None):
    import pystac
    with rasterio.open(image) as src:
        bounds=transform_bounds(src.crs,'EPSG:4326',*src.bounds,densify_pts=21)
    l,b,r,t=bounds;geometry={'type':'Polygon','coordinates':[[[l,b],[r,b],[r,t],[l,t],[l,b]]]}
    if source_item is not None:
        dt=source_item.datetime
        temporal={k:source_item.properties[k] for k in ('start_datetime','end_datetime') if k in source_item.properties}
    else:
        if not acquisition_datetime:raise ValueError('Provide acquisition_datetime in config for non-STAC input; processing time is not acquisition time.')
        dt=datetime.fromisoformat(acquisition_datetime.replace('Z','+00:00'));temporal={}
        if dt.tzinfo is None:raise ValueError('Acquisition datetime needs a timezone.')
    item=pystac.Item('class-guided-mask3',geometry,list(bounds),dt,temporal)
    item.properties['heatwise:processor_version']=VERSION
    item.properties['heatwise:processed_at']=datetime.now(timezone.utc).isoformat()
    for path in sorted(out.rglob('*')):
        if not path.is_file() or path.name.endswith('.log') or path.name in ('catalog.json','item.json'):continue
        typ=pystac.MediaType.COG if path.suffix=='.tif' else ('application/json' if path.suffix=='.json' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if path.suffix=='.xlsx' else 'application/octet-stream' if path.suffix in ('.npz', '.npy') else 'text/csv' if path.suffix=='.csv' else 'text/plain')
        asset=pystac.Asset('./'+path.relative_to(out).as_posix(),media_type=typ,roles=['data' if path.suffix=='.tif' else 'metadata'])
        if path==image:asset.extra_fields['bands']=[{'name':f'band_{i+1}','eo:center_wavelength':float(w)} for i,w in enumerate(wl)]
        item.add_asset(path.relative_to(out).as_posix(),asset)
    catalog=pystac.Catalog('heatwise-class-guided','Scene-specific spectral preprocessing products.')
    catalog.add_item(item);catalog.set_self_href(str(out/'catalog.json'));item.set_self_href(str(out/'item.json'))
    catalog.make_all_asset_hrefs_relative();catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)


def load_config(path):
    # Defaults are executable-owned; no companion file required by the processor.
    cfg={'seed':42,'extraction':copy.deepcopy(Extraction.DEFAULTS),'matching':copy.deepcopy(Matching.DEFAULTS),'bands':copy.deepcopy(BandSelection.DEFAULTS),'vegetation_mode':'separate','vegetation_quota':30,'ndvi_max_delta_um':.04,'export_intermediates':True,'required_classes':[],'acquisition_datetime':None,'class_mapping':{}}
    updates=yaml.safe_load(Path(path).read_text()) if path else {}
    if updates is None:updates={}
    for k,v in updates.items():
        if k not in cfg:raise ValueError(f'Unknown configuration setting: {k}')
        if isinstance(cfg[k],dict):
            if k!='class_mapping' and set(v)-set(cfg[k]):raise ValueError(f'Unknown keys in {k}: {set(v)-set(cfg[k])}')
            cfg[k].update(v)
        else:cfg[k]=v
    return cfg


def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def run(image,gusl,out,cfg,wavelength_file=None,source_item=None):
    if source_item is None and not cfg['acquisition_datetime']:
        raise ValueError('Direct image input requires acquisition_datetime in config for STAC output.')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):raise ValueError('Output directory must be empty (prevents stale or mixed products).')
    write_json(out/'effective_config.json',cfg)
    cube,wl,original_order,profile=read_image(image,wavelength_file)
    candidates,usable,strata=extract_candidates(cube,wl,cfg)
    scene=np.stack([c['spectrum'] for c in candidates]);wl_use=wl[usable];orig=original_order[usable]
    names=[f'CAND_{i+1:03d}' for i in range(len(candidates))]
    diagnostics=out/'diagnostics';diagnostics.mkdir()
    pd.DataFrame([{k:v for k,v in c.items() if k!='spectrum'}|{'candidate':name} for c,name in zip(candidates,names)]).to_csv(diagnostics/'candidates.csv',index=False)
    if cfg['export_intermediates']:
        np.savez_compressed(diagnostics/'candidates.npz',spectra=scene,wavelengths_um=wl_use,original_indices_base0=orig,**strata)
    matcher=Matching(cfg['matching']);libraries=matcher.read_multiple_gusl_sheets(gusl,matcher.GUSL_SHEETS)
    lib=[];lnames=[]
    for entry in libraries:
        if np.max(entry['wl'])>50:raise ValueError('GUSL wavelengths must be in micrometers; convert the source explicitly.')
        lib.append(matcher.pchip_library_to_target_grid(entry['wl'],entry['X'],wl_use));lnames.extend(entry['names'])
    lib=np.vstack(lib)
    full,common=match_candidates(matcher,scene,wl_use,names,lib,lnames,'FULL',diagnostics,cfg['export_intermediates'])
    pd.DataFrame({'wavelength_um':wl_use,**full}).to_excel(out/'Endmembers_FULL.xlsx',index=False)
       # Endmembers are selected exclusively using FULL spectral matching.
    # Band selection is performed independently and does not alter endmembers.
    final = full

    selected, details = select_bands(
        final, wl_use, common, cfg, out
    )
    groups=infer_groups(list(final),matcher.FINAL_TARGET_CLASSES,cfg['class_mapping'])
    missing=set(cfg['required_classes'])-set(groups)
    if missing:
        raise ValueError(
            f'Required material classes missing after FULL: {sorted(missing)}'
        )
    selected_wl=wl_use[selected]
    excel=out/'EndmembersFinales_mask3.xlsx';image_out=out/'hyperspectral_mask3_COG.tif';txt=out/'mask3_wavelengths_um.txt'
    pd.DataFrame({'wavelength_um':selected_wl,**final}).to_excel(excel,index=False,sheet_name='endmembers')
    np.savetxt(txt,selected_wl,fmt='%.17g')
    write_reduced_cog(image,image_out,orig[selected],selected_wl)
    assert_alignment(image_out,excel,txt,selected_wl)
    details.update(wavelengths_um=selected_wl.tolist(),original_band_indices_base0=orig[selected].tolist(),original_band_indices_base1=(orig[selected]+1).tolist(),full_metric_original_indices_base0=orig[common].tolist(),selected_full_grid_indices_base0=selected.tolist(),seed=cfg['seed'],configuration=cfg['bands'],mask3_reselection=True)
    write_json(out/'selected_bands.json',details)
    write_json(out/'endmember_classes.json',{'classes':groups,'note':'FCLS output bands correspond to individual endmembers; material abundances require summing bundle members.'})
    summary={'version':VERSION,'status':'success','input_sha256':{'image':sha256(image),'gusl':sha256(gusl)},'versions':{p:importlib.metadata.version(p) for p in ['numpy','scipy','pandas','rasterio','scikit-learn','openpyxl','pystac']},'python':sys.version,'gdal':rasterio.__gdal_version__,'candidate_count':len(candidates),'usable_image_bands':int(usable.sum()),'full_metric_bands':int(common.sum()),'selected_bands':len(selected),'final_endmembers':list(final),'missing_target_classes':sorted(set(matcher.FINAL_TARGET_CLASSES)-set(groups)),'alignment_verified':True,'band_selection_method':details['method'],'scientific_accuracy_validated':False}
    summary['input_band_count'] = int(len(wl))
    write_json(out/'unmixing_inputs.json', {
        'consumer': 'ESA-Heatwise/heatwise-hysupp-unmixing',
        'input_image': image_out.name,
        'endmembers': excel.name,
        'wavelengths_txt': txt.name,
        'scale_factor': 1.0,
        'image_axis_order': ['bands', 'rows', 'columns'],
        'endmember_axis_order': ['wavelength_rows', 'endmember_columns'],
        'spectral_bands': len(selected),
        'endmember_names': list(final),
        'wavelengths_um': selected_wl.tolist(),
        'alignment_verified': True,
        'unmixing_executed': False,
        'note': 'Paths are relative to this JSON. Official processor accepts GeoTIFF and XLSX/CSV, not MAT endmembers.'
    })
    write_json(out/'run_summary.json',summary)
    write_stac(out,image_out,selected_wl,cfg['acquisition_datetime'],source_item)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True);group.add_argument('--image',type=Path);group.add_argument('--input-catalog',type=Path)
    p.add_argument('--asset-key');p.add_argument('--gusl',required=True,type=Path);p.add_argument('--config',type=Path);p.add_argument('--output-dir',required=True,type=Path);p.add_argument('--wavelengths',type=Path);p.add_argument('--seed',type=int)
    for flag in ['preselect-top-bands','bands-per-combo','n-random-combinations','top-n-combinations','n-final-bands']:p.add_argument('--'+flag,type=int)
    p.add_argument('--min-spacing-um',type=float)
    args=p.parse_args();cfg=load_config(args.config)
    if args.seed is not None:cfg['seed']=args.seed
    for name in ['preselect_top_bands','bands_per_combo','n_random_combinations','top_n_combinations','n_final_bands','min_spacing_um']:
        value=getattr(args,name)
        if value is not None:cfg['bands'][name.upper()]=value
    source=None;image=args.image
    if args.input_catalog:image,source=resolve_stac(args.input_catalog,args.asset_key)
    try:
        summary=run(image,args.gusl,args.output_dir,cfg,args.wavelengths,source)
        print(json.dumps(summary,indent=2))
    except Exception as exc:
        logging.exception('Processing failed: %s',exc)
        return 1
    return 0

if __name__=='__main__':
    sys.exit(main())
