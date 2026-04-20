"""
data_pipeline.py
================
Phase 1 – The Cartographer

Fetches the Sasolburg → Zeerust route (OSRM) and elevation (Open-Elevation),
saves a CSV with GPS coords, altitude, bearing, and slope.

Spatial resolution: 500 m  (see README for justification).
Falls back to a realistic synthetic route when network is unavailable.
"""

import os
import time
import requests
import numpy as np
import pandas as pd

from constants import (
    SASOLBURG, ZEERUST, RESOLUTION_M,
)

OUTPUT_CSV = "data/route_data.csv"
OSRM_URL   = "http://router.project-osrm.org/route/v1/driving"
ELEV_URL   = "https://api.open-elevation.com/api/v1/lookup"


# ─────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────────────────────────────────────

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    φ1, φ2 = np.radians(lat1), np.radians(lat2)
    dφ = np.radians(lat2 - lat1)
    dλ = np.radians(lon2 - lon1)
    a  = np.sin(dφ/2)**2 + np.cos(φ1)*np.cos(φ2)*np.sin(dλ/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    φ1, φ2 = np.radians(lat1), np.radians(lat2)
    dλ = np.radians(lon2 - lon1)
    x  = np.sin(dλ) * np.cos(φ2)
    y  = np.cos(φ1)*np.sin(φ2) - np.sin(φ1)*np.cos(φ2)*np.cos(dλ)
    return (np.degrees(np.arctan2(x, y)) + 360) % 360


def subsample(coords, total_dist_m):
    """Resample polyline to RESOLUTION_M spacing."""
    n_target = max(int(total_dist_m / RESOLUTION_M) + 1, 2)
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + haversine_m(
            coords[i-1][0], coords[i-1][1],
            coords[i][0],   coords[i][1]))
    total  = cum[-1]
    targs  = np.linspace(0, total, n_target)
    result = []
    j = 0
    for t in targs:
        while j < len(cum)-1 and cum[j+1] < t:
            j += 1
        if j >= len(coords)-1:
            result.append(coords[-1]); continue
        f = (t - cum[j]) / max(cum[j+1] - cum[j], 1e-9)
        result.append((
            coords[j][0] + f*(coords[j+1][0]-coords[j][0]),
            coords[j][1] + f*(coords[j+1][1]-coords[j][1]),
        ))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# OSRM route fetch
# ─────────────────────────────────────────────────────────────────────────────

def fetch_route_osrm():
    lon1, lat1 = SASOLBURG[1], SASOLBURG[0]
    lon2, lat2 = ZEERUST[1],   ZEERUST[0]
    url = (f"{OSRM_URL}/{lon1},{lat1};{lon2},{lat2}"
           f"?overview=full&geometries=geojson&steps=false")
    print(f"[OSRM] Requesting route …")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data       = r.json()
    coords_raw = data["routes"][0]["geometry"]["coordinates"]
    total_dist = data["routes"][0]["distance"]
    print(f"[OSRM] {total_dist/1000:.1f} km  |  {len(coords_raw)} raw points")
    coords = [(c[1], c[0]) for c in coords_raw]
    return subsample(coords, total_dist)


# ─────────────────────────────────────────────────────────────────────────────
# Open-Elevation batch fetch
# ─────────────────────────────────────────────────────────────────────────────

def fetch_elevations(coords, batch=100):
    elevs = []
    for start in range(0, len(coords), batch):
        chunk   = coords[start:start+batch]
        payload = {"locations": [{"latitude": la, "longitude": lo} for la,lo in chunk]}
        for attempt in range(3):
            try:
                r = requests.post(ELEV_URL, json=payload, timeout=60)
                r.raise_for_status()
                elevs.extend([res["elevation"] for res in r.json()["results"]])
                print(f"[Elevation] {min(start+batch, len(coords))}/{len(coords)}")
                break
            except Exception as e:
                print(f"[Elevation] attempt {attempt+1} failed: {e}")
                time.sleep(3)
        else:
            elevs.extend([None]*len(chunk))
    arr = np.array([e if e is not None else np.nan for e in elevs], dtype=float)
    nans = np.isnan(arr)
    if nans.any():
        idx = np.arange(len(arr))
        arr[nans] = np.interp(idx[nans], idx[~nans], arr[~nans])
    return arr


