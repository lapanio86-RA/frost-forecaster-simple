from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

Progress = Optional[Callable[[str], None]]


@dataclass(frozen=True)
class Domain:
    key: str
    name: str
    lat_south: float
    lat_north: float
    lon_west: float
    lon_east: float
    recommended_step: float


DOMAINS: Dict[str, Domain] = {
    "south_core": Domain(
        key="south_core",
        name="Sul core - PR/SC/RS (recomendado)",
        lat_south=-34.0,
        lat_north=-22.0,
        lon_west=-58.5,
        lon_east=-48.0,
        recommended_step=0.5,
    ),
    "serra": Domain(
        key="serra",
        name="Serra SC/RS - alta resolução",
        lat_south=-30.8,
        lat_north=-26.0,
        lon_west=-53.5,
        lon_east=-48.5,
        recommended_step=0.25,
    ),
    "south_wide": Domain(
        key="south_wide",
        name="Sul ampliado + entorno",
        lat_south=-35.0,
        lat_north=-20.0,
        lon_west=-61.0,
        lon_east=-46.0,
        recommended_step=0.75,
    ),
}


@dataclass
class ForecastGrid:
    source: str
    domain: Domain
    grid_step: float
    lats: np.ndarray
    lons: np.ndarray
    times_utc: pd.DatetimeIndex
    temp_c: np.ndarray          # (time, lat, lon)
    rh_pct: np.ndarray          # (time, lat, lon)
    dewpoint_c: np.ndarray      # (time, lat, lon)
    wind_ms: np.ndarray         # (time, lat, lon)
    cloud_pct: np.ndarray       # (time, lat, lon)


@dataclass
class NightResult:
    night_date: dt.date
    window_start_local: pd.Timestamp
    window_end_local: pd.Timestamp
    risk: np.ndarray
    min_temp_c: np.ndarray
    min_dewpoint_c: np.ndarray
    max_rh_pct: np.ndarray
    min_wind_ms: np.ndarray
    mean_cloud_pct: np.ndarray
    max_risk_hour_local: np.ndarray
    available_hours: int

    @property
    def max_risk(self) -> float:
        return float(np.nanmax(self.risk)) if np.isfinite(self.risk).any() else float("nan")

    @property
    def mean_risk(self) -> float:
        return float(np.nanmean(self.risk)) if np.isfinite(self.risk).any() else float("nan")

    @property
    def min_temp(self) -> float:
        return float(np.nanmin(self.min_temp_c)) if np.isfinite(self.min_temp_c).any() else float("nan")


def _log(progress: Progress, msg: str) -> None:
    if progress:
        progress(msg)


def make_grid(domain: Domain, step: float) -> Tuple[np.ndarray, np.ndarray]:
    """Create a regular lat/lon grid with inclusive endpoints."""
    if step <= 0:
        raise ValueError("A resolução precisa ser maior que zero.")
    lats = np.round(np.arange(domain.lat_south, domain.lat_north + step * 0.5, step), 5)
    lons = np.round(np.arange(domain.lon_west, domain.lon_east + step * 0.5, step), 5)
    return lats, lons


def _cache_dir() -> Path:
    root = Path.cwd() / "cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_key(domain: Domain, step: float, forecast_days: int) -> Path:
    today = dt.date.today().isoformat()
    raw = f"openmeteo|{today}|{domain.key}|{step}|{forecast_days}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return _cache_dir() / f"forecast_{domain.key}_{step:g}_{forecast_days}d_{today}_{digest}.npz"


def _save_npz(path: Path, grid: ForecastGrid) -> None:
    np.savez_compressed(
        path,
        source=grid.source,
        domain_key=grid.domain.key,
        grid_step=grid.grid_step,
        lats=grid.lats,
        lons=grid.lons,
        times_utc=grid.times_utc.astype("datetime64[ns]").values,
        temp_c=grid.temp_c,
        rh_pct=grid.rh_pct,
        dewpoint_c=grid.dewpoint_c,
        wind_ms=grid.wind_ms,
        cloud_pct=grid.cloud_pct,
    )


