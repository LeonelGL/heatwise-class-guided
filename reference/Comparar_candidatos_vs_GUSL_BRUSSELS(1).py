##!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Comparar_candidatos_vs_GUSL_ALL_PCHIP_NO_EXTRAP_FULL_SEPOLIA.py

Workflow:
- Lee candidatos espectrales extraídos desde Sepolia.
- Lee firmas GUSL desde dos hojas:
    BRUSSELS_APEX_GENLIB
    DLR
- Interpola Brussels + DLR a la grilla espectral de Sepolia usando PCHIP sin extrapolación.
- Compara candidatos vs GUSL usando:
    SAM
    MBDSA
- Guarda:
    matriz SAM
    matriz MBDSA
    top matches por candidato
    mejor match por candidato
    resumen por clase
    candidatos usados para promedio
    endmembers finales promediados
    GUSL remuestreada
- Ejecuta análisis FULL y MASK3.
- No genera gráficos.

Cambios principales:
1) TOP_X_MATERIALS_FOR_AVERAGE ahora se aplica efectivamente.
   Para cada clase final se promedian solo los TOP X candidatos mejor matcheados.

2) Se agrega MBDSA:
      MBDSA = (1 + MBD) * (1 + sin(SAM_rad)) - 1

   donde MBD es una diferencia relativa de brillo medio:
      MBD = |mean(x) - mean(e)| / (mean(x) + mean(e) + eps)

   Esto penaliza casos donde dos espectros tienen forma parecida
   pero distinto nivel de reflectancia.

3) El ranking de matches se controla con MATCH_RANK_METRIC:
      "mbdsa" -> ranking por MBDSA
      "sam"   -> ranking por SAM

4) Esta versión NO extrapola las firmas GUSL.
   Fuera del rango espectral real de cada firma se conservan NaN,
   y las métricas se calculan únicamente con las bandas finitas comunes.
