"""
main.py
=======
Sasol Solar Challenge – Day 2 Strategy Simulator
=================================================
Orchestrates the full pipeline:

  Phase 1  →  data_pipeline.py  : fetch route + elevation → CSV
              solar_model.py    : Gaussian solar irradiance model
  Phase 2  →  optimizer.py      : base-route optimizer + loop optimizer
  Phase 3  →  visualizer.py     : generate all plots

Usage:
  python main.py                    # full run (fetches route from API)
  python main.py --use-cached       # skip API calls if CSV already exists
  python main.py --quick            # synthetic route (no network needed)
"""

import argparse
import os
import sys
import time
import numpy as np
import pandas as pd

from solar_model    import solar_power_W, RACE_START_S
from physics        import (ms_to_kmh, kmh_to_ms, BATTERY_CAPACITY_WH,
                             INITIAL_SOC, MIN_SOC, power_demand_W)
from optimizer      import (BaseRouteOptimizer, LoopOptimizer,
                            CONTROL_STOP_S, LOOP_STOP_S,
                            LOOP_DIST_M, RACE_END_S)
from visualizer     import generate_all_plots

ROUTE_CSV = "data/route_data.csv"


# ── helper: synthetic flat route for offline/quick testing ────────────────────

def make_synthetic_route(n_pts=100, total_dist_m=280_000) -> pd.DataFrame:
    """
    Generates a synthetic route with gentle elevation changes for offline testing.
    Mimics the Sasolburg–Zeerust terrain: high plateau, slight descent westward.
    """
    cum_d = np.linspace(0, total_dist_m, n_pts)

    # Gentle sinusoidal terrain + overall 150 m descent
    base_alt  = 1_450.0
    alt       = (base_alt
                 - 150 * cum_d / total_dist_m
                 + 40  * np.sin(cum_d / total_dist_m * 4 * np.pi)
                 + 20  * np.sin(cum_d / total_dist_m * 12 * np.pi))

    # Slope from gradient
    dz        = np.gradient(alt, cum_d)
    slope_pct = dz * 100

    lats = np.linspace(-26.818, -25.549, n_pts)
    lons = np.linspace( 27.832,  26.082, n_pts)

    return pd.DataFrame({
        "latitude":              lats,
        "longitude":             lons,
        "cumulative_distance_m": cum_d,
        "altitude_m":            alt,
        "bearing_deg":           np.full(n_pts, 255.0),
        "slope_pct":             slope_pct,
    })


# ── helper: stitch base-route + loops into one timeline ───────────────────────

