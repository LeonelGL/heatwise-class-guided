
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
select_bands_paper_style.py

Selección de bandas "inspirada en Herold et al. (2003)" para un archivo Excel
con espectros de materiales.

IDEA METODOLÓGICA
-----------------
El paper usa:
1) una medida de separabilidad entre clases (Bhattacharyya distance),
2) evaluación de combinaciones de bandas,
3) top combinaciones por "best average separability" y "best minimum separability",
4) frecuencia de aparición de cada banda dentro de esas top combinaciones como
   medida de importancia.

Este script reproduce ESA lógica de trabajo:

- Si hay múltiples espectros por material (por ejemplo columnas:
      asphalt__1, asphalt__2, asphalt__3, concrete__1, concrete__2, ...)
  y cada clase tiene al menos 2 muestras,
  usa Bhattacharyya distance diagonal regularizada.

- Si hay UN solo espectro por material (caso típico de "5 espectros"),
  NO se puede estimar la covarianza de clase de forma rigurosa.
  En ese caso el script usa un PROXY:
      separabilidad = distancia euclídea estandarizada entre espectros
  y mantiene el mismo esquema de:
      top combinaciones + frecuencia de aparición.
  Es decir: es "paper-inspired", no una reproducción exacta del paper.

SALIDAS
-------
- Excel con:
    * per_band_scores
    * top_avg_combinations
    * top_min_combinations
    * band_frequency
    * recommended_bands
- PNG con frecuencia de aparición por longitud de onda

