from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Iterable, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

from frost_core import ForecastGrid, NightResult
from map_boundaries import draw_brazil_state_boundaries, draw_state_labels


CITY_MARKERS = [
    ("Curitiba", -25.43, -49.27),
    ("Florianópolis", -27.59, -48.55),
    ("Porto Alegre", -30.03, -51.23),
    ("São Joaquim", -28.29, -49.93),
    ("Urupema", -27.95, -49.87),
    ("Vacaria", -28.51, -50.93),
    ("Caxias", -29.17, -51.18),
]


def waterfall_cmap(transparent_below: float = 0.02) -> LinearSegmentedColormap:
    # 0 is transparent; stronger risks resemble radio/waterfall colors.
    points = [
        (0.00, (0.0, 0.0, 0.0, 0.0)),
        (max(transparent_below, 0.001), (0.0, 0.0, 0.0, 0.0)),
        (0.12, (0.05, 0.10, 0.55, 0.35)),
        (0.25, (0.35, 0.00, 0.70, 0.48)),
        (0.40, (0.00, 0.75, 1.00, 0.58)),
        (0.58, (0.00, 0.95, 0.25, 0.68)),
        (0.75, (1.00, 0.95, 0.00, 0.78)),
        (0.90, (1.00, 0.12, 0.00, 0.88)),
        (1.00, (1.00, 1.00, 1.00, 0.96)),
    ]
    return LinearSegmentedColormap.from_list("frost_waterfall", points)


def _setup_axes(ax, grid: ForecastGrid) -> None:
    lon_min = float(grid.lons.min())
    lon_max = float(grid.lons.max())
    lat_min = float(grid.lats.min())
    lat_max = float(grid.lats.max())
    extent = (lon_min, lon_max, lat_min, lat_max)

    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_facecolor("#eef3f7")
    ax.grid(True, linewidth=0.35, alpha=0.35, zorder=0)

    # Political boundaries from IBGE GeoJSON, drawn without cartopy/geopandas.
    # This keeps the app light, but restores Brazilian state borders.
    boundary_status = draw_brazil_state_boundaries(ax, extent)
    draw_state_labels(ax, extent)

    for name, lat, lon in CITY_MARKERS:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            ax.scatter([lon], [lat], s=15, c="black", zorder=9)
            ax.text(lon + 0.08, lat + 0.08, name, fontsize=7, color="black", zorder=10)

    ax.text(
        0.01,
        0.01,
        boundary_status,
        transform=ax.transAxes,
        fontsize=7,
        color="#333333",
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.65, "pad": 2},
        zorder=20,
    )