def _load_npz(path: Path, domain: Domain) -> ForecastGrid:
    data = np.load(path, allow_pickle=True)
    return ForecastGrid(
        source=str(data["source"]),
        domain=domain,
        grid_step=float(data["grid_step"]),
        lats=data["lats"],
        lons=data["lons"],
        times_utc=pd.DatetimeIndex(data["times_utc"]),
        temp_c=data["temp_c"],
        rh_pct=data["rh_pct"],
        dewpoint_c=data["dewpoint_c"],
        wind_ms=data["wind_ms"],
        cloud_pct=data["cloud_pct"],
    )


def _chunked(seq: List[Tuple[float, float]], size: int) -> Iterable[List[Tuple[float, float]]]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _request_openmeteo_batch(
    session: requests.Session,
    points: List[Tuple[float, float]],
    forecast_days: int,
    retries: int = 6,
    progress: Progress = None,
) -> List[dict]:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": ",".join(f"{lat:.5f}" for lat, _ in points),
        "longitude": ",".join(f"{lon:.5f}" for _, lon in points),
        "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m,cloud_cover",
        "timezone": "UTC",
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "forecast_days": int(forecast_days),
    }

    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, params=params, timeout=90)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait_s = float(retry_after) if retry_after else min(90.0, 10.0 * attempt)
                _log(progress, f"Limite da API atingido. Aguardando {wait_s:.0f}s e tentando de novo...")
                time.sleep(wait_s)
                continue
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                payload = [payload]
            return payload
        except Exception as exc:  # noqa: BLE001 - user-facing retry
            last_error = exc
            wait_s = min(60.0, 2.0 * attempt)
            _log(progress, f"Falha na consulta ({attempt}/{retries}): {exc}. Nova tentativa em {wait_s:.0f}s...")
            time.sleep(wait_s)
    raise RuntimeError(f"Falha ao consultar Open-Meteo após {retries} tentativas: {last_error}")


def _forecast_days_needed(start_date: dt.date, nights: int) -> int:
    today = dt.datetime.now().date()
    last_needed = start_date + dt.timedelta(days=max(0, nights))
    days = (last_needed - today).days + 2
    return int(max(1, min(16, days)))


def fetch_openmeteo_grid(
    domain: Domain,
    grid_step: float,
    start_date: dt.date,
    nights: int,
    batch_size: int = 20,
    pause_between_batches: float = 1.0,
    use_cache: bool = True,
    progress: Progress = None,
) -> ForecastGrid:
    """Fetch hourly forecast for a regular grid using Open-Meteo.

    This is intentionally conservative: smaller batches and a pause between
    batches reduce HTTP 429 errors and make it usable from a normal home IP.
    """
    forecast_days = _forecast_days_needed(start_date, nights)
    lats, lons = make_grid(domain, grid_step)
    cache_path = _cache_key(domain, grid_step, forecast_days)
    if use_cache and cache_path.exists():
        _log(progress, f"Usando cache: {cache_path.name}")
        return _load_npz(cache_path, domain)

    points = [(float(lat), float(lon)) for lat in lats for lon in lons]
    ny, nx = len(lats), len(lons)
    _log(progress, f"Consultando Open-Meteo: {len(points)} pontos, resolução {grid_step:g}°, {forecast_days} dias.")

    session = requests.Session()
    session.headers.update({"User-Agent": "FrostForecasterSimple/1.0"})

    all_items: List[dict] = []
    chunks = list(_chunked(points, batch_size))
    for idx, chunk in enumerate(chunks, start=1):
        a = (idx - 1) * batch_size + 1
        b = min(idx * batch_size, len(points))
        _log(progress, f"Baixando lote {idx}/{len(chunks)} ({a}-{b} de {len(points)})...")
        items = _request_openmeteo_batch(session, chunk, forecast_days, progress=progress)
        all_items.extend(items)
        if idx < len(chunks):
            time.sleep(pause_between_batches)

    if not all_items:
        raise RuntimeError("A API retornou zero pontos.")

    first_hourly = all_items[0].get("hourly") or {}
    times = pd.to_datetime(first_hourly.get("time"), utc=True).tz_convert(None)
    nt = len(times)
    if nt == 0:
        raise RuntimeError("A API não retornou horas de previsão.")

    def blank() -> np.ndarray:
        return np.full((nt, ny, nx), np.nan, dtype=float)

    temp_c = blank()
    rh_pct = blank()
    dewpoint_c = blank()
    wind_ms = blank()
    cloud_pct = blank()

    variable_map = {
        "temperature_2m": temp_c,
        "relative_humidity_2m": rh_pct,
        "dew_point_2m": dewpoint_c,
        "wind_speed_10m": wind_ms,
        "cloud_cover": cloud_pct,
    }

    for pidx, item in enumerate(all_items):
        iy = pidx // nx
        ix = pidx % nx
        hourly = item.get("hourly") or {}
        for name, arr in variable_map.items():
            vals = np.array(hourly.get(name, [np.nan] * nt), dtype=float)
            if len(vals) != nt:
                vals = np.resize(vals, nt)
            arr[:, iy, ix] = vals

    grid = ForecastGrid(
        source="Open-Meteo",
        domain=domain,
        grid_step=grid_step,
        lats=lats,
        lons=lons,
        times_utc=times,
        temp_c=temp_c,
        rh_pct=rh_pct,
        dewpoint_c=dewpoint_c,
        wind_ms=wind_ms,
        cloud_pct=cloud_pct,
    )
    if use_cache:
        _save_npz(cache_path, grid)
        _log(progress, f"Cache salvo: {cache_path.name}")
    return grid