def build_full_timeline(base_sim: dict, loop_result: dict,
                        arrival_time_s: float) -> tuple:
    """
    Concatenates base-route simulation data with loop data.

    Returns (time_s, velocity_ms, soc, solar_W, demand_W, events)
    where events is a list of dicts describing stops.
    """
    t_base     = base_sim["time_s"]
    v_base     = base_sim["velocity_ms"]
    soc_base   = base_sim["soc"]
    p_sol_base = base_sim["solar_W"]
    p_dem_base = base_sim["power_demand_W"]
    arrival    = arrival_time_s

    events = []

    # ── 30-minute control stop ─────────────────────────────────────────────────
    t_ctrl_start = arrival
    t_ctrl_end   = arrival + CONTROL_STOP_S
    dt_ctrl      = 30          # 30-second resolution
    n_ctrl       = int(CONTROL_STOP_S / dt_ctrl)
    t_ctrl_arr   = np.linspace(t_ctrl_start, t_ctrl_end, n_ctrl)
    v_ctrl       = np.zeros(n_ctrl)
    soc_ctrl     = np.full(n_ctrl, soc_base[-1])
    # Solar charges during stop
    for i, tc in enumerate(t_ctrl_arr):
        P_sol = solar_power_W(tc)
        if i == 0:
            soc_ctrl[i] = soc_base[-1]
        else:
            dt_i = t_ctrl_arr[i] - t_ctrl_arr[i-1]
            soc_ctrl[i] = min(1.0, soc_ctrl[i-1] + P_sol * dt_i /
                               (3600 * BATTERY_CAPACITY_WH))
    p_sol_ctrl   = np.array([solar_power_W(tc) for tc in t_ctrl_arr])
    p_dem_ctrl   = np.zeros(n_ctrl)

    events.append({"type": "control_stop",
                   "t_start": t_ctrl_start, "t_end": t_ctrl_end,
                   "label": "30-min Control Stop"})

    # ── loops ──────────────────────────────────────────────────────────────────
    loop_tl    = loop_result.get("timeline", [])
    n_loops    = loop_result.get("n_loops", 0)
    v_loop_ms  = loop_result.get("v_loop_ms", kmh_to_ms(80))

    if loop_tl:
        t_loop_arr   = np.array([r[0] for r in loop_tl])
        v_loop_arr   = np.array([r[1] for r in loop_tl])
        soc_loop_arr = np.array([r[2] for r in loop_tl])
        p_sol_loop   = np.array([solar_power_W(t) for t in t_loop_arr])
        p_dem_loop   = np.array([power_demand_W(v, 0.0, 0.0) if v > 0 else 0.0
                                  for v in v_loop_arr])
    else:
        t_loop_arr = p_sol_loop = p_dem_loop = v_loop_arr = soc_loop_arr = np.array([])

    # Mark loop stop events
    if n_loops > 0:
        t_cur = t_ctrl_end
        for k in range(n_loops - 1):
            t_cur += LOOP_DIST_M / v_loop_ms
            events.append({"type": "loop_stop",
                            "t_start": t_cur, "t_end": t_cur + LOOP_STOP_S,
                            "label": f"5-min Stop (after loop {k+1})"})
            t_cur += LOOP_STOP_S

    # ── concatenate ────────────────────────────────────────────────────────────
    def cat(*arrays):
        non_empty = [a for a in arrays if len(a) > 0]
        return np.concatenate(non_empty) if non_empty else np.array([])

    t_full   = cat(t_base,     t_ctrl_arr,   t_loop_arr)
    v_full   = cat(v_base,     v_ctrl,       v_loop_arr)
    soc_full = cat(soc_base,   soc_ctrl,     soc_loop_arr)
    sol_full = cat(p_sol_base, p_sol_ctrl,   p_sol_loop)
    dem_full = cat(p_dem_base, p_dem_ctrl,   p_dem_loop)

    return t_full, v_full, soc_full, sol_full, dem_full, events


# ── main orchestrator ──────────────────────────────────────────────────────────