REQUISITOS
----------
numpy, pandas, openpyxl, matplotlib
"""

from pathlib import Path
from itertools import combinations
import math
import random
import re

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

INPUT_XLSX = Path(r"/mnt/data/input_spectra.xlsx")
OUTPUT_DIR = Path(r"/mnt/data/band_selection_results")

# Si las columnas vienen como asphalt__1, asphalt__2, concrete__1...
# el grupo se toma por el prefijo antes de GROUP_SEPARATOR.
GROUP_SEPARATOR = "__"

# Cantidad final de bandas que querés recomendar
N_FINAL_BANDS = 15

# Cantidad de bandas por combinación evaluada
# (en el paper usaron 7 y 9 para distintos análisis; acá lo hacemos configurable)
BANDS_PER_COMBO = 9

# Número de top combinaciones a guardar para promedio y mínimo
TOP_N_COMBINATIONS = 20

# Cuántas bandas preseleccionar antes de muestrear combinaciones
# para no explotar combinatoriamente
PRESELECT_TOP_BANDS = 35

# Cuántas combinaciones aleatorias evaluar del pool preseleccionado
# Si el número total posible es menor, las recorre exhaustivamente.
N_RANDOM_COMBINATIONS = 50000

# Distancia mínima entre bandas recomendadas para evitar redundancia
MIN_SPACING_UM = 0.040

# Wavelength filters
WL_MIN = None
WL_MAX = None

# Intervalos inválidos opcionales [(lo, hi), ...]
INVALID_INTERVALS_UM = [
    # (1.315, 1.467),
    # (1.759, 1.949),
]

# Modo de normalización previa
# "none"    -> usa reflectancia tal cual
# "l2"      -> normaliza cada espectro a norma 2 = 1
# "snv"     -> standard normal variate por espectro
PREPROCESS_MODE = "none"

# Regularización para B-distance si hay múltiples muestras por clase
REG_EPS = 1e-6

# Semilla
RANDOM_SEED = 42


# =============================================================================
# UTILIDADES
# =============================================================================

def safe_mkdir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def normalize_name(s):
    s = str(s).strip()
    s = s.replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s)
    return s


def find_wavelength_column(columns):
    low = [str(c).strip().lower() for c in columns]
    preferred = ["wavelength", "wavelength_um", "lambda", "wl"]
    for p in preferred:
        for c, cl in zip(columns, low):
            if p in cl:
                return c
    return columns[0]


def average_duplicate_wavelengths(wl, X):
    wl = np.asarray(wl, dtype=float)
    X = np.asarray(X, dtype=float)
    uniq = np.unique(wl)
    if uniq.size == wl.size:
        return wl.astype(np.float32), X.astype(np.float32)

    out = np.full((X.shape[0], uniq.size), np.nan, dtype=np.float32)
    for j, u in enumerate(uniq):
        idx = np.where(np.isclose(wl, u))[0]
        out[:, j] = np.nanmean(X[:, idx], axis=1)
    return uniq.astype(np.float32), out.astype(np.float32)


def apply_interval_mask(wl, intervals):
    wl = np.asarray(wl, dtype=float)
    mask = np.ones(wl.size, dtype=bool)
    for lo, hi in intervals:
        mask &= ~((wl >= float(lo)) & (wl <= float(hi)))
    return mask


def preprocess_matrix(X, mode="none"):
    X = np.asarray(X, dtype=float).copy()

    if mode == "none":
        return X.astype(np.float32)

    if mode == "l2":
        n = np.linalg.norm(X, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return (X / n).astype(np.float32)

    if mode == "snv":
        mu = np.nanmean(X, axis=1, keepdims=True)
        sd = np.nanstd(X, axis=1, keepdims=True)
        sd[sd == 0] = 1.0
        return ((X - mu) / sd).astype(np.float32)

    raise ValueError(f"PREPROCESS_MODE no reconocido: {mode}")


def read_excel_spectra(xlsx_path: Path):
    xls = pd.ExcelFile(xlsx_path)
    sheet = xls.sheet_names[0]
    df = pd.read_excel(xlsx_path, sheet_name=sheet)
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
    names = []
    X = []
    for c in spec_cols:
        vals = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
        if np.all(~np.isfinite(vals)):
            continue
        names.append(normalize_name(c))
        X.append(vals)

    if len(X) == 0:
        raise ValueError("No encontré espectros válidos en el Excel")

    X = np.vstack(X).astype(np.float32)
    wl, X = average_duplicate_wavelengths(wl, X)

    return wl.astype(np.float32), X.astype(np.float32), names, sheet, wl_col


def infer_groups(names, separator="__"):
    groups = {}
    for n in names:
        if separator in n:
            base = n.split(separator)[0].strip()
        else:
            base = n.strip()
        groups.setdefault(base, []).append(n)
    return groups


def build_group_arrays(names, X, groups):
    name_to_idx = {n: i for i, n in enumerate(names)}
    out = {}
    for g, cols in groups.items():
        idx = [name_to_idx[c] for c in cols]
        out[g] = np.asarray(X[idx, :], dtype=np.float32)
    return out


# =============================================================================
# MÉTRICAS DE SEPARABILIDAD
# =============================================================================

def pairwise_standardized_euclidean(class_means, band_idx, band_scales, eps=1e-12):
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
    return float(np.mean(vals)), float(np.min(vals))


def bhattacharyya_distance_diag(mu1, var1, mu2, var2, eps=1e-12):
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

    term1 = 0.125 * np.sum(((mu1 - mu2) ** 2) / avg)
    term2 = 0.5 * np.sum(np.log(avg / np.sqrt(var1 * var2)))
    return float(term1 + term2)


def pairwise_bhattacharyya_diag(group_arrays, band_idx, reg_eps=1e-6):
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
        # var diagonal robusta
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
            vals.append(
                bhattacharyya_distance_diag(mu1, var1, mu2, var2, eps=reg_eps)
            )

    vals = np.asarray(vals, dtype=float)
    return float(np.mean(vals)), float(np.min(vals))


# =============================================================================
# SELECCIÓN DE BANDAS
# =============================================================================

def compute_single_band_scores(
    wl,
    group_arrays,
    use_exact_bdistance,
):
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
            avg_s, min_s = pairwise_bhattacharyya_diag(group_arrays, [b], reg_eps=REG_EPS)
        else:
            avg_s, min_s = pairwise_standardized_euclidean(class_means, [b], band_scales)

        rows.append({
            "band_idx": b,
            "wavelength_um": float(wl[b]),
            "avg_sep": avg_s,
            "min_sep": min_s,
            "combo_score": 0.5 * (avg_s + min_s),
        })

    return pd.DataFrame(rows).sort_values(
        ["combo_score", "avg_sep", "min_sep"],
        ascending=False
    ).reset_index(drop=True)


def sample_band_combinations(candidate_idx, k, n_random, seed=42):
    candidate_idx = list(candidate_idx)
    total_possible = math.comb(len(candidate_idx), k)

    if total_possible <= n_random:
        return list(combinations(candidate_idx, k))

    rng = random.Random(seed)
    combos = set()
    while len(combos) < n_random:
        comb = tuple(sorted(rng.sample(candidate_idx, k)))
        combos.add(comb)
    return list(combos)


def evaluate_combinations(
    wl,
    group_arrays,
    combos,
    use_exact_bdistance,
):
    class_means = {k: np.nanmean(v, axis=0) for k, v in group_arrays.items()}
    all_means = np.vstack([class_means[k] for k in class_means.keys()])
    band_scales = np.nanstd(all_means, axis=0)
    band_scales[band_scales == 0] = 1.0

    rows = []
    for combo in combos:
        if use_exact_bdistance:
            avg_s, min_s = pairwise_bhattacharyya_diag(group_arrays, combo, reg_eps=REG_EPS)
        else:
            avg_s, min_s = pairwise_standardized_euclidean(class_means, combo, band_scales)

        rows.append({
            "band_indices": ",".join(map(str, combo)),
            "wavelengths_um": ",".join(f"{wl[i]:.6f}" for i in combo),
            "avg_sep": avg_s,
            "min_sep": min_s,
        })

    return pd.DataFrame(rows)


def build_frequency_table(wl, top_avg_df, top_min_df):
    freq = np.zeros(len(wl), dtype=int)
    freq_avg = np.zeros(len(wl), dtype=int)
    freq_min = np.zeros(len(wl), dtype=int)

    for _, row in top_avg_df.iterrows():
        idx = [int(x) for x in str(row["band_indices"]).split(",")]
        for i in idx:
            freq[i] += 1
            freq_avg[i] += 1

    for _, row in top_min_df.iterrows():
        idx = [int(x) for x in str(row["band_indices"]).split(",")]
        for i in idx:
            freq[i] += 1
            freq_min[i] += 1

    df = pd.DataFrame({
        "band_idx": np.arange(len(wl)),
        "wavelength_um": wl,
        "freq_total": freq,
        "freq_top_avg": freq_avg,
        "freq_top_min": freq_min,
    }).sort_values(
        ["freq_total", "freq_top_min", "freq_top_avg", "wavelength_um"],
        ascending=[False, False, False, True]
    ).reset_index(drop=True)

    return df


def recommend_bands_from_frequency(freq_df, n_final=15, min_spacing_um=0.040):
    selected = []
    for _, row in freq_df.iterrows():
        wl = float(row["wavelength_um"])
        if all(abs(wl - s["wavelength_um"]) >= min_spacing_um for s in selected):
            selected.append({
                "band_idx": int(row["band_idx"]),
                "wavelength_um": wl,
                "freq_total": int(row["freq_total"]),
                "freq_top_avg": int(row["freq_top_avg"]),
                "freq_top_min": int(row["freq_top_min"]),
            })
        if len(selected) >= n_final:
            break

    return pd.DataFrame(selected).sort_values("wavelength_um").reset_index(drop=True)


def plot_frequency(freq_df, out_png):
    d = freq_df.sort_values("wavelength_um")
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(d["wavelength_um"], d["freq_total"], width=0.01)
    ax.set_xlabel("Wavelength (um)")
    ax.set_ylabel("Frequency in top combinations")
    ax.set_title("Band importance (paper-style frequency of appearance)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


# =============================================================================
# MAIN
# =============================================================================

def main():
    safe_mkdir(OUTPUT_DIR)

    wl, X, names, sheet, wl_col = read_excel_spectra(INPUT_XLSX)
    print(f"[INFO] Hoja: {sheet}")
    print(f"[INFO] Columna de longitud de onda: {wl_col}")
    print(f"[INFO] Espectros leídos: {len(names)}")
    print(f"[INFO] Bandas originales: {len(wl)}")

    mask = np.ones(len(wl), dtype=bool)
    if WL_MIN is not None:
        mask &= wl >= float(WL_MIN)
    if WL_MAX is not None:
        mask &= wl <= float(WL_MAX)
    if INVALID_INTERVALS_UM:
        mask &= apply_interval_mask(wl, INVALID_INTERVALS_UM)

    wl = wl[mask]
    X = X[:, mask]
    print(f"[INFO] Bandas válidas tras filtros: {len(wl)}")

    X = preprocess_matrix(X, mode=PREPROCESS_MODE)

    groups = infer_groups(names, separator=GROUP_SEPARATOR)
    group_arrays = build_group_arrays(names, X, groups)

    print("[INFO] Grupos detectados:")
    for g, arr in group_arrays.items():
        print(f"       - {g}: {arr.shape[0]} espectro(s)")

    use_exact_bdistance = all(arr.shape[0] >= 2 for arr in group_arrays.values())
    if use_exact_bdistance:
        print("[INFO] Modo: Bhattacharyya distance diagonal (hay >=2 muestras por clase).")
    else:
        print("[INFO] Modo: proxy paper-inspired (1 espectro por clase o clases con muy pocas muestras).")

    # -------------------------------------------------------------------------
    # 1) Score por banda individual
    # -------------------------------------------------------------------------
    df_band = compute_single_band_scores(wl, group_arrays, use_exact_bdistance)

    # pool preseleccionado
    pre_n = min(PRESELECT_TOP_BANDS, len(df_band))
    candidate_idx = df_band["band_idx"].iloc[:pre_n].astype(int).tolist()

    print(f"[INFO] Bandas preseleccionadas para combinar: {pre_n}")

    # -------------------------------------------------------------------------
    # 2) Combinaciones
    # -------------------------------------------------------------------------
    if len(candidate_idx) < BANDS_PER_COMBO:
        raise ValueError(
            f"No hay suficientes bandas preseleccionadas para formar combinaciones de {BANDS_PER_COMBO}"
        )

    combos = sample_band_combinations(
        candidate_idx=candidate_idx,
        k=BANDS_PER_COMBO,
        n_random=N_RANDOM_COMBINATIONS,
        seed=RANDOM_SEED,
    )
    print(f"[INFO] Combinaciones evaluadas: {len(combos)}")

    df_combo = evaluate_combinations(
        wl=wl,
        group_arrays=group_arrays,
        combos=combos,
        use_exact_bdistance=use_exact_bdistance,
    )

    top_avg = df_combo.sort_values(["avg_sep", "min_sep"], ascending=False).head(TOP_N_COMBINATIONS).reset_index(drop=True)
    top_min = df_combo.sort_values(["min_sep", "avg_sep"], ascending=False).head(TOP_N_COMBINATIONS).reset_index(drop=True)

    # -------------------------------------------------------------------------
    # 3) Frecuencia de aparición
    # -------------------------------------------------------------------------
    freq_df = build_frequency_table(wl, top_avg, top_min)
    rec_df = recommend_bands_from_frequency(
        freq_df,
        n_final=N_FINAL_BANDS,
        min_spacing_um=MIN_SPACING_UM,
    )

    # -------------------------------------------------------------------------
    # 4) Export
    # -------------------------------------------------------------------------
    xlsx_out = OUTPUT_DIR / "band_selection_paper_style.xlsx"
    png_out = OUTPUT_DIR / "band_frequency.png"

    with pd.ExcelWriter(xlsx_out, engine="openpyxl") as writer:
        df_band.to_excel(writer, index=False, sheet_name="per_band_scores")
        top_avg.to_excel(writer, index=False, sheet_name="top_avg_combinations")
        top_min.to_excel(writer, index=False, sheet_name="top_min_combinations")
        freq_df.to_excel(writer, index=False, sheet_name="band_frequency")
        rec_df.to_excel(writer, index=False, sheet_name="recommended_bands")

    plot_frequency(freq_df, png_out)

    print("\n======================")
    print("Bandas recomendadas")
    print("======================")
    for _, row in rec_df.iterrows():
        print(
            f"- idx={int(row['band_idx']):3d} | "
            f"wl={row['wavelength_um']:.6f} um | "
            f"freq_total={int(row['freq_total'])}"
        )

    print("======================")
    print(f"[OK] Excel: {xlsx_out}")
    print(f"[OK] Plot : {png_out}")


if __name__ == "__main__":
    main()