def make_demo_grid(domain: Domain, grid_step: float, start_date: dt.date, nights: int) -> ForecastGrid:
    """Synthetic, deterministic data for offline testing."""
    lats, lons = make_grid(domain, grid_step)
    forecast_days = _forecast_days_needed(start_date, nights)
    start_utc = pd.Timestamp(dt.datetime.combine(dt.date.today(), dt.time(0, 0)))
    times = pd.date_range(start=start_utc, periods=forecast_days * 24, freq="h")
    nt, ny, nx = len(times), len(lats), len(lons)
    lon2, lat2 = np.meshgrid(lons, lats)

    temp_c = np.empty((nt, ny, nx), dtype=float)
    rh_pct = np.empty_like(temp_c)
    dewpoint_c = np.empty_like(temp_c)
    wind_ms = np.empty_like(temp_c)
    cloud_pct = np.empty_like(temp_c)

    # Colder around the highlands. This is only for UI/offline testing.
    highland = np.exp(-(((lat2 + 28.3) / 2.4) ** 2 + ((lon2 + 50.4) / 2.8) ** 2))
    southness = np.clip((-lat2 - 22) / 12, 0, 1)

    for i, ts in enumerate(times):
        local_hour = (ts.hour - 3) % 24
        night_cycle = math.cos((local_hour - 5) / 24 * 2 * math.pi)
        diurnal = -3.8 * night_cycle
        synoptic = -1.5 * math.sin(i / 20)
        temp_c[i] = 9.0 - 9.0 * highland - 3.0 * southness + diurnal + synoptic
        rh_pct[i] = np.clip(76 + 20 * highland + 8 * night_cycle - 0.45 * temp_c[i], 30, 100)
        dewpoint_c[i] = temp_c[i] - (100 - rh_pct[i]) / 5.0
        wind_ms[i] = np.clip(2.0 + 2.0 * np.sin(i / 9 + lon2) - 1.1 * highland, 0.2, 8.0)
        cloud_pct[i] = np.clip(35 + 25 * np.sin(i / 11 + lat2 / 4) - 25 * highland, 0, 100)

    return ForecastGrid(
        source="Demo offline",
        domain=domain,
        grid_step=grid_step,
        lats=lats,
        lons=lons,
        times_utc=times,
        temp_c=temp_c,
        rh_pct=rh_pct,
        dewpoint_c=dewpoint_c,
        wind_ms=wind_ms,
        cloud_pct=cloud_pct,
    )