def run(use_cached=False, quick=False):
    print("=" * 60)
    print("  SASOL SOLAR CHALLENGE – DAY 2 STRATEGY SIMULATOR")
    print("=" * 60)

    os.makedirs("data",    exist_ok=True)
    os.makedirs("plots",   exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    # ── Phase 1: Data Pipeline ─────────────────────────────────────────────────
    print("\n── Phase 1: Route Data ──────────────────────────────────────")

    if quick:
        print("[Route] Using synthetic route (quick mode).")
        route_df = make_synthetic_route()
        route_df.to_csv(ROUTE_CSV, index=False)
    elif use_cached and os.path.exists(ROUTE_CSV):
        print(f"[Route] Loading cached data from {ROUTE_CSV}")
        route_df = pd.read_csv(ROUTE_CSV)
    else:
        from data_pipeline import run_pipeline
        route_df = run_pipeline()

    total_route_km = route_df["cumulative_distance_m"].iloc[-1] / 1000
    print(f"[Route] Total route distance: {total_route_km:.1f} km")
    print(f"[Route] Waypoints: {len(route_df)}")
    print(f"[Route] Elevation range: "
          f"{route_df['altitude_m'].min():.0f} – "
          f"{route_df['altitude_m'].max():.0f} m")

    # ── Phase 1: Solar model sanity check ─────────────────────────────────────
    from solar_model import total_solar_energy_J
    E_avail = total_solar_energy_J(RACE_START_S, RACE_END_S)
    print(f"\n[Solar] Total available energy (race window): "
          f"{E_avail/3_600_000:.3f} kWh")

    # ── Phase 2: Base-route optimization ──────────────────────────────────────
    print("\n── Phase 2A: Base-Route Optimization ────────────────────────")
    t0 = time.time()

    # Target Zeerust arrival: leave as much time as possible for loops
    # but guarantee we can at least do the control stop + 1 loop
    target_arr = 13 * 3600    # aim for 13:00 — leaves 4 h for loops

    opt_a = BaseRouteOptimizer(route_df, t_depart_s=RACE_START_S,
                               target_arrival_s=target_arr)
    base_sim = opt_a.optimize()
    print(f"[Base] Elapsed: {time.time()-t0:.1f}s")

    arrival_s   = base_sim["arrival_time_s"]
    arrival_soc = base_sim["arrival_soc"]
    print(f"[Base] Arrival at Zeerust: {arrival_s/3600:.2f} h  "
          f"({int(arrival_s//3600):02d}:{int((arrival_s%3600)//60):02d})")
    print(f"[Base] Arrival SOC      : {arrival_soc*100:.1f}%")

    # ── Phase 2B: Loop optimization ───────────────────────────────────────────
    print("\n── Phase 2B: Loop Optimization ──────────────────────────────")
    opt_b      = LoopOptimizer(arrival_s, arrival_soc)
    loop_result = opt_b.optimize()

    n_loops    = loop_result["n_loops"]
    v_loop_kmh = loop_result["v_loop_kmh"]
    final_soc  = loop_result["final_soc"]

    print(f"\n[Loops] Optimal speed : {v_loop_kmh:.1f} km/h")
    print(f"[Loops] Loops done    : {n_loops}")
    print(f"[Loops] Extra distance: {n_loops * 35:.0f} km")
    print(f"[Loops] Final SOC     : {final_soc*100:.1f}%")

    # ── Phase 3: Build timeline & plots ───────────────────────────────────────
    print("\n── Phase 3: Visualization ───────────────────────────────────")

    t_full, v_full, soc_full, sol_full, dem_full, events = build_full_timeline(
        base_sim, loop_result, arrival_s)

    total_dist_km = total_route_km + n_loops * 35
    result_summary = {
        "total_dist_km":  total_dist_km,
        "route_dist_km":  total_route_km,
        "n_loops":        n_loops,
        "loop_speed_kmh": v_loop_kmh,
        "final_soc":      final_soc,
        "arrival_time_s": arrival_s,
    }

    plot_paths = generate_all_plots(
        t_full, v_full, soc_full, sol_full, dem_full,
        route_df, events, result_summary
    )

    # ── Summary report ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  STRATEGY REPORT")
    print("=" * 60)
    print(f"  Route distance       : {total_route_km:.1f} km")
    print(f"  Arrival at Zeerust   : "
          f"{int(arrival_s//3600):02d}:{int((arrival_s%3600)//60):02d}")
    print(f"  Arrival SOC          : {arrival_soc*100:.1f}%")
    print(f"  Control stop         : 30 min")
    print(f"  Loops completed      : {n_loops}  ×  35 km")
    print(f"  Optimal loop speed   : {v_loop_kmh:.1f} km/h")
    print(f"  TOTAL DISTANCE       : {total_dist_km:.1f} km")
    print(f"  Final battery SOC    : {final_soc*100:.1f}%  "
          f"{'✓ OK' if final_soc >= MIN_SOC else '✗ VIOLATION'}")
    print(f"  SOC constraint       : ≥ {MIN_SOC*100:.0f}%  →  "
          f"{'PASS' if final_soc >= MIN_SOC else 'FAIL'}")
    print("=" * 60)
    print("\nPlots generated:")
    for p in plot_paths:
        print(f"  {p}")

    # Save summary to file
    summary_lines = [
        "SASOL SOLAR CHALLENGE – DAY 2 RESULTS",
        "="*50,
        f"Route: Sasolburg → Zeerust ({total_route_km:.1f} km)",
        f"Race start: 08:00 | Race end: 17:00",
        "",
        "BASE ROUTE",
        f"  Arrival time : {int(arrival_s//3600):02d}:{int((arrival_s%3600)//60):02d}",
        f"  Arrival SOC  : {arrival_soc*100:.1f}%",
        "",
        "LOOP PHASE",
        f"  Control stop : 30 min (mandatory)",
        f"  Loop speed   : {v_loop_kmh:.1f} km/h",
        f"  Loops done   : {n_loops}",
        f"  Loop distance: {n_loops * 35:.0f} km",
        "",
        "FINAL RESULT",
        f"  Total distance: {total_dist_km:.1f} km",
        f"  Final SOC     : {final_soc*100:.1f}%",
        f"  SOC constraint: {'PASS ✓' if final_soc >= MIN_SOC else 'FAIL ✗'}",
    ]
    with open("outputs/strategy_report.txt", "w") as f:
        f.write("\n".join(summary_lines))
    print("\n  Strategy report → outputs/strategy_report.txt")

    return result_summary


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sasol Solar Challenge Day 2 Strategy Simulator")
    parser.add_argument("--use-cached", action="store_true",
                        help="Skip API calls; use existing route CSV")
    parser.add_argument("--quick",      action="store_true",
                        help="Use synthetic route (no network required)")
    args = parser.parse_args()

    run(use_cached=args.use_cached, quick=args.quick)