# ─────────────────────────────────────────────────────────────────────────────
# Realistic synthetic route (offline fallback)
# ─────────────────────────────────────────────────────────────────────────────

def make_synthetic_route(total_dist_m=285_000, n_pts=None):
    """
    Realistic synthetic route Sasolburg → Zeerust (~285 km).
    Terrain: high Highveld plateau (~1 450 m) descending to lower Bushveld
    (~1 050 m) through the Magaliesberg foothills — matches real topography.
    """
    if n_pts is None:
        n_pts = max(int(total_dist_m / RESOLUTION_M) + 1, 50)

    cum_d = np.linspace(0, total_dist_m, n_pts)
    x     = cum_d / total_dist_m   # normalised [0, 1]

    # Base descent profile: Highveld → Bushveld
    base_alt = 1_450 - 400 * x

    # Magaliesberg crossing (~halfway): a noticeable 120 m climb then descent
    magalies = 120 * np.exp(-((x - 0.48)**2) / (2 * 0.04**2))

    # General rolling terrain (multiple harmonics)
    rolling  = (
          35 * np.sin(2 * np.pi * x * 3)
        + 20 * np.sin(2 * np.pi * x * 7 + 1.2)
        + 12 * np.sin(2 * np.pi * x * 13 + 0.7)
        +  6 * np.sin(2 * np.pi * x * 22 + 2.1)
    )

    alt = base_alt + magalies + rolling

    # Smooth slope (first derivative)
    dz        = np.gradient(alt, cum_d)
    slope_pct = dz * 100

    # GPS interpolation
    lats = np.linspace(SASOLBURG[0], ZEERUST[0], n_pts)
    lons = np.linspace(SASOLBURG[1], ZEERUST[1], n_pts)

    bearings = [0.0]
    for i in range(1, n_pts):
        bearings.append(bearing_deg(lats[i-1], lons[i-1], lats[i], lons[i]))

    return pd.DataFrame({
        "latitude":              lats,
        "longitude":             lons,
        "cumulative_distance_m": cum_d,
        "altitude_m":            alt,
        "bearing_deg":           bearings,
        "slope_pct":             slope_pct,
    })


# ─────────────────────────────────────────────────────────────────────────────
# DataFrame builder
# ─────────────────────────────────────────────────────────────────────────────

def build_dataframe(coords, elevs):
    n     = len(coords)
    lats  = [c[0] for c in coords]
    lons  = [c[1] for c in coords]
    cumd  = [0.0]
    for i in range(1, n):
        cumd.append(cumd[-1] + haversine_m(lats[i-1], lons[i-1], lats[i], lons[i]))
    bears = [0.0]
    for i in range(1, n):
        bears.append(bearing_deg(lats[i-1], lons[i-1], lats[i], lons[i]))
    slopes = [0.0]
    for i in range(1, n):
        dz = elevs[i] - elevs[i-1]
        dx = cumd[i]  - cumd[i-1]
        slopes.append((dz / max(dx, 1e-3)) * 100)
    return pd.DataFrame({
        "latitude":              lats,
        "longitude":             lons,
        "cumulative_distance_m": cumd,
        "altitude_m":            elevs,
        "bearing_deg":           bears,
        "slope_pct":             slopes,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Public entry points
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(use_synthetic=False):
    os.makedirs("data", exist_ok=True)

    if use_synthetic:
        print("[Pipeline] Using synthetic route (no network).")
        df = make_synthetic_route()
    else:
        try:
            coords = fetch_route_osrm()
            elevs  = fetch_elevations(coords)
            df     = build_dataframe(coords, elevs)
        except Exception as e:
            print(f"[Pipeline] API failed ({e}). Falling back to synthetic route.")
            df = make_synthetic_route()

    df.to_csv(OUTPUT_CSV, index=False)
    km = df["cumulative_distance_m"].iloc[-1] / 1000
    print(f"[Pipeline] {len(df)} waypoints  |  {km:.1f} km  →  {OUTPUT_CSV}")
    return df


if __name__ == "__main__":
    df = run_pipeline(use_synthetic=True)
    print(df[["cumulative_distance_m","altitude_m","slope_pct"]].describe().round(2))
