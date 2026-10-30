"""Builds Clarity's Cyprus data files from Copernicus Marine Service data.

Writes to --out:
  waves.json             Med-Waves forecast (~4 km, hourly) for sea cells near the coast,
                         from 00:00 UTC yesterday to four days ahead.
  clarity.json           Satellite water clarity (Kd490, ~1 km) for pixels just off the coast:
                         a typical clear-water value for each month, plus the latest reading.
  clarity_baseline.json  Cache of the monthly values, rebuilt every BASELINE_MAX_AGE_DAYS.

Output only changes when the source data changes, so running this hourly is cheap.
Credentials come from COPERNICUSMARINE_SERVICE_USERNAME / COPERNICUSMARINE_SERVICE_PASSWORD
or a prior `copernicusmarine login`.
"""

import argparse
import calendar
import datetime as dt
import json
import pathlib
import warnings

import copernicusmarine as cm
import numpy as np

# A box around Cyprus, including the Karpas peninsula.
BOX = dict(minimum_latitude=34.3, maximum_latitude=35.9, minimum_longitude=31.9, maximum_longitude=34.8)

WAVES_DATASET = "cmems_mod_med_wav_anfc_4.2km_PT1H-i"
KD_HISTORY_DATASET = "cmems_obs-oc_med_bgc-transp_my_l3-multi-1km_P1D"
KD_RECENT_DATASET = "cmems_obs-oc_med_bgc-transp_nrt_l3-multi-1km_P1D"

WAVE_DAYS = 5               # yesterday, today and three days ahead
WAVE_COAST_CELLS = 2        # keep wave cells within ~8 km of land
KD_COAST_PIXELS = 4         # keep satellite pixels within ~4 km of land...
KD_SKIP_PIXELS = 1          # ...but not those right against it, where land and seabed skew readings
KD_RECENT_DAYS = 5          # look this far back for the latest cloud-free reading
KD_SCALE = 10_000           # Kd490 is stored as an integer in units of 0.0001 m⁻¹
BASELINE_YEARS = 5
BASELINE_PERCENTILE = 20    # a "clear day" is clearer than 80% of days in that month
BASELINE_MIN_DAYS = 5       # fewer cloud-free days than this and the month is left empty
BASELINE_MAX_AGE_DAYS = 30

ATTRIBUTION = "Generated using E.U. Copernicus Marine Service Information"


def near(mask: np.ndarray, cells: int) -> np.ndarray:
    """Cells within `cells` steps (up, down, left, right) of a True cell in `mask`."""
    out = mask.copy()
    for _ in range(cells):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def ints(values: np.ndarray, scale: float) -> list:
    return [int(round(float(v) * scale)) if np.isfinite(v) else None for v in values]


def iso(t) -> str:
    return np.datetime_as_string(np.datetime64(t, "s"), unit="s") + "Z"


def build_waves(today: dt.date) -> dict:
    start = dt.datetime.combine(today - dt.timedelta(days=1), dt.time())
    end = start + dt.timedelta(days=WAVE_DAYS) - dt.timedelta(hours=1)
    ds = cm.open_dataset(
        dataset_id=WAVES_DATASET,
        variables=["VHM0", "VTM10", "VMDR"],
        start_datetime=start.isoformat(),
        end_datetime=end.isoformat(),
        **BOX,
    ).load()
    times = ds["time"].values
    if len(times) > 1 and not np.all(np.diff(times) == np.timedelta64(1, "h")):
        raise ValueError("Wave data is not hourly")

    height, period, direction = (ds[v].values for v in ("VHM0", "VTM10", "VMDR"))
    sea = np.isfinite(height).any(axis=0)
    coastal = sea & near(~sea, WAVE_COAST_CELLS)
    lat, lon = ds["latitude"].values, ds["longitude"].values

    cells = [
        {
            "lat": round(float(lat[i]), 4),
            "lon": round(float(lon[j]), 4),
            "h": ints(height[:, i, j], 100),
            "t": ints(period[:, i, j], 10),
            "d": ints(direction[:, i, j], 1),
        }
        for i, j in zip(*np.nonzero(coastal))
    ]
    return {
        "attribution": ATTRIBUTION,
        "dataset": WAVES_DATASET,
        "start": iso(times[0]),
        "hours": len(times),
        "units": {"h": "cm, significant wave height", "t": "0.1 s, mean period Tm-10", "d": "degrees, mean direction from"},
        "cells": cells,
    }