"""

import re
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from scipy.interpolate import PchipInterpolator


# =============================================================================
# CONFIG
# =============================================================================

CANDIDATES_XLSX = Path(
    r"C:\Users\Gateway\Desktop\PaviaPosition\Resultados\EndmemberCandidates\Sepolia_urban\Sepolia_urban_scene_candidates.xlsx"
)

GUSL_XLSX = Path(
    r"C:\Users\Gateway\Desktop\PaviaPosition\GUSL\spectra_material_headers\GUSL_spectra_by_material_headers.xlsx"
)

OUTPUT_DIR = Path(
    r"C:\Users\Gateway\Desktop\PaviaPosition\GUSL\Sepolia_urban\GUSL_ALL_comparison_PCHIP_NO_EXTRAP_FULL_SEPOLIA"
)

CANDIDATE_SHEET = "urban_scene_candidates"

GUSL_SHEETS = [
    "BRUSSELS_APEX_GENLIB",
    "DLR",
]

TOP_K = 50

# =============================================================================
# PARÁMETRO PRINCIPAL PARA EL PROMEDIO FINAL
# =============================================================================
# Número máximo de candidatos/materiales usados para promediar el endmember
# final de cada clase.
#
# Ejemplos:
#   TOP_X_MATERIALS_FOR_AVERAGE = 1  -> usa solo el mejor candidato por clase
#   TOP_X_MATERIALS_FOR_AVERAGE = 3  -> usa los 3 mejores candidatos por clase
#   TOP_X_MATERIALS_FOR_AVERAGE = 5  -> usa los 5 mejores candidatos por clase
#
# Si una clase tiene menos candidatos válidos que este número, usa todos los
# disponibles.
# =============================================================================

TOP_X_MATERIALS_FOR_AVERAGE = 3


# =============================================================================
# MÉTRICA PRINCIPAL PARA RANKING
# =============================================================================
# "mbdsa" -> usa MBDSA para ordenar mejores matches y seleccionar TOP X
# "sam"   -> usa SAM para ordenar mejores matches y seleccionar TOP X
# =============================================================================

MATCH_RANK_METRIC = "mbdsa"

# =============================================================================
# MÉTRICA PARA ASIGNACIÓN DE CLASE
# =============================================================================
# "sam"   -> usa SAM para decidir la clase ganadora del candidato
# "mbdsa" -> usa MBDSA para decidir la clase ganadora del candidato
#
# En esta versión:
#   - SAM decide la clase: asphalt_road, concrete, metal, etc.
#   - MATCH_RANK_METRIC sigue decidiendo el ranking dentro de cada clase.
# =============================================================================

CLASS_ASSIGNMENT_METRIC = "sam"


TARGET_CLASS_PREFIXES = {
    "asphalt_road": ["Asphalt"],
    "concrete": ["Concrete"],
    "metal": ["Metal", "Roof", "Zinc"],
    "terracota": ["Terracotta", "Clay", "Tile"],
    "vegetation": ["Vegetation"],

    # Auxiliares: compiten durante la asignación, pero no se guardan como
    # endmembers finales principales.
    "bitumen_aux": ["Bitumen"],
    "soil_aux": ["Soil"],
    "water_aux": ["Water"],
}

FINAL_TARGET_CLASSES = [
    "asphalt_road",
    "concrete",
    "metal",
    "terracota",
    "vegetation",
]


# =============================================================================
# UMBRALES OPCIONALES DE ACEPTACIÓN
# =============================================================================
# Si USE_ACCEPTANCE_THRESHOLDS = False:
#   todo candidato cuyo best_target_class sea una clase entra como candidato
#   disponible para el TOP X.
#
# Si USE_ACCEPTANCE_THRESHOLDS = True:
#   se aplican umbrales sobre SAM, MBDSA y margen.
#
# Los umbrales se aplican según la métrica principal definida en
# MATCH_RANK_METRIC, pero se guardan ambas métricas en los outputs.
# =============================================================================

USE_ACCEPTANCE_THRESHOLDS = False

MAX_ACCEPTED_SAM_DEG = 8.0
MAX_ACCEPTED_MBDSA = 0.12

MIN_MARGIN_TO_2ND_SAM_DEG = 1.0
MIN_MARGIN_TO_2ND_MBDSA = 0.01


# =============================================================================
# SALIDA EXTRA: 3 ASFALTOS + 3 CONCRETOS
# =============================================================================
# Este bloque NO modifica los endmembers finales promediados ni los outputs
# existentes. Solo genera un Excel adicional con candidatos seleccionados
# explícitamente para asphalt_road y concrete.
#
# Criterio:
#   1) buen ajuste a su propia clase;
#   2) separación explícita contra la clase opuesta asphalt/concrete;
#   3) diversidad espectral controlada entre los tres candidatos elegidos.
# =============================================================================

ASPHALT_CONCRETE_X3_COUNT = 3
ASPHALT_CONCRETE_X3_FILENAME = "AsfaltosConcretosX3.xlsx"

# Excel final adicional con 3 asfaltos + 3 concretos + metal/terracota/vegetation
# Mantiene intactos todos los outputs anteriores y solo agrega:
#   EndmembersFinales.xlsx
#   EndmembersFinales_mask3.xlsx
FINAL_X9_FILENAME_BASE = "EndmembersFinales"

X3_WEIGHT_CLASS_SCORE = 0.50
X3_WEIGHT_PAIR_MARGIN = 0.35
X3_WEIGHT_DIVERSITY = 0.15


# =============================================================================
# MASK3
# =============================================================================

MASK3_TARGETS_UM = np.array([
    0.498, 0.538, 0.580, 0.640, 0.675, 0.740,
    0.846, 1.106, 1.290, 1.710, 2.180, 2.330
], dtype=np.float32)

MASK3_MAX_DELTA_UM = 0.020


# =============================================================================
# UTILIDADES
# =============================================================================

def normalize_name(s):
    s = str(s).strip()
    s = s.replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s)
    return s


def find_wavelength_column(columns):
    lower = [normalize_name(c).lower() for c in columns]

    preferred_patterns = [
        "wavelength_um",
        "wavelength",
        "wavelength [",
        "lambda",
        "wl",
        "longitud",
    ]

    for patt in preferred_patterns:
        for orig, low in zip(columns, lower):
            if patt in low:
                return orig

    return columns[0]


def read_spectral_library_excel(xlsx_path, preferred_sheet=None):
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

    sheet_name = preferred_sheet if (
        preferred_sheet is not None and preferred_sheet in xls.sheet_names
    ) else xls.sheet_names[0]

    df = pd.read_excel(xlsx_path, sheet_name=sheet_name)
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")

    wl_col = find_wavelength_column(df.columns)
    wl = pd.to_numeric(df[wl_col], errors="coerce").to_numpy(dtype=float)

    valid_rows = np.isfinite(wl)
    df = df.loc[valid_rows].copy()
    wl = wl[valid_rows]

    order = np.argsort(wl)
    wl = wl[order]
    df = df.iloc[order].reset_index(drop=True)

    spec_cols = [c for c in df.columns if c != wl_col]

    if len(spec_cols) == 0:
        raise ValueError(
            f"No encontré columnas espectrales en {xlsx_path}, hoja {sheet_name}"
        )

    X = []
    names = []

    for c in spec_cols:
        vals = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)

        if len(vals) == len(order):
            vals = vals[order]

        if np.all(~np.isfinite(vals)):
            continue

        X.append(vals)
        names.append(normalize_name(c))

    if len(X) == 0:
        raise ValueError(
            f"No encontré espectros válidos en {xlsx_path}, hoja {sheet_name}"
        )

    X = np.vstack(X)

    return wl.astype(np.float32), X.astype(np.float32), names, sheet_name, wl_col


def read_multiple_gusl_sheets(xlsx_path, sheet_names):
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
            raise ValueError(
                f"La hoja '{sheet}' no existe en {xlsx_path}. "
                f"Hojas disponibles: {available_sheets}"
            )

        wl, X, names, sheet_name, wl_col = read_spectral_library_excel(
            xlsx_path,
            preferred_sheet=sheet
        )

        names_with_source = [
            f"{name}__{sheet_name}"
            for name in names
        ]

        out.append({
            "sheet_name": sheet_name,
            "wl_col": wl_col,
            "wl": wl,
            "X": X,
            "names": names_with_source,
        })

    return out


def safe_mkdir(path):
    path.mkdir(parents=True, exist_ok=True)


def l2_normalize_rows(X, eps=1e-12):
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms = np.maximum(norms, eps)
    return X / norms


def pchip_library_to_target_grid(lib_wl, lib_X, target_wl):
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
            interpolator = PchipInterpolator(
                x_unique,
                y_unique,
                extrapolate=False
            )
            yi[inside] = interpolator(target_wl[inside])
        else:
            yi[inside] = np.interp(
                target_wl[inside],
                x_unique,
                y_unique
            )

        out[i, :] = yi.astype(np.float32)

    return out

# =============================================================================
# MÉTRICAS ESPECTRALES
# =============================================================================

def compute_similarity_matrices(scene_X, lib_X, eps=1e-12):
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
    valid_bands = (
        np.all(np.isfinite(scene_X), axis=0) &
        np.all(np.isfinite(lib_X), axis=0)
    )

    n_valid = int(np.sum(valid_bands))

    if n_valid < 2:
        raise RuntimeError(
            f"No hay suficientes bandas finitas para calcular métricas. "
            f"Bandas válidas: {n_valid}"
        )

    scene_valid = scene_X[:, valid_bands].astype(np.float64)
    lib_valid = lib_X[:, valid_bands].astype(np.float64)

    scene_n = l2_normalize_rows(scene_valid, eps=eps)
    lib_n = l2_normalize_rows(lib_valid, eps=eps)

    dots = np.clip(scene_n @ lib_n.T, -1.0, 1.0)

    sam_rad = np.arccos(dots)
    sam_deg = np.degrees(sam_rad)

    scene_mean = np.nanmean(scene_valid, axis=1, keepdims=True)
    lib_mean = np.nanmean(lib_valid, axis=1, keepdims=True).T

    mbd = np.abs(scene_mean - lib_mean) / (
        np.abs(scene_mean) + np.abs(lib_mean) + eps
    )

    mbdsa = (1.0 + mbd) * (1.0 + np.sin(sam_rad)) - 1.0

    return sam_deg.astype(np.float32), mbdsa.astype(np.float32), valid_bands


def get_rank_column():
    metric = str(MATCH_RANK_METRIC).strip().lower()

    if metric == "sam":
        return "sam_deg"

    if metric == "mbdsa":
        return "mbdsa"

    raise ValueError(
        f"MATCH_RANK_METRIC inválida: {MATCH_RANK_METRIC}. "
        "Usar 'sam' o 'mbdsa'."
    )


def get_metric_column(metric_name):
    metric = str(metric_name).strip().lower()

    if metric == "sam":
        return "sam_deg"

    if metric == "mbdsa":
        return "mbdsa"

    raise ValueError(
        f"Métrica inválida: {metric_name}. "
        "Usar 'sam' o 'mbdsa'."
    )


def build_mask3_mask(available_wl, mask3_targets_um, max_delta_um=0.020):
    """
    Selecciona, para cada target de MASK3, la banda más cercana
    en la grilla disponible si está dentro de la tolerancia.
    Evita duplicados.
    """
    available_wl = np.asarray(available_wl, dtype=float).ravel()
    mask = np.zeros(available_wl.size, dtype=bool)

    selected_info = []
    used_idx = set()

    for tgt in mask3_targets_um:
        j = int(np.argmin(np.abs(available_wl - tgt)))
        d = abs(float(available_wl[j]) - float(tgt))

        if d <= max_delta_um and j not in used_idx:
            used_idx.add(j)
            mask[j] = True
            selected_info.append(
                (float(tgt), float(available_wl[j]), float(d), int(j))
            )

    return mask, selected_info


def material_prefix_match(name, prefixes):
    n = normalize_name(name).lower()

    for p in prefixes:
        pp = normalize_name(p).lower()

        if n == pp:
            return True

        if n.startswith(pp + "_"):
            return True

        if n.startswith(pp + " "):
            return True

    return False


def summarize_candidates_by_target_class(df_top, target_class_prefixes):
    """
    Para cada candidato:
      - busca el mejor match dentro de cada clase objetivo usando la métrica
        definida por CLASS_ASSIGNMENT_METRIC;
      - determina la clase objetivo ganadora;
      - calcula margen respecto de la segunda clase.

    Retorna un DataFrame con una fila por candidato.
    """
    rank_col = get_metric_column(CLASS_ASSIGNMENT_METRIC)

    rows = []

    for cand, sub in df_top.groupby("candidate", sort=False):
        rec = {"candidate": cand}
        class_scores = []

        for cls, prefixes in target_class_prefixes.items():
            class_mask = sub["library_match"].apply(
                lambda x: material_prefix_match(x, prefixes)
            )

            s = sub[class_mask].sort_values(
                [rank_col, "rank"],
                ascending=[True, True]
            )

            if s.empty:
                rec[f"{cls}_match"] = None
                rec[f"{cls}_sam"] = np.nan
                rec[f"{cls}_mbdsa"] = np.nan
                rec[f"{cls}_score"] = np.nan
                rec[f"{cls}_rank"] = np.nan
            else:
                best = s.iloc[0]

                rec[f"{cls}_match"] = str(best["library_match"])
                rec[f"{cls}_sam"] = float(best["sam_deg"])
                rec[f"{cls}_mbdsa"] = float(best["mbdsa"])
                rec[f"{cls}_score"] = float(best[rank_col])
                rec[f"{cls}_rank"] = int(best["rank"])

                class_scores.append((
                    cls,
                    float(best[rank_col]),
                    float(best["sam_deg"]),
                    float(best["mbdsa"]),
                ))

        if len(class_scores) == 0:
            rec["best_target_class"] = None
            rec["best_target_score"] = np.nan
            rec["best_target_sam"] = np.nan
            rec["best_target_mbdsa"] = np.nan

            rec["second_target_class"] = None
            rec["second_target_score"] = np.nan
            rec["second_target_sam"] = np.nan
            rec["second_target_mbdsa"] = np.nan

            rec["margin_to_2nd_score"] = np.nan
            rec["margin_to_2nd_sam"] = np.nan
            rec["margin_to_2nd_mbdsa"] = np.nan
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

            rec["best_target_class"] = best_cls
            rec["best_target_score"] = best_score
            rec["best_target_sam"] = best_sam
            rec["best_target_mbdsa"] = best_mbdsa

            rec["second_target_class"] = second_cls
            rec["second_target_score"] = second_score
            rec["second_target_sam"] = second_sam
            rec["second_target_mbdsa"] = second_mbdsa

            rec["margin_to_2nd_score"] = (
                second_score - best_score
                if pd.notna(second_score)
                else np.nan
            )
            rec["margin_to_2nd_sam"] = (
                second_sam - best_sam
                if pd.notna(second_sam)
                else np.nan
            )
            rec["margin_to_2nd_mbdsa"] = (
                second_mbdsa - best_mbdsa
                if pd.notna(second_mbdsa)
                else np.nan
            )

        rows.append(rec)

    return pd.DataFrame(rows)


def add_acceptance_flags(df_summary):
    """
    Agrega columnas:
        accepted_by_thresholds
        acceptance_reason

    Si USE_ACCEPTANCE_THRESHOLDS=False, marca True para todo candidato con clase.
    """
    df = df_summary.copy()
    metric = str(MATCH_RANK_METRIC).strip().lower()

    accepted = []
    reasons = []

    for _, row in df.iterrows():
        best_cls = row.get("best_target_class", None)

        best_sam = row.get("best_target_sam", np.nan)
        best_mbdsa = row.get("best_target_mbdsa", np.nan)

        margin_sam = row.get("margin_to_2nd_sam", np.nan)
        margin_mbdsa = row.get("margin_to_2nd_mbdsa", np.nan)

        if best_cls is None or pd.isna(best_cls):
            accepted.append(False)
            reasons.append("NO_TARGET_CLASS")
            continue

        if not USE_ACCEPTANCE_THRESHOLDS:
            accepted.append(True)
            reasons.append("ACCEPTED_NO_THRESHOLDS")
            continue

        if pd.isna(best_sam):
            accepted.append(False)
            reasons.append("NO_BEST_SAM")
            continue

        if pd.isna(best_mbdsa):
            accepted.append(False)
            reasons.append("NO_BEST_MBDSA")
            continue

        if best_sam > MAX_ACCEPTED_SAM_DEG:
            accepted.append(False)
            reasons.append(f"SAM_TOO_HIGH>{MAX_ACCEPTED_SAM_DEG}")
            continue

        if best_mbdsa > MAX_ACCEPTED_MBDSA:
            accepted.append(False)
            reasons.append(f"MBDSA_TOO_HIGH>{MAX_ACCEPTED_MBDSA}")
            continue

        if metric == "sam":
            if pd.isna(margin_sam):
                accepted.append(False)
                reasons.append("NO_SAM_MARGIN")
                continue

            if margin_sam < MIN_MARGIN_TO_2ND_SAM_DEG:
                accepted.append(False)
                reasons.append(f"SAM_MARGIN_TOO_LOW<{MIN_MARGIN_TO_2ND_SAM_DEG}")
                continue

        elif metric == "mbdsa":
            if pd.isna(margin_mbdsa):
                accepted.append(False)
                reasons.append("NO_MBDSA_MARGIN")
                continue

            if margin_mbdsa < MIN_MARGIN_TO_2ND_MBDSA:
                accepted.append(False)
                reasons.append(f"MBDSA_MARGIN_TOO_LOW<{MIN_MARGIN_TO_2ND_MBDSA}")
                continue

        accepted.append(True)
        reasons.append("ACCEPTED_BY_THRESHOLDS")

    df["accepted_by_thresholds"] = accepted
    df["acceptance_reason"] = reasons

    return df


# =============================================================================
# ENDMEMBERS FINALES PROMEDIADOS
# =============================================================================

def collect_candidates_for_class_average(
    df_summary,
    scene_names,
    scene_full_for_average,
    final_target_classes,
    top_x_for_average,
):
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

    metric = str(MATCH_RANK_METRIC).strip().lower()

    if metric == "sam":
        sort_col = None
        sort_col_suffix = "sam"
        margin_col = "margin_to_2nd_sam"
    elif metric == "mbdsa":
        sort_col = None
        sort_col_suffix = "mbdsa"
        margin_col = "margin_to_2nd_mbdsa"
    else:
        raise ValueError(
            f"MATCH_RANK_METRIC inválida: {MATCH_RANK_METRIC}. "
            "Usar 'sam' o 'mbdsa'."
        )

    rows_summary = []
    rows_used = []
    averaged_endmembers = {}

    top_x_for_average = int(top_x_for_average)

    if top_x_for_average < 1:
        raise ValueError(
            f"top_x_for_average debe ser >= 1. "
            f"Valor recibido: {top_x_for_average}"
        )

    for cls in final_target_classes:
        class_sam_col = f"{cls}_sam"
        class_mbdsa_col = f"{cls}_mbdsa"
        class_score_col = f"{cls}_score"
        match_col = f"{cls}_match"

        if metric == "sam":
            sort_col = class_sam_col
        else:
            sort_col = class_mbdsa_col

        if sort_col not in df_summary.columns:
            valid = pd.DataFrame()
        else:
            valid = df_summary[
                (df_summary["best_target_class"] == cls) &
                (df_summary[sort_col].notna()) &
                (df_summary["accepted_by_thresholds"] == True)
            ].copy()

        if not valid.empty:
            valid = valid.sort_values(
                by=[sort_col, margin_col, "candidate"],
                ascending=[True, False, True]
            ).reset_index(drop=True)

            # ================================================================
            # CAMBIO PRINCIPAL REAL:
            # acá se corta la lista y solo se usan los TOP X.
            # ================================================================
            valid_for_average = valid.head(top_x_for_average).copy()
        else:
            valid_for_average = pd.DataFrame()

        if valid_for_average.empty:
            averaged_endmembers[cls] = np.full(
                scene_full_for_average.shape[1],
                np.nan,
                dtype=np.float32
            )

            rows_summary.append({
                "class_name": cls,
                "ranking_metric": metric,
                "top_x_requested": top_x_for_average,
                "n_candidates_available": int(len(valid)),
                "n_candidates_used": 0,
                "mean_class_sam_deg": np.nan,
                "best_class_sam_deg": np.nan,
                "mean_class_mbdsa": np.nan,
                "best_class_mbdsa": np.nan,
                "mean_class_score": np.nan,
                "best_class_score": np.nan,
                "mean_margin_to_2nd_sam_deg": np.nan,
                "mean_margin_to_2nd_mbdsa": np.nan,
                "candidates_used": None,
                "matches_used": None,
                "status": "NO_VALID_CANDIDATE",
            })
            continue

        idxs = []
        cand_names = []
        match_names = []

        for _, row in valid_for_average.iterrows():
            cand = str(row["candidate"])

            if cand not in name_to_idx:
                continue

            idxs.append(name_to_idx[cand])
            cand_names.append(cand)
            match_names.append(
                str(row[match_col]) if pd.notna(row[match_col]) else ""
            )

            rows_used.append({
                "class_name": cls,
                "ranking_metric": metric,
                "top_x_requested": top_x_for_average,
                "candidate": cand,
                "class_match": row[match_col],
                "class_sam_deg": (
                    float(row[class_sam_col])
                    if pd.notna(row[class_sam_col])
                    else np.nan
                ),
                "class_mbdsa": (
                    float(row[class_mbdsa_col])
                    if pd.notna(row[class_mbdsa_col])
                    else np.nan
                ),
                "class_score": (
                    float(row[class_score_col])
                    if pd.notna(row[class_score_col])
                    else np.nan
                ),
                "best_target_class": row["best_target_class"],
                "best_target_score": (
                    float(row["best_target_score"])
                    if pd.notna(row["best_target_score"])
                    else np.nan
                ),
                "best_target_sam_deg": (
                    float(row["best_target_sam"])
                    if pd.notna(row["best_target_sam"])
                    else np.nan
                ),
                "best_target_mbdsa": (
                    float(row["best_target_mbdsa"])
                    if pd.notna(row["best_target_mbdsa"])
                    else np.nan
                ),
                "second_target_class": row["second_target_class"],
                "second_target_score": (
                    float(row["second_target_score"])
                    if pd.notna(row["second_target_score"])
                    else np.nan
                ),
                "second_target_sam_deg": (
                    float(row["second_target_sam"])
                    if pd.notna(row["second_target_sam"])
                    else np.nan
                ),
                "second_target_mbdsa": (
                    float(row["second_target_mbdsa"])
                    if pd.notna(row["second_target_mbdsa"])
                    else np.nan
                ),
                "margin_to_2nd_score": (
                    float(row["margin_to_2nd_score"])
                    if pd.notna(row["margin_to_2nd_score"])
                    else np.nan
                ),
                "margin_to_2nd_sam_deg": (
                    float(row["margin_to_2nd_sam"])
                    if pd.notna(row["margin_to_2nd_sam"])
                    else np.nan
                ),
                "margin_to_2nd_mbdsa": (
                    float(row["margin_to_2nd_mbdsa"])
                    if pd.notna(row["margin_to_2nd_mbdsa"])
                    else np.nan
                ),
                "acceptance_reason": row.get("acceptance_reason", ""),
            })

        if len(idxs) == 0:
            averaged_endmembers[cls] = np.full(
                scene_full_for_average.shape[1],
                np.nan,
                dtype=np.float32
            )

            rows_summary.append({
                "class_name": cls,
                "ranking_metric": metric,
                "top_x_requested": top_x_for_average,
                "n_candidates_available": int(len(valid)),
                "n_candidates_used": 0,
                "mean_class_sam_deg": np.nan,
                "best_class_sam_deg": np.nan,
                "mean_class_mbdsa": np.nan,
                "best_class_mbdsa": np.nan,
                "mean_class_score": np.nan,
                "best_class_score": np.nan,
                "mean_margin_to_2nd_sam_deg": np.nan,
                "mean_margin_to_2nd_mbdsa": np.nan,
                "candidates_used": None,
                "matches_used": None,
                "status": "NO_VALID_CANDIDATE_IN_SCENE_NAMES",
            })
            continue

        spectra = scene_full_for_average[idxs, :]
        avg_spec = np.nanmean(spectra, axis=0).astype(np.float32)
        averaged_endmembers[cls] = avg_spec

        rows_summary.append({
            "class_name": cls,
            "ranking_metric": metric,
            "top_x_requested": top_x_for_average,
            "n_candidates_available": int(len(valid)),
            "n_candidates_used": len(idxs),
            "mean_class_sam_deg": float(
                np.nanmean(valid_for_average[class_sam_col].to_numpy(dtype=float))
            ),
            "best_class_sam_deg": float(
                np.nanmin(valid_for_average[class_sam_col].to_numpy(dtype=float))
            ),
            "mean_class_mbdsa": float(
                np.nanmean(valid_for_average[class_mbdsa_col].to_numpy(dtype=float))
            ),
            "best_class_mbdsa": float(
                np.nanmin(valid_for_average[class_mbdsa_col].to_numpy(dtype=float))
            ),
            "mean_class_score": float(
                np.nanmean(valid_for_average[class_score_col].to_numpy(dtype=float))
            ),
            "best_class_score": float(
                np.nanmin(valid_for_average[class_score_col].to_numpy(dtype=float))
            ),
            "mean_margin_to_2nd_sam_deg": float(
                np.nanmean(valid_for_average["margin_to_2nd_sam"].to_numpy(dtype=float))
            ),
            "mean_margin_to_2nd_mbdsa": float(
                np.nanmean(valid_for_average["margin_to_2nd_mbdsa"].to_numpy(dtype=float))
            ),
            "candidates_used": "; ".join(cand_names),
            "matches_used": "; ".join(match_names),
            "status": "OK",
        })

    df_avg_summary = pd.DataFrame(rows_summary)
    df_used = pd.DataFrame(rows_used)

    return df_avg_summary, df_used, averaged_endmembers


def print_average_summary(df_avg_summary, title="Resumen de endmembers promediados"):
    print("\n======================")
    print(title)
    print("======================")

    for _, row in df_avg_summary.iterrows():
        cls = row["class_name"]

        n_used = (
            int(row["n_candidates_used"])
            if pd.notna(row["n_candidates_used"])
            else 0
        )

        n_available = (
            int(row["n_candidates_available"])
            if "n_candidates_available" in row and pd.notna(row["n_candidates_available"])
            else n_used
        )

        top_x = (
            int(row["top_x_requested"])
            if "top_x_requested" in row and pd.notna(row["top_x_requested"])
            else np.nan
        )

        metric = row.get("ranking_metric", MATCH_RANK_METRIC)
        mean_sam = row["mean_class_sam_deg"]
        best_sam = row["best_class_sam_deg"]
        mean_mbdsa = row["mean_class_mbdsa"]
        best_mbdsa = row["best_class_mbdsa"]
        status = row["status"]

        if status != "OK" or n_used == 0:
            print(f"- {cls}: SIN CANDIDATOS VÁLIDOS PARA EL PROMEDIO")
        else:
            print(
                f"- {cls}: promedio con {n_used} candidato(s) "
                f"de {n_available} disponible(s) "
                f"(TOP_X={top_x}, ranking={metric}) | "
                f"mean_SAM={mean_sam:.2f}° | "
                f"best_SAM={best_sam:.2f}° | "
                f"mean_MBDSA={mean_mbdsa:.5f} | "
                f"best_MBDSA={best_mbdsa:.5f}"
            )

    print("======================")


def save_averaged_endmembers_excel(
    xlsx_path,
    wavelength_um,
    averaged_endmembers,
    df_avg_summary,
    df_used,
):
    df_endm = pd.DataFrame({"wavelength_um": wavelength_um})

    for cls, spec in averaged_endmembers.items():
        df_endm[cls] = spec

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df_endm.to_excel(writer, index=False, sheet_name="averaged_endmembers")
        df_avg_summary.to_excel(writer, index=False, sheet_name="average_summary")
        df_used.to_excel(writer, index=False, sheet_name="candidates_used")


# =============================================================================
# SALIDA EXTRA: 3 ASFALTOS + 3 CONCRETOS
# =============================================================================

def _normalize_cost(values):
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


def _normalize_benefit(values):
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


def _sam_between_spectra_deg(x, y, eps=1e-12):
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


def _add_pairwise_asphalt_concrete_margins(df_summary):
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

    required = [
        "asphalt_road_sam",
        "concrete_sam",
        "asphalt_road_mbdsa",
        "concrete_mbdsa",
        "asphalt_road_score",
        "concrete_score",
    ]

    for col in required:
        if col not in df.columns:
            df[col] = np.nan

    df["margin_asphalt_vs_concrete_sam"] = (
        df["concrete_sam"] - df["asphalt_road_sam"]
    )
    df["margin_asphalt_vs_concrete_mbdsa"] = (
        df["concrete_mbdsa"] - df["asphalt_road_mbdsa"]
    )
    df["margin_asphalt_vs_concrete_score"] = (
        df["concrete_score"] - df["asphalt_road_score"]
    )

    df["margin_concrete_vs_asphalt_sam"] = (
        df["asphalt_road_sam"] - df["concrete_sam"]
    )
    df["margin_concrete_vs_asphalt_mbdsa"] = (
        df["asphalt_road_mbdsa"] - df["concrete_mbdsa"]
    )
    df["margin_concrete_vs_asphalt_score"] = (
        df["asphalt_road_score"] - df["concrete_score"]
    )

    return df


def _fill_missing_pair_margin_for_ranking(margins):
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


def select_asphalt_concrete_x3(
    mode_name,
    df_summary,
    scene_names,
    scene_cmp,
    scene_full_for_average,
    wavelength_um,
    top_n=3,
):
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
    metric = str(MATCH_RANK_METRIC).strip().lower()

    if metric == "sam":
        metric_suffix = "sam"
    elif metric == "mbdsa":
        metric_suffix = "mbdsa"
    else:
        raise ValueError(
            f"MATCH_RANK_METRIC inválida: {MATCH_RANK_METRIC}. "
            "Usar 'sam' o 'mbdsa'."
        )

    df = _add_pairwise_asphalt_concrete_margins(df_summary)
    name_to_idx = {name: i for i, name in enumerate(scene_names)}

    selection_rows = []
    selected_for_spectra = []

    selection_plan = [
        {
            "class_name": "asphalt_road",
            "opponent_class": "concrete",
            "pair_margin_sam_col": "margin_asphalt_vs_concrete_sam",
            "pair_margin_mbdsa_col": "margin_asphalt_vs_concrete_mbdsa",
            "pair_margin_score_col": "margin_asphalt_vs_concrete_score",
        },
        {
            "class_name": "concrete",
            "opponent_class": "asphalt_road",
            "pair_margin_sam_col": "margin_concrete_vs_asphalt_sam",
            "pair_margin_mbdsa_col": "margin_concrete_vs_asphalt_mbdsa",
            "pair_margin_score_col": "margin_concrete_vs_asphalt_score",
        },
    ]

    for plan in selection_plan:
        cls = plan["class_name"]
        opponent = plan["opponent_class"]

        class_sam_col = f"{cls}_sam"
        class_mbdsa_col = f"{cls}_mbdsa"
        class_score_col = f"{cls}_score"
        class_match_col = f"{cls}_match"

        opponent_sam_col = f"{opponent}_sam"
        opponent_mbdsa_col = f"{opponent}_mbdsa"
        opponent_score_col = f"{opponent}_score"
        opponent_match_col = f"{opponent}_match"

        if metric_suffix == "sam":
            class_metric_col = class_sam_col
            pair_margin_metric_col = plan["pair_margin_sam_col"]
        else:
            class_metric_col = class_mbdsa_col
            pair_margin_metric_col = plan["pair_margin_mbdsa_col"]

        needed_cols = [
            "candidate",
            "best_target_class",
            "accepted_by_thresholds",
            class_metric_col,
        ]

        missing_cols = [c for c in needed_cols if c not in df.columns]

        if missing_cols:
            continue

        valid = df[
            (df["best_target_class"] == cls) &
            (df["accepted_by_thresholds"] == True) &
            (df[class_metric_col].notna())
        ].copy()

        valid = valid[
            valid["candidate"].apply(lambda x: str(x) in name_to_idx)
        ].copy()

        if valid.empty:
            continue

        valid = valid.reset_index(drop=True)

        quality_values = valid[class_metric_col].to_numpy(dtype=float)
        pair_margin_values = _fill_missing_pair_margin_for_ranking(
            valid[pair_margin_metric_col].to_numpy(dtype=float)
        )

        quality_cost_all = _normalize_cost(quality_values)
        pair_margin_benefit_all = _normalize_benefit(pair_margin_values)

        selected_positions = []

        while len(selected_positions) < int(top_n):
            remaining_positions = [
                i for i in range(len(valid))
                if i not in selected_positions
            ]

            if len(remaining_positions) == 0:
                break

            quality_cost = quality_cost_all[remaining_positions]
            pair_margin_benefit = pair_margin_benefit_all[remaining_positions]

            if len(selected_positions) == 0:
                diversity_benefit = np.ones(len(remaining_positions), dtype=float)

                # Primera elección: calidad propia + separación explícita
                selection_score = (
                    0.60 * quality_cost +
                    0.40 * (1.0 - pair_margin_benefit)
                )
            else:
                diversity_values = []

                selected_candidate_indices = [
                    name_to_idx[str(valid.loc[pos, "candidate"])]
                    for pos in selected_positions
                ]

                for pos in remaining_positions:
                    cand_idx = name_to_idx[str(valid.loc[pos, "candidate"])]

                    dists = [
                        _sam_between_spectra_deg(
                            scene_cmp[cand_idx, :],
                            scene_cmp[sel_idx, :]
                        )
                        for sel_idx in selected_candidate_indices
                    ]

                    if np.any(np.isfinite(dists)):
                        diversity_values.append(float(np.nanmin(dists)))
                    else:
                        diversity_values.append(np.nan)

                diversity_benefit = _normalize_benefit(diversity_values)

                # Siguientes elecciones: calidad + separación + diversidad interna
                selection_score = (
                    X3_WEIGHT_CLASS_SCORE * quality_cost +
                    X3_WEIGHT_PAIR_MARGIN * (1.0 - pair_margin_benefit) +
                    X3_WEIGHT_DIVERSITY * (1.0 - diversity_benefit)
                )

            order = np.lexsort((
                valid.loc[remaining_positions, "candidate"].astype(str).to_numpy(),
                selection_score,
            ))

            chosen_local = int(order[0])
            chosen_pos = int(remaining_positions[chosen_local])
            selected_positions.append(chosen_pos)

            row = valid.loc[chosen_pos].copy()
            cand = str(row["candidate"])
            cand_idx = name_to_idx[cand]

            selected_for_spectra.append({
                "mode": mode_name,
                "class_name": cls,
                "x3_rank": len(selected_positions),
                "candidate": cand,
                "scene_index": cand_idx,
            })

            selection_rows.append({
                "mode": mode_name,
                "class_name": cls,
                "opponent_class": opponent,
                "x3_rank": len(selected_positions),
                "candidate": cand,
                "selection_score": float(selection_score[chosen_local]),
                "ranking_metric": metric,
                "class_match": (
                    str(row[class_match_col])
                    if class_match_col in row and pd.notna(row[class_match_col])
                    else ""
                ),
                "opponent_match": (
                    str(row[opponent_match_col])
                    if opponent_match_col in row and pd.notna(row[opponent_match_col])
                    else ""
                ),
                "class_sam_deg": (
                    float(row[class_sam_col])
                    if class_sam_col in row and pd.notna(row[class_sam_col])
                    else np.nan
                ),
                "opponent_sam_deg": (
                    float(row[opponent_sam_col])
                    if opponent_sam_col in row and pd.notna(row[opponent_sam_col])
                    else np.nan
                ),
                "margin_vs_opponent_sam_deg": (
                    float(row[plan["pair_margin_sam_col"]])
                    if plan["pair_margin_sam_col"] in row and pd.notna(row[plan["pair_margin_sam_col"]])
                    else np.nan
                ),
                "class_mbdsa": (
                    float(row[class_mbdsa_col])
                    if class_mbdsa_col in row and pd.notna(row[class_mbdsa_col])
                    else np.nan
                ),
                "opponent_mbdsa": (
                    float(row[opponent_mbdsa_col])
                    if opponent_mbdsa_col in row and pd.notna(row[opponent_mbdsa_col])
                    else np.nan
                ),
                "margin_vs_opponent_mbdsa": (
                    float(row[plan["pair_margin_mbdsa_col"]])
                    if plan["pair_margin_mbdsa_col"] in row and pd.notna(row[plan["pair_margin_mbdsa_col"]])
                    else np.nan
                ),
                "class_score": (
                    float(row[class_score_col])
                    if class_score_col in row and pd.notna(row[class_score_col])
                    else np.nan
                ),
                "opponent_score": (
                    float(row[opponent_score_col])
                    if opponent_score_col in row and pd.notna(row[opponent_score_col])
                    else np.nan
                ),
                "margin_vs_opponent_score": (
                    float(row[plan["pair_margin_score_col"]])
                    if plan["pair_margin_score_col"] in row and pd.notna(row[plan["pair_margin_score_col"]])
                    else np.nan
                ),
                "best_target_class": row.get("best_target_class", ""),
                "second_target_class": row.get("second_target_class", ""),
                "margin_to_2nd_sam_deg": (
                    float(row["margin_to_2nd_sam"])
                    if "margin_to_2nd_sam" in row and pd.notna(row["margin_to_2nd_sam"])
                    else np.nan
                ),
                "margin_to_2nd_mbdsa": (
                    float(row["margin_to_2nd_mbdsa"])
                    if "margin_to_2nd_mbdsa" in row and pd.notna(row["margin_to_2nd_mbdsa"])
                    else np.nan
                ),
                "quality_cost_normalized": float(quality_cost_all[chosen_pos]),
                "pair_margin_benefit_normalized": float(pair_margin_benefit_all[chosen_pos]),
                "diversity_benefit_normalized": float(diversity_benefit[chosen_local]),
                "n_valid_candidates_for_class": int(len(valid)),
                "accepted_by_thresholds": bool(row.get("accepted_by_thresholds", False)),
                "acceptance_reason": row.get("acceptance_reason", ""),
            })

    df_selection = pd.DataFrame(selection_rows)

    df_spectra = pd.DataFrame({
        "wavelength_um": np.asarray(wavelength_um, dtype=float).ravel()
    })

    for item in selected_for_spectra:
        cand = item["candidate"]
        cand_idx = int(item["scene_index"])
        col_name = (
            f"{item['mode']}_{item['class_name']}_"
            f"x{item['x3_rank']}_{cand}"
        )

        df_spectra[col_name] = scene_full_for_average[cand_idx, :]

    return df_selection, df_spectra


def save_asphalt_concrete_x3_excel(
    xlsx_path,
    full_info,
    mask3_info,
):
    """
    Guarda el archivo adicional AsfaltosConcretosX3.xlsx.

    Contiene:
      - selección FULL;
      - firmas completas de los candidatos seleccionados con criterio FULL;
      - selección MASK3;
      - firmas completas de los candidatos seleccionados con criterio MASK3;
      - parámetros usados.
    """
    df_params = pd.DataFrame([
        {
            "parameter": "ASPHALT_CONCRETE_X3_COUNT",
            "value": ASPHALT_CONCRETE_X3_COUNT,
        },
        {
            "parameter": "MATCH_RANK_METRIC",
            "value": MATCH_RANK_METRIC,
        },
        {
            "parameter": "X3_WEIGHT_CLASS_SCORE",
            "value": X3_WEIGHT_CLASS_SCORE,
        },
        {
            "parameter": "X3_WEIGHT_PAIR_MARGIN",
            "value": X3_WEIGHT_PAIR_MARGIN,
        },
        {
            "parameter": "X3_WEIGHT_DIVERSITY",
            "value": X3_WEIGHT_DIVERSITY,
        },
        {
            "parameter": "criterion",
            "value": (
                "own-class quality + explicit asphalt/concrete margin + "
                "controlled spectral diversity"
            ),
        },
    ])

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        full_info["asfaltos_concretos_x3_selection"].to_excel(
            writer,
            index=False,
            sheet_name="selection_FULL"
        )
        full_info["asfaltos_concretos_x3_spectra"].to_excel(
            writer,
            index=False,
            sheet_name="spectra_FULL"
        )
        mask3_info["asfaltos_concretos_x3_selection"].to_excel(
            writer,
            index=False,
            sheet_name="selection_MASK3"
        )
        mask3_info["asfaltos_concretos_x3_spectra"].to_excel(
            writer,
            index=False,
            sheet_name="spectra_MASK3"
        )
        df_params.to_excel(
            writer,
            index=False,
            sheet_name="parameters"
        )



# =============================================================================
# EXCEL FINAL: 3 ASFALTOS + 3 CONCRETOS + 3 CATEGORÍAS PROMEDIADAS
# =============================================================================

def save_endmembers_finales_excel(
    xlsx_path,
    mode_name,
    wavelength_um,
    df_asphalt_concrete_x3_selection,
    scene_names,
    scene_full_for_average,
    averaged_endmembers,
    df_avg_summary,
    df_used,
):
    """
    Guarda el Excel final pedido para usar bundles de endmembers.

    Estructura esperada si hay suficientes candidatos válidos:
        asphalt_road_1
        asphalt_road_2
        asphalt_road_3
        concrete_1
        concrete_2
        concrete_3
        metal
        terracota
        vegetation

    Notas:
    - Asphalt y concrete NO se promedian: se escriben como candidatos separados.
    - Metal, terracota y vegetation quedan igual que en Final_averaged_endmembers:
      un único endmember promedio por clase.
    - Si no hay 3 asfaltos o 3 concretos válidos, se escriben solo los disponibles.
      Esto evita generar columnas artificiales con NaN que después puedan entrar por
      error al unmixing.
    """
    wavelength_um = np.asarray(wavelength_um, dtype=float).ravel()
    name_to_idx = {str(name): i for i, name in enumerate(scene_names)}

    df_final = pd.DataFrame({"wavelength_um": wavelength_um})
    rows_summary = []

    # ---------------------------------------------------------------------
    # 1) Asphalt y concrete: usar candidatos individuales X3.
    # ---------------------------------------------------------------------
    if df_asphalt_concrete_x3_selection is None or df_asphalt_concrete_x3_selection.empty:
        df_x3 = pd.DataFrame()
    else:
        df_x3 = df_asphalt_concrete_x3_selection.copy()

    for cls in ["asphalt_road", "concrete"]:
        if df_x3.empty or "class_name" not in df_x3.columns:
            sub = pd.DataFrame()
        else:
            sub = df_x3[df_x3["class_name"] == cls].copy()

        if not sub.empty:
            sub = sub.sort_values(["x3_rank", "candidate"]).head(
                ASPHALT_CONCRETE_X3_COUNT
            )

        n_written = 0

        for _, row in sub.iterrows():
            cand = str(row.get("candidate", ""))
            x3_rank = int(row.get("x3_rank", n_written + 1))

            if cand not in name_to_idx:
                rows_summary.append({
                    "mode": mode_name,
                    "endmember_name": f"{cls}_{x3_rank}",
                    "class_name": cls,
                    "source_type": "single_candidate_x3",
                    "candidate": cand,
                    "x3_rank": x3_rank,
                    "status": "CANDIDATE_NOT_FOUND_IN_SCENE_NAMES",
                    "ranking_metric": row.get("ranking_metric", MATCH_RANK_METRIC),
                    "class_match": row.get("class_match", ""),
                    "class_sam_deg": row.get("class_sam_deg", np.nan),
                    "class_mbdsa": row.get("class_mbdsa", np.nan),
                    "selection_score": row.get("selection_score", np.nan),
                })
                continue

            n_written += 1
            endmember_name = f"{cls}_{n_written}"
            cand_idx = name_to_idx[cand]
            df_final[endmember_name] = scene_full_for_average[cand_idx, :]

            rows_summary.append({
                "mode": mode_name,
                "endmember_name": endmember_name,
                "class_name": cls,
                "source_type": "single_candidate_x3",
                "candidate": cand,
                "x3_rank": x3_rank,
                "status": "OK",
                "ranking_metric": row.get("ranking_metric", MATCH_RANK_METRIC),
                "class_match": row.get("class_match", ""),
                "opponent_class": row.get("opponent_class", ""),
                "opponent_match": row.get("opponent_match", ""),
                "class_sam_deg": row.get("class_sam_deg", np.nan),
                "opponent_sam_deg": row.get("opponent_sam_deg", np.nan),
                "margin_vs_opponent_sam_deg": row.get("margin_vs_opponent_sam_deg", np.nan),
                "class_mbdsa": row.get("class_mbdsa", np.nan),
                "opponent_mbdsa": row.get("opponent_mbdsa", np.nan),
                "margin_vs_opponent_mbdsa": row.get("margin_vs_opponent_mbdsa", np.nan),
                "selection_score": row.get("selection_score", np.nan),
                "acceptance_reason": row.get("acceptance_reason", ""),
            })

        if n_written < ASPHALT_CONCRETE_X3_COUNT:
            rows_summary.append({
                "mode": mode_name,
                "endmember_name": None,
                "class_name": cls,
                "source_type": "single_candidate_x3",
                "candidate": None,
                "x3_rank": None,
                "status": (
                    f"ONLY_{n_written}_OF_{ASPHALT_CONCRETE_X3_COUNT}_"
                    "VALID_CANDIDATES_WRITTEN"
                ),
                "ranking_metric": MATCH_RANK_METRIC,
            })

    # ---------------------------------------------------------------------
    # 2) Metal, terracota y vegetation: quedan como promedio por clase.
    # ---------------------------------------------------------------------
    for cls in ["metal", "terracota", "vegetation"]:
        spec = averaged_endmembers.get(cls, None)

        if spec is None:
            rows_summary.append({
                "mode": mode_name,
                "endmember_name": cls,
                "class_name": cls,
                "source_type": "averaged_class",
                "candidate": None,
                "x3_rank": None,
                "status": "NO_AVERAGED_ENDMEMBER_FOUND",
                "ranking_metric": MATCH_RANK_METRIC,
            })
            continue

        spec = np.asarray(spec, dtype=np.float32).ravel()

        if spec.size != wavelength_um.size or np.all(~np.isfinite(spec)):
            rows_summary.append({
                "mode": mode_name,
                "endmember_name": cls,
                "class_name": cls,
                "source_type": "averaged_class",
                "candidate": None,
                "x3_rank": None,
                "status": "INVALID_OR_EMPTY_AVERAGED_ENDMEMBER",
                "ranking_metric": MATCH_RANK_METRIC,
            })
            continue

        df_final[cls] = spec

        avg_row = pd.DataFrame()
        if df_avg_summary is not None and not df_avg_summary.empty:
            avg_row = df_avg_summary[df_avg_summary["class_name"] == cls].copy()

        if not avg_row.empty:
            avg = avg_row.iloc[0]
            status = avg.get("status", "OK")
            n_candidates_used = avg.get("n_candidates_used", np.nan)
            candidates_used = avg.get("candidates_used", None)
            matches_used = avg.get("matches_used", None)
            mean_class_sam_deg = avg.get("mean_class_sam_deg", np.nan)
            mean_class_mbdsa = avg.get("mean_class_mbdsa", np.nan)
        else:
            status = "OK"
            n_candidates_used = np.nan
            candidates_used = None
            matches_used = None
            mean_class_sam_deg = np.nan
            mean_class_mbdsa = np.nan

        rows_summary.append({
            "mode": mode_name,
            "endmember_name": cls,
            "class_name": cls,
            "source_type": "averaged_class",
            "candidate": candidates_used,
            "x3_rank": None,
            "status": status,
            "ranking_metric": MATCH_RANK_METRIC,
            "n_candidates_used_for_average": n_candidates_used,
            "matches_used": matches_used,
            "mean_class_sam_deg": mean_class_sam_deg,
            "mean_class_mbdsa": mean_class_mbdsa,
        })

    df_summary_final = pd.DataFrame(rows_summary)

    n_endmembers_written = int(df_final.shape[1] - 1)
    expected_n_endmembers = int(2 * ASPHALT_CONCRETE_X3_COUNT + 3)

    df_parameters = pd.DataFrame([
        {
            "parameter": "mode",
            "value": mode_name,
        },
        {
            "parameter": "file_role",
            "value": (
                "Final endmember list: 3 asphalt + 3 concrete individual "
                "endmembers plus averaged metal/terracota/vegetation"
            ),
        },
        {
            "parameter": "expected_n_endmembers_if_complete",
            "value": expected_n_endmembers,
        },
        {
            "parameter": "actual_n_endmembers_written",
            "value": n_endmembers_written,
        },
        {
            "parameter": "ASPHALT_CONCRETE_X3_COUNT",
            "value": ASPHALT_CONCRETE_X3_COUNT,
        },
        {
            "parameter": "MATCH_RANK_METRIC",
            "value": MATCH_RANK_METRIC,
        },
        {
            "parameter": "CLASS_ASSIGNMENT_METRIC",
            "value": CLASS_ASSIGNMENT_METRIC,
        },
        {
            "parameter": "USE_ACCEPTANCE_THRESHOLDS",
            "value": USE_ACCEPTANCE_THRESHOLDS,
        },
        {
            "parameter": "note",
            "value": (
                "If fewer than 3 asphalt or concrete candidates satisfy the current "
                "selection/acceptance logic, only the valid candidates are written. "
                "No artificial NaN endmember columns are added."
            ),
        },
    ])

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df_final.to_excel(writer, index=False, sheet_name="endmembers")
        df_summary_final.to_excel(writer, index=False, sheet_name="endmember_summary")

        if df_x3.empty:
            pd.DataFrame().to_excel(writer, index=False, sheet_name="x3_selection")
        else:
            df_x3.to_excel(writer, index=False, sheet_name="x3_selection")

        if df_avg_summary is None or df_avg_summary.empty:
            pd.DataFrame().to_excel(writer, index=False, sheet_name="average_summary")
        else:
            df_avg_summary.to_excel(writer, index=False, sheet_name="average_summary")

        if df_used is None or df_used.empty:
            pd.DataFrame().to_excel(writer, index=False, sheet_name="candidates_used_avg")
        else:
            df_used.to_excel(writer, index=False, sheet_name="candidates_used_avg")

        df_parameters.to_excel(writer, index=False, sheet_name="parameters")

    return {
        "xlsx_path": xlsx_path,
        "n_endmembers_written": n_endmembers_written,
        "expected_n_endmembers": expected_n_endmembers,
        "columns": list(df_final.columns),
    }


def build_top_matches_dataframe(
    scene_names,
    lib_names_valid,
    sam_mat,
    mbdsa_mat,
    metric_name,
    top_k,
):
    """
    Construye un DataFrame de top matches usando la métrica indicada.

    Se usa internamente para que la asignación de clase pueda hacerse con SAM,
    aunque el ranking principal y los outputs Top/Best se mantengan con MBDSA.
    """
    rank_col = get_metric_column(metric_name)

    if rank_col == "sam_deg":
        rank_mat = sam_mat
    elif rank_col == "mbdsa":
        rank_mat = mbdsa_mat
    else:
        raise RuntimeError(f"rank_col inesperada: {rank_col}")

    rows_top = []

    for i, cname in enumerate(scene_names):
        order = np.argsort(rank_mat[i, :])
        top_idx = order[:min(top_k, len(order))]

        for rank, j in enumerate(top_idx, start=1):
            rows_top.append({
                "candidate": cname,
                "rank": rank,
                "ranking_metric": metric_name,
                "library_match": lib_names_valid[j],
                "score": float(rank_mat[i, j]),
                "sam_deg": float(sam_mat[i, j]),
                "mbdsa": float(mbdsa_mat[i, j]),
            })

    return pd.DataFrame(rows_top)


# =============================================================================
# ANÁLISIS PRINCIPAL
# =============================================================================

def run_single_analysis(
    mode_name,
    suffix,
    scene_names,
    scene_cmp,
    scene_full_for_average,
    wl_full_for_average,
    lib_names_all,
    lib_cmp_all,
    save_wl,
    lib_save_all,
    output_dir,
    top_k,
    top_x_for_average,
    target_class_prefixes,
    final_target_classes,
    min_bands_required,
):
    """
    Ejecuta una comparación FULL o MASK3.

    Importante:
    - La selección puede hacerse con un subconjunto de bandas, por ejemplo MASK3.
    - El promedio final siempre se hace con scene_full_for_average, que debe
      estar en la grilla completa de Sepolia.
    """
    rank_col = get_rank_column()

    valid_lib = np.any(np.isfinite(lib_cmp_all), axis=1)

    lib_cmp = lib_cmp_all[valid_lib]
    lib_names_valid = [n for n, ok in zip(lib_names_all, valid_lib) if ok]
    lib_save_valid = lib_save_all[valid_lib]

    print(f"[INFO] [{mode_name}] Espectros GUSL válidos: {len(lib_names_valid)}")
    print(f"[INFO] [{mode_name}] Bandas nominales de comparación: {scene_cmp.shape[1]}")
    print(f"[INFO] [{mode_name}] Métrica principal de ranking: {MATCH_RANK_METRIC}")

    if len(lib_names_valid) == 0:
        raise RuntimeError(f"[{mode_name}] No quedaron espectros GUSL válidos.")

    if scene_cmp.shape[1] < min_bands_required:
        raise RuntimeError(
            f"[{mode_name}] Muy pocas bandas nominales para la comparación "
            f"({scene_cmp.shape[1]} < {min_bands_required})."
        )

    print(f"[INFO] [{mode_name}] Calculando matrices SAM y MBDSA...")
    sam_mat, mbdsa_mat, metric_valid_bands = compute_similarity_matrices(
        scene_cmp,
        lib_cmp
    )

    n_metric_bands = int(np.sum(metric_valid_bands))
    print(f"[INFO] [{mode_name}] Bandas efectivas usadas para métricas: {n_metric_bands}")

    if n_metric_bands < min_bands_required:
        raise RuntimeError(
            f"[{mode_name}] Muy pocas bandas efectivas para métricas "
            f"({n_metric_bands} < {min_bands_required})."
        )

    # -------------------------------------------------------------------------
    # Matrices completas
    # -------------------------------------------------------------------------
    df_sam = pd.DataFrame(sam_mat, index=scene_names, columns=lib_names_valid)
    df_mbdsa = pd.DataFrame(mbdsa_mat, index=scene_names, columns=lib_names_valid)

    sam_csv = output_dir / f"SAM_matrix_scene_vs_GUSL_ALL{suffix}.csv"
    mbdsa_csv = output_dir / f"MBDSA_matrix_scene_vs_GUSL_ALL{suffix}.csv"

    df_sam.to_csv(sam_csv, encoding="utf-8-sig")
    df_mbdsa.to_csv(mbdsa_csv, encoding="utf-8-sig")

    print(f"[OK] {sam_csv}")
    print(f"[OK] {mbdsa_csv}")

    # -------------------------------------------------------------------------
    # Top-K por candidato
    # -------------------------------------------------------------------------
    rows_top = []
    rows_best = []

    if rank_col == "sam_deg":
        rank_mat = sam_mat
    elif rank_col == "mbdsa":
        rank_mat = mbdsa_mat
    else:
        raise RuntimeError(f"rank_col inesperada: {rank_col}")

    for i, cname in enumerate(scene_names):
        order = np.argsort(rank_mat[i, :])
        top_idx = order[:min(top_k, len(order))]

        best_j = top_idx[0]

        rows_best.append({
            "candidate": cname,
            "ranking_metric": MATCH_RANK_METRIC,
            "best_library_match": lib_names_valid[best_j],
            "best_score": float(rank_mat[i, best_j]),
            "best_sam_deg": float(sam_mat[i, best_j]),
            "best_mbdsa": float(mbdsa_mat[i, best_j]),
        })

        for rank, j in enumerate(top_idx, start=1):
            rows_top.append({
                "candidate": cname,
                "rank": rank,
                "ranking_metric": MATCH_RANK_METRIC,
                "library_match": lib_names_valid[j],
                "score": float(rank_mat[i, j]),
                "sam_deg": float(sam_mat[i, j]),
                "mbdsa": float(mbdsa_mat[i, j]),
            })

    df_top = pd.DataFrame(rows_top)
    df_best = pd.DataFrame(rows_best).sort_values("best_score", ascending=True)

    top_csv = output_dir / f"Top_matches_per_candidate{suffix}.csv"
    best_csv = output_dir / f"Best_match_per_candidate{suffix}.csv"

    df_top.to_csv(top_csv, index=False, encoding="utf-8-sig")
    df_best.to_csv(best_csv, index=False, encoding="utf-8-sig")

    print(f"[OK] {top_csv}")
    print(f"[OK] {best_csv}")

    # -------------------------------------------------------------------------
    # Resumen por clase objetivo
    # -------------------------------------------------------------------------
    if str(CLASS_ASSIGNMENT_METRIC).strip().lower() == str(MATCH_RANK_METRIC).strip().lower():
        df_top_for_class_assignment = df_top
    else:
        df_top_for_class_assignment = build_top_matches_dataframe(
            scene_names=scene_names,
            lib_names_valid=lib_names_valid,
            sam_mat=sam_mat,
            mbdsa_mat=mbdsa_mat,
            metric_name=CLASS_ASSIGNMENT_METRIC,
            top_k=top_k,
        )

    df_target_summary = summarize_candidates_by_target_class(
        df_top_for_class_assignment,
        target_class_prefixes
    )

    df_target_summary = add_acceptance_flags(df_target_summary)

    summary_csv = output_dir / f"Target_class_summary_per_candidate{suffix}.csv"
    df_target_summary.to_csv(summary_csv, index=False, encoding="utf-8-sig")
    print(f"[OK] {summary_csv}")

    # -------------------------------------------------------------------------
    # Salida extra: 3 asfaltos + 3 concretos
    # -------------------------------------------------------------------------
    df_asfaltos_concretos_x3, df_asfaltos_concretos_x3_spectra = select_asphalt_concrete_x3(
        mode_name=mode_name,
        df_summary=df_target_summary,
        scene_names=scene_names,
        scene_cmp=scene_cmp,
        scene_full_for_average=scene_full_for_average,
        wavelength_um=wl_full_for_average,
        top_n=ASPHALT_CONCRETE_X3_COUNT,
    )

    print(
        f"[INFO] [{mode_name}] Selección Asfaltos/Concretos X3: "
        f"{len(df_asfaltos_concretos_x3)} candidatos"
    )

    # -------------------------------------------------------------------------
    # Promedio de candidatos de escena por clase final
    # -------------------------------------------------------------------------
    print(
        f"[INFO] [{mode_name}] Promediando firmas completas: "
        f"{scene_full_for_average.shape[1]} bandas "
        f"(selección hecha con {scene_cmp.shape[1]} bandas nominales; "
        f"TOP_X_MATERIALS_FOR_AVERAGE={top_x_for_average}; "
        f"ranking={MATCH_RANK_METRIC})"
    )

    df_avg_summary, df_used, averaged_endmembers = collect_candidates_for_class_average(
        df_summary=df_target_summary,
        scene_names=scene_names,
        scene_full_for_average=scene_full_for_average,
        final_target_classes=final_target_classes,
        top_x_for_average=top_x_for_average,
    )

    avg_summary_csv = output_dir / f"Averaged_endmember_summary_per_class{suffix}.csv"
    used_csv = output_dir / f"Candidates_used_for_average_per_class{suffix}.csv"
    final_endm_xlsx = output_dir / f"Final_averaged_endmembers{suffix}.xlsx"

    df_avg_summary.to_csv(avg_summary_csv, index=False, encoding="utf-8-sig")
    df_used.to_csv(used_csv, index=False, encoding="utf-8-sig")

    print(f"[OK] {avg_summary_csv}")
    print(f"[OK] {used_csv}")

    save_averaged_endmembers_excel(
        xlsx_path=final_endm_xlsx,
        wavelength_um=wl_full_for_average,
        averaged_endmembers=averaged_endmembers,
        df_avg_summary=df_avg_summary,
        df_used=df_used,
    )

    print(f"[OK] {final_endm_xlsx}")

    # -------------------------------------------------------------------------
    # Excel final adicional: 3 asfaltos + 3 concretos + metal/terracota/vegetation
    # -------------------------------------------------------------------------
    endmembers_finales_xlsx = output_dir / f"{FINAL_X9_FILENAME_BASE}{suffix}.xlsx"
    endmembers_finales_info = save_endmembers_finales_excel(
        xlsx_path=endmembers_finales_xlsx,
        mode_name=mode_name,
        wavelength_um=wl_full_for_average,
        df_asphalt_concrete_x3_selection=df_asfaltos_concretos_x3,
        scene_names=scene_names,
        scene_full_for_average=scene_full_for_average,
        averaged_endmembers=averaged_endmembers,
        df_avg_summary=df_avg_summary,
        df_used=df_used,
    )

    print(
        f"[OK] {endmembers_finales_xlsx} "
        f"({endmembers_finales_info['n_endmembers_written']}/"
        f"{endmembers_finales_info['expected_n_endmembers']} endmembers escritos)"
    )

    print_average_summary(
        df_avg_summary,
        title=f"Endmembers promediados por clase [{mode_name}]"
    )

    # -------------------------------------------------------------------------
    # Guardar GUSL remuestreada
    # -------------------------------------------------------------------------
    remuestreada_specs = pd.DataFrame(
        lib_save_valid.T,
        columns=lib_names_valid
    )

    remuestreada = pd.concat(
        [
            pd.DataFrame({"wavelength_um": save_wl}),
            remuestreada_specs
        ],
        axis=1
    )

    remuestreada_xlsx = output_dir / f"GUSL_ALL_resampled_no_extrap_to_Sepolia_scene_grid{suffix}.xlsx"

    with pd.ExcelWriter(remuestreada_xlsx, engine="openpyxl") as writer:
        remuestreada.to_excel(writer, index=False, sheet_name="GUSL_on_scene_grid")
        df_best.to_excel(writer, index=False, sheet_name="best_match_summary")
        df_top.to_excel(writer, index=False, sheet_name="top_matches")
        df_target_summary.to_excel(writer, index=False, sheet_name="target_class_summary")
        df_avg_summary.to_excel(writer, index=False, sheet_name="avg_endmember_summary")
        df_used.to_excel(writer, index=False, sheet_name="candidates_used_for_avg")

        df_metric_bands = pd.DataFrame({
            "wavelength_um": (
                save_wl
                if len(save_wl) == len(metric_valid_bands)
                else np.arange(len(metric_valid_bands))
            ),
            "used_for_metrics": metric_valid_bands
        })
        df_metric_bands.to_excel(writer, index=False, sheet_name="metric_valid_bands")

    print(f"[OK] {remuestreada_xlsx}")

    return {
        "n_lib_valid": len(lib_names_valid),
        "n_bands_nominal": int(scene_cmp.shape[1]),
        "n_bands_metrics": n_metric_bands,
        "sam_csv": sam_csv,
        "mbdsa_csv": mbdsa_csv,
        "top_csv": top_csv,
        "best_csv": best_csv,
        "summary_csv": summary_csv,
        "avg_summary_csv": avg_summary_csv,
        "used_csv": used_csv,
        "final_endm_xlsx": final_endm_xlsx,
        "endmembers_finales_xlsx": endmembers_finales_xlsx,
        "endmembers_finales_info": endmembers_finales_info,
        "remuestreada_xlsx": remuestreada_xlsx,
        "asfaltos_concretos_x3_selection": df_asfaltos_concretos_x3,
        "asfaltos_concretos_x3_spectra": df_asfaltos_concretos_x3_spectra,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("[INFO] Leyendo candidatos de escena...")

    if not CANDIDATES_XLSX.exists():
        raise FileNotFoundError(f"No existe: {CANDIDATES_XLSX}")

    scene_wl, scene_X, scene_names, scene_sheet, scene_wl_col = read_spectral_library_excel(
        CANDIDATES_XLSX,
        preferred_sheet=CANDIDATE_SHEET
    )

    print(f"[INFO] Candidatos: hoja='{scene_sheet}', wl_col='{scene_wl_col}'")
    print(f"[INFO] Scene -> {len(scene_names)} espectros, {scene_wl.size} bandas")
    print(f"[INFO] wl scene: [{scene_wl.min():.4f}, {scene_wl.max():.4f}] um")

    print("\n[INFO] Leyendo GUSL Brussels + DLR...")

    if not GUSL_XLSX.exists():
        raise FileNotFoundError(f"No existe: {GUSL_XLSX}")

    gusl_libraries = read_multiple_gusl_sheets(
        xlsx_path=GUSL_XLSX,
        sheet_names=GUSL_SHEETS
    )

    all_gusl_names = []
    all_gusl_resampled = []

    for lib in gusl_libraries:
        sheet_name = lib["sheet_name"]
        gusl_wl = lib["wl"]
        gusl_X_raw = lib["X"]
        gusl_names = lib["names"]
        gusl_wl_col = lib["wl_col"]

        print("\n" + "-" * 80)
        print(f"[INFO] GUSL sheet: '{sheet_name}', wl_col='{gusl_wl_col}'")
        print(f"[INFO] {sheet_name} -> {len(gusl_names)} espectros, {gusl_wl.size} bandas")
        print(f"[INFO] wl {sheet_name}: [{gusl_wl.min():.4f}, {gusl_wl.max():.4f}] um")

        print(
            f"[INFO] Remuestreando {sheet_name} a la grilla de Sepolia "
            f"usando PCHIP sin extrapolación..."
        )

        gusl_X_on_scene_grid = pchip_library_to_target_grid(
            lib_wl=gusl_wl,
            lib_X=gusl_X_raw,
            target_wl=scene_wl
        )

        print(
            f"[INFO] {sheet_name} remuestreada -> "
            f"{gusl_X_on_scene_grid.shape[0]} espectros, "
            f"{gusl_X_on_scene_grid.shape[1]} bandas"
        )

        bands_with_any_finite = int(np.sum(np.any(np.isfinite(gusl_X_on_scene_grid), axis=0)))
        bands_with_all_finite = int(np.sum(np.all(np.isfinite(gusl_X_on_scene_grid), axis=0)))
        print(
            f"[INFO] {sheet_name}: bandas con al menos una firma finita = "
            f"{bands_with_any_finite}/{gusl_X_on_scene_grid.shape[1]}"
        )
        print(
            f"[INFO] {sheet_name}: bandas finitas para todas las firmas = "
            f"{bands_with_all_finite}/{gusl_X_on_scene_grid.shape[1]}"
        )

        all_gusl_names.extend(gusl_names)
        all_gusl_resampled.append(gusl_X_on_scene_grid)

    gusl_names_all = all_gusl_names
    gusl_X_all_on_scene_grid = np.vstack(all_gusl_resampled)

    print("\n" + "=" * 80)
    print("[INFO] GUSL combinada Brussels + DLR")
    print(f"[INFO] Total espectros GUSL combinados: {len(gusl_names_all)}")
    print(f"[INFO] Matriz GUSL combinada: {gusl_X_all_on_scene_grid.shape}")
    print(f"[INFO] Grilla final usada: Sepolia completa -> {scene_wl.size} bandas")
    print("[INFO] GUSL fue interpolada sin extrapolación; fuera del rango real se conservan NaN.")
    print("[INFO] Las métricas usarán solo las bandas finitas comunes entre candidatos y GUSL.")
    print(f"[INFO] TOP_X_MATERIALS_FOR_AVERAGE = {TOP_X_MATERIALS_FOR_AVERAGE}")
    print(f"[INFO] MATCH_RANK_METRIC = {MATCH_RANK_METRIC}")
    print("=" * 80)

    safe_mkdir(OUTPUT_DIR)

    # -------------------------------------------------------------------------
    # FULL
    # -------------------------------------------------------------------------
    scene_wl_full_cmp = scene_wl
    scene_cmp_full = scene_X
    gusl_cmp_full_all = gusl_X_all_on_scene_grid

    print("\n[INFO] Ejecutando análisis FULL sobre grilla completa de Sepolia...")

    full_info = run_single_analysis(
        mode_name="FULL",
        suffix="",
        scene_names=scene_names,
        scene_cmp=scene_cmp_full,
        scene_full_for_average=scene_X,
        wl_full_for_average=scene_wl,
        lib_names_all=gusl_names_all,
        lib_cmp_all=gusl_cmp_full_all,
        save_wl=scene_wl,
        lib_save_all=gusl_X_all_on_scene_grid,
        output_dir=OUTPUT_DIR,
        top_k=TOP_K,
        top_x_for_average=TOP_X_MATERIALS_FOR_AVERAGE,
        target_class_prefixes=TARGET_CLASS_PREFIXES,
        final_target_classes=FINAL_TARGET_CLASSES,
        min_bands_required=10,
    )

    # -------------------------------------------------------------------------
    # MASK3
    # -------------------------------------------------------------------------
    print("\n[INFO] Construyendo subset MASK3 sobre grilla completa de Sepolia...")

    mask3_mask, selected_mask3 = build_mask3_mask(
        scene_wl,
        MASK3_TARGETS_UM,
        max_delta_um=MASK3_MAX_DELTA_UM
    )

    if np.sum(mask3_mask) == 0:
        raise RuntimeError(
            "No se encontró ninguna banda utilizable de MASK3 en la grilla de Sepolia."
        )

    print(f"[INFO] MASK3 targets pedidos : {len(MASK3_TARGETS_UM)}")
    print(f"[INFO] MASK3 bandas halladas : {int(np.sum(mask3_mask))}")

    for tgt, found, delta, idx in selected_mask3:
        print(
            f"       target={tgt:.3f} um -> band={found:.4f} um | "
            f"delta={delta:.4f} | idx={idx}"
        )

    scene_wl_mask3_cmp = scene_wl[mask3_mask]
    scene_cmp_mask3 = scene_X[:, mask3_mask]
    gusl_cmp_mask3_all = gusl_X_all_on_scene_grid[:, mask3_mask]

    print("\n[INFO] Ejecutando análisis MASK3...")

    mask3_info = run_single_analysis(
        mode_name="MASK3",
        suffix="_mask3",
        scene_names=scene_names,
        scene_cmp=scene_cmp_mask3,
        scene_full_for_average=scene_X,
        wl_full_for_average=scene_wl,
        lib_names_all=gusl_names_all,
        lib_cmp_all=gusl_cmp_mask3_all,
        save_wl=scene_wl_mask3_cmp,
        lib_save_all=gusl_cmp_mask3_all,
        output_dir=OUTPUT_DIR,
        top_k=TOP_K,
        top_x_for_average=TOP_X_MATERIALS_FOR_AVERAGE,
        target_class_prefixes=TARGET_CLASS_PREFIXES,
        final_target_classes=FINAL_TARGET_CLASSES,
        min_bands_required=5,
    )

    asfaltos_concretos_x3_xlsx = OUTPUT_DIR / ASPHALT_CONCRETE_X3_FILENAME
    save_asphalt_concrete_x3_excel(
        xlsx_path=asfaltos_concretos_x3_xlsx,
        full_info=full_info,
        mask3_info=mask3_info,
    )
    print(f"[OK] {asfaltos_concretos_x3_xlsx}")

    # -------------------------------------------------------------------------
    # Resumen final
    # -------------------------------------------------------------------------
    print("\n======================")
    print("Resumen")
    print("======================")
    print(f"Candidatos escena                         : {len(scene_names)}")
    print(f"Bandas Sepolia completas                  : {scene_wl.size}")
    print(f"Espectros GUSL ALL FULL                   : {full_info['n_lib_valid']}")
    print(f"Espectros GUSL ALL MASK3                  : {mask3_info['n_lib_valid']}")
    print(f"Bandas FULL nominales                     : {full_info['n_bands_nominal']}")
    print(f"Bandas FULL efectivas métricas            : {full_info['n_bands_metrics']}")
    print(f"Bandas MASK3 nominales                    : {mask3_info['n_bands_nominal']}")
    print(f"Bandas MASK3 efectivas métricas           : {mask3_info['n_bands_metrics']}")
    print(f"TOP_X_MATERIALS_FOR_AVERAGE               : {TOP_X_MATERIALS_FOR_AVERAGE}")
    print(f"MATCH_RANK_METRIC                         : {MATCH_RANK_METRIC}")
    print(f"Excel endmembers FULL                     : {full_info['final_endm_xlsx']}")
    print(f"Excel endmembers MASK3                    : {mask3_info['final_endm_xlsx']}")
    print(f"Excel EndmembersFinales FULL              : {full_info['endmembers_finales_xlsx']}")
    print(f"Excel EndmembersFinales MASK3             : {mask3_info['endmembers_finales_xlsx']}")
    print(f"Excel Asfaltos/Concretos X3              : {asfaltos_concretos_x3_xlsx}")
    print(f"Output                                    : {OUTPUT_DIR}")
    print("======================")
    print("[DONE]")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n[FATAL] El script terminó con error:\n")
        traceback.print_exc()
        sys.exit(1)