"""
data_pipeline.py
================
Phase 1 – The Cartographer

Fetches the Sasolburg → Zeerust route via OSRM (open-source, no API key),
then queries the Open-Elevation API for altitude at each point.
Computes slope between consecutive waypoints and saves everything as a CSV.

Spatial resolution choice:
  We request one GPS coordinate every ~500 m along the route.
  A solar car travels at 60-100 km/h, so 500 m corresponds to 18-30 seconds
  of driving — fine enough to capture meaningful elevation changes (hillcrests,
  valleys) without making the optimiser's state-space unmanageable.
  Coarser resolution (e.g. 5 km) would miss short steep grades that spike
  motor power; finer resolution (e.g. 50 m) would create 5000+ waypoints,
  slowing the NLP solver with negligible accuracy gain.
"""

import requests
import numpy as np
import pandas as pd
import time
import json
import os

# ── coordinates ────────────────────────────────────────────────────────────────
SASOLBURG  = (-26.8178, 27.8322)   # lat, lon
ZEERUST    = (-25.5487, 26.0822)

OSRM_URL   = "http://router.project-osrm.org/route/v1/driving"
ELEV_URL   = "https://api.open-elevation.com/api/v1/lookup"

TARGET_SPACING_M = 500             # desired resolution in metres
OUTPUT_CSV = "data/route_data.csv"


# ── helpers ────────────────────────────────────────────────────────────────────