def build_baseline(today: dt.date) -> dict:
    """Typical clear-water Kd490 per calendar month for coastal pixels, from recent full years."""
    years = list(range(today.year - BASELINE_YEARS, today.year))
    by_month: dict[int, list[np.ndarray]] = {m: [] for m in range(1, 13)}
    lat = lon = None
    for year in years:
        for month in range(1, 13):
            last_day = calendar.monthrange(year, month)[1]
            ds = cm.open_dataset(
                dataset_id=KD_HISTORY_DATASET,
                variables=["KD490"],
                start_datetime=f"{year}-{month:02d}-01T00:00:00",
                end_datetime=f"{year}-{month:02d}-{last_day}T23:59:59",
                **BOX,
            )
            by_month[month].append(ds["KD490"].values.astype(np.float32))
            lat, lon = ds["latitude"].values, ds["longitude"].values
            print(f"  baseline {year}-{month:02d}", flush=True)

    monthly = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN pixels (land, or always cloudy)
        for month in range(1, 13):
            stack = np.concatenate(by_month[month], axis=0)
            value = np.nanpercentile(stack, BASELINE_PERCENTILE, axis=0)
            value[np.isfinite(stack).sum(axis=0) < BASELINE_MIN_DAYS] = np.nan
            monthly.append(value)
    monthly = np.stack(monthly)  # (month, lat, lon)

    # Pixels that never have a valid reading are land (or flagged as too close to it).
    sea = np.isfinite(monthly).any(axis=0)
    land = ~sea
    band = sea & near(land, KD_COAST_PIXELS) & ~near(land, KD_SKIP_PIXELS)
    pixels = [
        {"lat": round(float(lat[i]), 4), "lon": round(float(lon[j]), 4), "kd": ints(monthly[:, i, j], KD_SCALE)}
        for i, j in zip(*np.nonzero(band))
    ]
    return {
        "built": today.isoformat(),
        "dataset": KD_HISTORY_DATASET,
        "years": years,
        "percentile": BASELINE_PERCENTILE,
        "pixels": pixels,
    }


def build_clarity(today: dt.date, baseline: dict) -> dict:
    start = today - dt.timedelta(days=KD_RECENT_DAYS)
    ds = cm.open_dataset(
        dataset_id=KD_RECENT_DATASET,
        variables=["KD490"],
        start_datetime=f"{start.isoformat()}T00:00:00",
        end_datetime=f"{today.isoformat()}T23:59:59",
        **BOX,
    ).load()
    kd = ds["KD490"].values
    dates = [np.datetime_as_string(t, unit="D") for t in ds["time"].values]
    lat, lon = ds["latitude"].values, ds["longitude"].values

    pixels = []
    for pixel in baseline["pixels"]:
        i, j = int(np.abs(lat - pixel["lat"]).argmin()), int(np.abs(lon - pixel["lon"]).argmin())
        recent = None
        for k in reversed(range(len(dates))):
            if np.isfinite(kd[k, i, j]):
                recent = {"date": dates[k], "kd": int(round(float(kd[k, i, j]) * KD_SCALE))}
                break
        pixels.append({**pixel, "recent": recent})
    return {
        "attribution": ATTRIBUTION,
        "datasets": {"monthly": baseline["dataset"], "recent": KD_RECENT_DATASET},
        "years": baseline["years"],
        "percentile": baseline["percentile"],
        "units": {"kd": f"1/{KD_SCALE} per metre, diffuse attenuation at 490 nm"},
        "pixels": pixels,
    }


def write_if_changed(path: pathlib.Path, data: dict) -> bool:
    text = json.dumps(data, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--only", choices=["waves", "clarity"], help="build just one file")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    today = dt.datetime.now(dt.timezone.utc).date()

    if args.only in (None, "waves"):
        changed = write_if_changed(args.out / "waves.json", build_waves(today))
        print(f"waves.json {'updated' if changed else 'unchanged'}")

    if args.only in (None, "clarity"):
        baseline_path = args.out / "clarity_baseline.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else None
        if baseline is None or (today - dt.date.fromisoformat(baseline["built"])).days > BASELINE_MAX_AGE_DAYS:
            print("Rebuilding monthly clarity baseline (this takes a while)...")
            baseline = build_baseline(today)
            write_if_changed(baseline_path, baseline)
        changed = write_if_changed(args.out / "clarity.json", build_clarity(today, baseline))
        print(f"clarity.json {'updated' if changed else 'unchanged'}")


if __name__ == "__main__":
    main()