def save_risk_map(
    grid: ForecastGrid,
    result: NightResult,
    output_dir: Path,
    transparent_below: float = 0.02,
    dpi: int = 150,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    lons, lats = np.meshgrid(grid.lons, grid.lats)
    risk_pct = result.risk * 100.0

    fig, ax = plt.subplots(figsize=(9.5, 8), constrained_layout=True)
    _setup_axes(ax, grid)
    cmap = waterfall_cmap(transparent_below=transparent_below)
    data = np.ma.masked_where(result.risk < transparent_below, result.risk)
    mesh = ax.pcolormesh(lons, lats, data, shading="auto", cmap=cmap, vmin=0, vmax=1)
    cbar = fig.colorbar(mesh, ax=ax, pad=0.02, shrink=0.86)
    cbar.set_label("Índice de risco de geada")
    cbar.set_ticks([0, 0.1, 0.3, 0.6, 0.8, 1.0])
    cbar.set_ticklabels(["0%", "10%", "30%", "60%", "80%", "100%"])

    ax.set_title(
        "Risco de geada\n"
        f"Noite {result.window_start_local:%d/%m/%Y %Hh} → {result.window_end_local:%d/%m/%Y %Hh} BRT | "
        f"máx {np.nanmax(risk_pct):.0f}% | mín temp {np.nanmin(result.min_temp_c):.1f} °C"
    )
    out = output_dir / f"geada_risco_{result.night_date:%Y%m%d}.png"
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def save_metric_map(
    grid: ForecastGrid,
    result: NightResult,
    output_dir: Path,
    metric: str,
    dpi: int = 150,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    lons, lats = np.meshgrid(grid.lons, grid.lats)
    options = {
        "temp_min": (result.min_temp_c, "Temperatura mínima (°C)", "coolwarm_r"),
        "dew_min": (result.min_dewpoint_c, "Ponto de orvalho mínimo (°C)", "PuBu_r"),
        "rh_max": (result.max_rh_pct, "Umidade máxima (%)", "YlGnBu"),
        "wind_min": (result.min_wind_ms, "Vento mínimo (m/s)", "viridis"),
        "cloud_mean": (result.mean_cloud_pct, "Nebulosidade média (%)", "Greys"),
    }
    if metric not in options:
        raise KeyError(metric)
    data, label, cmap = options[metric]

    fig, ax = plt.subplots(figsize=(9.5, 8), constrained_layout=True)
    _setup_axes(ax, grid)
    mesh = ax.pcolormesh(lons, lats, data, shading="auto", cmap=cmap)
    cbar = fig.colorbar(mesh, ax=ax, pad=0.02, shrink=0.86)
    cbar.set_label(label)
    ax.set_title(f"{label}\nNoite {result.window_start_local:%d/%m/%Y %Hh} → {result.window_end_local:%d/%m/%Y %Hh} BRT")
    out = output_dir / f"{metric}_{result.night_date:%Y%m%d}.png"
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def save_csv(grid: ForecastGrid, result: NightResult, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"geada_dados_{result.night_date:%Y%m%d}.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "night_date",
            "lat",
            "lon",
            "risk_index",
            "risk_percent",
            "min_temp_c",
            "min_dewpoint_c",
            "max_rh_pct",
            "min_wind_ms",
            "mean_cloud_pct",
            "max_risk_hour_brt",
        ])
        for iy, lat in enumerate(grid.lats):
            for ix, lon in enumerate(grid.lons):
                writer.writerow([
                    result.night_date.isoformat(),
                    f"{lat:.5f}",
                    f"{lon:.5f}",
                    f"{result.risk[iy, ix]:.4f}",
                    f"{result.risk[iy, ix] * 100:.1f}",
                    f"{result.min_temp_c[iy, ix]:.2f}",
                    f"{result.min_dewpoint_c[iy, ix]:.2f}",
                    f"{result.max_rh_pct[iy, ix]:.1f}",
                    f"{result.min_wind_ms[iy, ix]:.2f}",
                    f"{result.mean_cloud_pct[iy, ix]:.1f}",
                    result.max_risk_hour_local[iy, ix],
                ])
    return out


def save_summary(results: List[NightResult], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "resumo_geada.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["night_date", "window", "max_risk_percent", "mean_risk_percent", "min_temp_c", "available_hours"])
        for r in results:
            writer.writerow([
                r.night_date.isoformat(),
                f"{r.window_start_local:%d/%m %Hh} -> {r.window_end_local:%d/%m %Hh}",
                f"{r.max_risk * 100:.1f}",
                f"{r.mean_risk * 100:.1f}",
                f"{r.min_temp:.2f}",
                r.available_hours,
            ])
    return out


def save_all_outputs(
    grid: ForecastGrid,
    results: List[NightResult],
    output_dir: Path,
    transparent_below: float = 0.02,
    include_metric_maps: bool = True,
) -> List[Path]:
    paths: List[Path] = []
    for result in results:
        paths.append(save_risk_map(grid, result, output_dir, transparent_below=transparent_below))
        paths.append(save_csv(grid, result, output_dir))
        if include_metric_maps:
            for metric in ["temp_min", "dew_min", "rh_max", "wind_min", "cloud_mean"]:
                paths.append(save_metric_map(grid, result, output_dir, metric=metric))
    paths.append(save_summary(results, output_dir))
    return paths