def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres."""
    R = 6_371_000
    φ1, φ2 = np.radians(lat1), np.radians(lat2)
    dφ = np.radians(lat2 - lat1)
    dλ = np.radians(lon2 - lon1)
    a = np.sin(dφ/2)**2 + np.cos(φ1)*np.cos(φ2)*np.sin(dλ/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))


def bearing(lat1, lon1, lat2, lon2):
    """Forward azimuth in degrees [0, 360)."""
    φ1, φ2 = np.radians(lat1), np.radians(lat2)
    dλ = np.radians(lon2 - lon1)
    x = np.sin(dλ) * np.cos(φ2)
    y = np.cos(φ1)*np.sin(φ2) - np.sin(φ1)*np.cos(φ2)*np.cos(dλ)
    return (np.degrees(np.arctan2(x, y)) + 360) % 360


# ── step 1: route geometry from OSRM ─────────────────────────────────────────

def fetch_route_osrm(origin, destination, steps=200):
    """
    Call OSRM's route service with `overview=full&geometries=geojson`.
    Returns a list of (lat, lon) tuples at approximately TARGET_SPACING_M spacing.
    """
    lon1, lat1 = origin[1],      origin[0]
    lon2, lat2 = destination[1], destination[0]

    url = (f"{OSRM_URL}/{lon1},{lat1};{lon2},{lat2}"
           f"?overview=full&geometries=geojson&steps=false")

    print(f"[OSRM] Requesting route …  {url[:80]}")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    coords_raw = data["routes"][0]["geometry"]["coordinates"]  # [lon, lat]
    total_dist = data["routes"][0]["distance"]                  # metres
    print(f"[OSRM] Route distance: {total_dist/1000:.1f} km  |  "
          f"{len(coords_raw)} raw geometry points")

    # Convert to (lat, lon) and sub-sample to TARGET_SPACING_M
    coords = [(c[1], c[0]) for c in coords_raw]
    return subsample(coords, total_dist)


def subsample(coords, total_dist_m):
    """
    Interpolate along the polyline to get evenly-spaced waypoints at
    roughly TARGET_SPACING_M apart.
    """
    n_target = max(int(total_dist_m / TARGET_SPACING_M) + 1, 2)

    # Build cumulative distance array
    cum = [0.0]
    for i in range(1, len(coords)):
        d = haversine(coords[i-1][0], coords[i-1][1],
                      coords[i][0],   coords[i][1])
        cum.append(cum[-1] + d)
    total = cum[-1]

    targets = np.linspace(0, total, n_target)
    result  = []
    j = 0
    for t in targets:
        while j < len(cum)-1 and cum[j+1] < t:
            j += 1
        if j >= len(coords)-1:
            result.append(coords[-1])
            continue
        frac = (t - cum[j]) / max(cum[j+1] - cum[j], 1e-9)
        lat = coords[j][0] + frac * (coords[j+1][0] - coords[j][0])
        lon = coords[j][1] + frac * (coords[j+1][1] - coords[j][1])
        result.append((lat, lon))

    print(f"[subsample] {len(result)} waypoints at ~{TARGET_SPACING_M} m spacing")
    return result


# ── step 2: elevation from Open-Elevation ────────────────────────────────────

def fetch_elevations_batch(coords, batch_size=100):
    """
    Open-Elevation accepts up to ~200 locations per POST request.
    We chunk the list and retry on failure.
    """
    elevations = []
    total = len(coords)

    for start in range(0, total, batch_size):
        chunk = coords[start:start + batch_size]
        payload = {"locations": [{"latitude": lat, "longitude": lon}
                                  for lat, lon in chunk]}
        for attempt in range(3):
            try:
                r = requests.post(ELEV_URL, json=payload, timeout=60)
                r.raise_for_status()
                results = r.json()["results"]
                elevations.extend([res["elevation"] for res in results])
                print(f"[Elevation] {min(start+batch_size, total)}/{total} done")
                break
            except Exception as e:
                print(f"[Elevation] Attempt {attempt+1} failed: {e}")
                time.sleep(3)
        else:
            # Fallback: linear interpolation from endpoints
            print("[Elevation] Using fallback linear interpolation for this batch")
            for _ in chunk:
                elevations.append(None)

    # Fill None gaps with linear interpolation
    elev_arr = np.array([e if e is not None else np.nan for e in elevations],
                        dtype=float)
    nans = np.isnan(elev_arr)
    if nans.any():
        idx = np.arange(len(elev_arr))
        elev_arr[nans] = np.interp(idx[nans], idx[~nans], elev_arr[~nans])

    return elev_arr


# ── step 3: assemble dataframe ────────────────────────────────────────────────

def build_route_dataframe(coords, elevations):
    """
    Build a DataFrame with:
      index, latitude, longitude, cumulative_distance_m,
      altitude_m, bearing_deg, slope_pct
    """
    n = len(coords)
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]

    # Cumulative distance
    cum_dist = [0.0]
    for i in range(1, n):
        d = haversine(lats[i-1], lons[i-1], lats[i], lons[i])
        cum_dist.append(cum_dist[-1] + d)

    # Bearing (direction)
    bearings = [0.0]
    for i in range(1, n):
        bearings.append(bearing(lats[i-1], lons[i-1], lats[i], lons[i]))

    # Slope  (rise / run × 100  in %)
    slopes = [0.0]
    for i in range(1, n):
        dz = elevations[i] - elevations[i-1]
        dx = cum_dist[i] - cum_dist[i-1]
        slopes.append((dz / max(dx, 1e-3)) * 100)

    df = pd.DataFrame({
        "latitude":              lats,
        "longitude":             lons,
        "cumulative_distance_m": cum_dist,
        "altitude_m":            elevations,
        "bearing_deg":           bearings,
        "slope_pct":             slopes,
    })
    return df


# ── main ──────────────────────────────────────────────────────────────────────

def run_pipeline():
    os.makedirs("data", exist_ok=True)

    # 1. Route
    coords = fetch_route_osrm(SASOLBURG, ZEERUST)

    # 2. Elevations
    elevations = fetch_elevations_batch(coords)

    # 3. DataFrame
    df = build_route_dataframe(coords, elevations)

    # 4. Save
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\n[Pipeline] Route data saved → {OUTPUT_CSV}")
    print(df.describe())
    return df


if __name__ == "__main__":
    run_pipeline()
