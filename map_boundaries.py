from __future__ import annotations

"""Simple political-boundary overlay for Matplotlib maps.

This module intentionally avoids heavy GIS dependencies (cartopy/geopandas/shapely)
so the app remains easy to run and package with PyInstaller.

It downloads Brazil state boundaries from the IBGE geographic mesh API once and
caches the GeoJSON locally. If the download fails, plotting continues without
boundaries instead of crashing the forecast generation.
"""

import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Sequence, Tuple

import requests


# The /paises/BR endpoint with resolucao=2 returns the national mesh including
# state-level political divisions. The /estados endpoint is kept as fallback.
IBGE_BOUNDARY_URLS = [
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&resolucao=2&qualidade=intermediaria",
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&resolucao=2&qualidade=minima",
    "https://servicodados.ibge.gov.br/api/v3/malhas/estados?formato=application/vnd.geo+json&qualidade=intermediaria",
    "https://servicodados.ibge.gov.br/api/v3/malhas/estados?formato=application/vnd.geo+json&qualidade=minima",
]

STATE_LABELS = {
    "PR": (-24.7, -51.5),
    "SC": (-27.3, -50.7),
    "RS": (-30.2, -53.2),
    "SP": (-22.7, -48.7),
    "MS": (-20.7, -54.6),
}


def _cache_file() -> Path:
    cache_dir = Path.cwd() / "cache" / "geodata"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "ibge_brazil_states_res2.geojson"


def _looks_like_geojson(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    typ = payload.get("type")
    return typ in {"FeatureCollection", "Feature", "Polygon", "MultiPolygon", "GeometryCollection"}


def get_ibge_boundaries(force_download: bool = False, timeout: float = 12.0) -> Tuple[Optional[dict], str]:
    """Return cached/downloaded Brazil political boundaries.

    Returns
    -------
    (geojson, status)
        geojson is None when unavailable. status is a user-readable message.
    """
    path = _cache_file()
    if path.exists() and not force_download:
        try:
            return json.loads(path.read_text(encoding="utf-8")), "Divisas políticas: cache IBGE"
        except Exception:
            # Corrupt cache; remove and try downloading.
            try:
                path.unlink()
            except Exception:
                pass

    last_error = ""
    headers = {"User-Agent": "FrostForecasterSimple/2.0"}
    for url in IBGE_BOUNDARY_URLS:
        try:
            r = requests.get(url, timeout=timeout, headers=headers)
            r.raise_for_status()
            payload = r.json()
            if _looks_like_geojson(payload):
                path.write_text(json.dumps(payload), encoding="utf-8")
                return payload, "Divisas políticas: IBGE"
            last_error = "resposta não parece GeoJSON"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
    return None, f"Divisas políticas indisponíveis ({last_error})"


def _iter_geometries(obj: Any) -> Iterator[dict]:
    if not isinstance(obj, dict):
        return
    typ = obj.get("type")
    if typ == "FeatureCollection":
        for feat in obj.get("features", []) or []:
            geom = feat.get("geometry") if isinstance(feat, dict) else None
            if geom:
                yield from _iter_geometries(geom)
    elif typ == "Feature":
        geom = obj.get("geometry")
        if geom:
            yield from _iter_geometries(geom)
    elif typ == "GeometryCollection":
        for geom in obj.get("geometries", []) or []:
            yield from _iter_geometries(geom)
    elif typ in {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}:
        yield obj


def _ring_inside_extent(ring: Sequence[Sequence[float]], extent: Tuple[float, float, float, float], margin: float = 1.0) -> bool:
    lon_min, lon_max, lat_min, lat_max = extent
    lon_min -= margin
    lon_max += margin
    lat_min -= margin
    lat_max += margin
    try:
        xs = [float(p[0]) for p in ring]
        ys = [float(p[1]) for p in ring]
    except Exception:
        return False
    return not (max(xs) < lon_min or min(xs) > lon_max or max(ys) < lat_min or min(ys) > lat_max)


def _plot_ring(ax, ring: Sequence[Sequence[float]], extent, *, color: str, linewidth: float, alpha: float, zorder: int) -> int:
    if not ring or not _ring_inside_extent(ring, extent):
        return 0
    xs = [float(p[0]) for p in ring]
    ys = [float(p[1]) for p in ring]
    ax.plot(xs, ys, color=color, linewidth=linewidth, alpha=alpha, zorder=zorder)
    return 1


def draw_brazil_state_boundaries(
    ax,
    extent: Tuple[float, float, float, float],
    *,
    color: str = "#242424",
    linewidth: float = 0.55,
    alpha: float = 0.82,
    zorder: int = 4,
) -> str:
    """Draw Brazilian state boundaries on an existing lat/lon Matplotlib axis.

    The function never raises for network/cache problems; it returns a status
    string that can be displayed on the plot.
    """
    geojson, status = get_ibge_boundaries()
    if not geojson:
        return status

    n = 0
    for geom in _iter_geometries(geojson):
        typ = geom.get("type")
        coords = geom.get("coordinates") or []
        if typ == "Polygon":
            for ring in coords:
                n += _plot_ring(ax, ring, extent, color=color, linewidth=linewidth, alpha=alpha, zorder=zorder)
        elif typ == "MultiPolygon":
            for polygon in coords:
                for ring in polygon:
                    n += _plot_ring(ax, ring, extent, color=color, linewidth=linewidth, alpha=alpha, zorder=zorder)
        elif typ == "LineString":
            n += _plot_ring(ax, coords, extent, color=color, linewidth=linewidth, alpha=alpha, zorder=zorder)
        elif typ == "MultiLineString":
            for line in coords:
                n += _plot_ring(ax, line, extent, color=color, linewidth=linewidth, alpha=alpha, zorder=zorder)

    if n == 0:
        return "Divisas políticas: fora do recorte ou não desenhadas"
    return status


def draw_state_labels(ax, extent: Tuple[float, float, float, float]) -> None:
    lon_min, lon_max, lat_min, lat_max = extent
    for uf, (lat, lon) in STATE_LABELS.items():
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            ax.text(
                lon,
                lat,
                uf,
                fontsize=9,
                fontweight="bold",
                color="#111111",
                ha="center",
                va="center",
                zorder=8,
                bbox={"boxstyle": "round,pad=0.15", "facecolor": "white", "edgecolor": "none", "alpha": 0.65},
            )