def _risk_hourly(temp_c: np.ndarray, rh_pct: np.ndarray, dewpoint_c: np.ndarray, wind_ms: np.ndarray, cloud_pct: np.ndarray) -> np.ndarray:
    """Heuristic frost-risk index, 0..1.

    This is not a statistically calibrated probability. It is a meteorological
    risk index based on cold temperature, near-saturation/dew point, weak wind,
    and low cloud cover during the night.
    """
    temp_factor = np.clip((5.0 - temp_c) / 7.0, 0, 1)
    dew_factor = np.clip((3.0 - dewpoint_c) / 7.0, 0, 1)
    rh_factor = np.clip((rh_pct - 70.0) / 30.0, 0, 1)
    moisture_factor = np.clip(0.55 * rh_factor + 0.45 * dew_factor, 0, 1)
    wind_factor = np.clip((4.0 - wind_ms) / 4.0, 0, 1)
    cloud_factor = np.clip((80.0 - cloud_pct) / 80.0, 0, 1)

    risk = temp_factor * moisture_factor * wind_factor * cloud_factor
    return np.clip(risk, 0, 1)


def compute_night_result(
    grid: ForecastGrid,
    night_date: dt.date,
    start_hour: int = 18,
    end_hour: int = 9,
    local_utc_offset_hours: int = -3,
) -> NightResult:
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
        raise ValueError("Horas da janela precisam estar entre 0 e 23.")

    start_local = pd.Timestamp(dt.datetime.combine(night_date, dt.time(start_hour, 0)))
    end_date = night_date if end_hour > start_hour else night_date + dt.timedelta(days=1)
    end_local = pd.Timestamp(dt.datetime.combine(end_date, dt.time(end_hour, 0)))
    local_times = grid.times_utc + pd.Timedelta(hours=local_utc_offset_hours)
    mask = (local_times >= start_local) & (local_times <= end_local)
    idx = np.where(mask)[0]
    if len(idx) == 0:
        raise RuntimeError(
            f"Não há horas de previsão para a janela {start_local:%d/%m %Hh} -> {end_local:%d/%m %Hh}. "
            "Escolha uma data dentro dos próximos dias de previsão."
        )

    t = grid.temp_c[idx]
    rh = grid.rh_pct[idx]
    dew = grid.dewpoint_c[idx]
    wind = grid.wind_ms[idx]
    cloud = grid.cloud_pct[idx]
    risk_h = _risk_hourly(t, rh, dew, wind, cloud)
    risk = np.nanmax(risk_h, axis=0)

    argmax = np.nanargmax(np.where(np.isfinite(risk_h), risk_h, -1), axis=0)
    selected_local_times = local_times[idx]
    hour_grid = np.empty(risk.shape, dtype=object)
    for iy in range(risk.shape[0]):
        for ix in range(risk.shape[1]):
            hour_grid[iy, ix] = selected_local_times[int(argmax[iy, ix])].strftime("%d/%m %Hh")

    return NightResult(
        night_date=night_date,
        window_start_local=start_local,
        window_end_local=end_local,
        risk=risk,
        min_temp_c=np.nanmin(t, axis=0),
        min_dewpoint_c=np.nanmin(dew, axis=0),
        max_rh_pct=np.nanmax(rh, axis=0),
        min_wind_ms=np.nanmin(wind, axis=0),
        mean_cloud_pct=np.nanmean(cloud, axis=0),
        max_risk_hour_local=hour_grid,
        available_hours=len(idx),
    )


def compute_multiple_nights(
    grid: ForecastGrid,
    start_date: dt.date,
    nights: int,
    start_hour: int = 18,
    end_hour: int = 9,
) -> List[NightResult]:
    results: List[NightResult] = []
    for offset in range(nights):
        night = start_date + dt.timedelta(days=offset)
        results.append(compute_night_result(grid, night, start_hour=start_hour, end_hour=end_hour))
    return results
