"""
main.py
=======
Sasol Solar Challenge – Day 2 Strategy Simulator  (v2 — Full Master Equation)
==============================================================================
Usage:
  python main.py                # real API route fetch + optimize
  python main.py --use-cached   # skip API, use existing route_data.csv
  python main.py --quick        # synthetic route (no network)
"""

import argparse
import os
import sys
import numpy as np
import pandas as pd

from constants import (
    RACE_START_S, RACE_END_S, CONTROL_STOP_S, LOOP_STOP_S,
    LOOP_DIST_M, INITIAL_SOC, MIN_SOC, BATTERY_CAPACITY_WH,
    P_AUXILIARY_W, V_BATTERY_NOM, C_RATED_AH, SOH,
)
from solar_model    import solar_power_W, total_solar_energy_J
from physics        import soc_update, drivetrain_power_W, auxiliary_power_W, ms_to_kmh
from optimizer      import BaseRouteOptimizer, LoopOptimizer
from visualizer     import generate_all_plots

ROUTE_CSV = "data/route_data.csv"


# ─────────────────────────────────────────────────────────────────────────────
# Timeline stitcher (base route + control stop + loops)
# ─────────────────────────────────────────────────────────────────────────────

def build_full_timeline(base_sim: dict, loop_result: dict,
                        arrival_s: float, route_df: pd.DataFrame):
    """
    Concatenate:
      • base-route simulation
      • 30-min control stop (car stationary, solar still charging)
      • loop driving + 5-min inter-loop stops

    Returns (time_s, velocity_ms, soc, solar_W, drive_W, aux_W, events)
    """
    events = []
    DT     = 30.0     # integration resolution for stops (seconds)

    # ── 30-min control stop ───────────────────────────────────────────────────
    t_cs  = arrival_s
    t_ce  = arrival_s + CONTROL_STOP_S

    t_ctrl_pts, v_ctrl, soc_ctrl, sol_ctrl, drv_ctrl, aux_ctrl = [], [], [], [], [], []
    soc = base_sim["soc"][-1]
    t   = t_cs
    while t <= t_ce:
        dt_   = min(DT, t_ce - t + 1e-9)
        Ps    = solar_power_W(t + dt_/2)
        soc   = soc_update(soc, Ps, 0.0, dt_)
        t_ctrl_pts.append(t); v_ctrl.append(0.0)
        soc_ctrl.append(soc); sol_ctrl.append(Ps)
        drv_ctrl.append(0.0); aux_ctrl.append(P_AUXILIARY_W)
        t += dt_

    events.append({"type": "control_stop", "t_start": t_cs, "t_end": t_ce,
                   "label": "30-min Control Stop (Zeerust)"})

    # ── loops ─────────────────────────────────────────────────────────────────
    tl = loop_result.get("timeline", [])
    n_loops = loop_result.get("n_loops", 0)
    v_loop  = loop_result.get("v_loop_ms", 0)

    if tl:
        t_loop_arr   = np.array([r[0] for r in tl])
        v_loop_arr   = np.array([r[1] for r in tl])
        soc_loop_arr = np.array([r[2] for r in tl])
        sol_loop     = np.array([solar_power_W(t) for t in t_loop_arr])
        drv_loop     = np.array([
            drivetrain_power_W(v, 0.0, 0.0) if v > 0 else 0.0
            for v in v_loop_arr])
        aux_loop     = np.full(len(tl), P_AUXILIARY_W)
    else:
        t_loop_arr = v_loop_arr = soc_loop_arr = sol_loop = drv_loop = aux_loop = np.array([])

    # Add loop-stop events
    if n_loops > 0:
        t_cur = t_ce
        for k in range(n_loops - 1):
            t_cur += LOOP_DIST_M / max(v_loop, 1e-6)
            events.append({"type": "loop_stop",
                           "t_start": t_cur, "t_end": t_cur + LOOP_STOP_S,
                           "label": f"5-min Stop after loop {k+1}"})
            t_cur += LOOP_STOP_S

    # ── concatenate ───────────────────────────────────────────────────────────
    def cat(*arrs):
        parts = [a for a in arrs if len(a) > 0]
        return np.concatenate(parts) if parts else np.array([])

    t_full   = cat(base_sim["time_s"],       np.array(t_ctrl_pts), t_loop_arr)
    v_full   = cat(base_sim["velocity_ms"],  np.array(v_ctrl),     v_loop_arr)
    soc_full = cat(base_sim["soc"],          np.array(soc_ctrl),   soc_loop_arr)
    sol_full = cat(base_sim["power_solar_W"],np.array(sol_ctrl),   sol_loop)
    drv_full = cat(base_sim["power_drive_W"],np.array(drv_ctrl),   drv_loop)
    aux_full = cat(base_sim["power_aux_W"],  np.array(aux_ctrl),   aux_loop)

    return t_full, v_full, soc_full, sol_full, drv_full, aux_full, events


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run(use_cached=False, quick=False):
    print("=" * 62)
    print("  SASOL SOLAR CHALLENGE – DAY 2  (v2: Full Master Equation)")
    print("=" * 62)

    os.makedirs("data",    exist_ok=True)
    os.makedirs("plots",   exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    # ── Phase 1: Route ─────────────────────────────────────────────────────────
    print("\n── Phase 1: Cartographer ────────────────────────────────────")
    from data_pipeline import run_pipeline
    if use_cached and os.path.exists(ROUTE_CSV):
        print(f"[Route] Loading cached {ROUTE_CSV}")
        route_df = pd.read_csv(ROUTE_CSV)
    else:
        route_df = run_pipeline(use_synthetic=quick)

    total_km = route_df["cumulative_distance_m"].iloc[-1] / 1000
    print(f"[Route] {len(route_df)} waypoints  |  {total_km:.1f} km  "
          f"|  alt {route_df['altitude_m'].min():.0f}–{route_df['altitude_m'].max():.0f} m")

    # Solar energy sanity check
    E_avail = total_solar_energy_J(RACE_START_S, RACE_END_S)
    E_aux_day = P_AUXILIARY_W * (RACE_END_S - RACE_START_S) / 3_600_000
    print(f"[Solar] Available over race window: {E_avail/3_600_000:.3f} kWh")
    print(f"[Aux]   Auxiliary draw over day   : {E_aux_day:.3f} kWh  "
          f"({P_AUXILIARY_W:.0f} W × 9 h)")

    # ── Phase 2A: Base Route ───────────────────────────────────────────────────
    print("\n── Phase 2A: Base-Route Optimizer ───────────────────────────")
    # Aim to arrive at 12:30 — balances solar availability vs loop time
    target_arr = 12 * 3600 + 30 * 60

    opt_a    = BaseRouteOptimizer(route_df,
                                  t_depart_s=RACE_START_S,
                                  target_arrival_s=target_arr)
    base_sim = opt_a.optimize()

    arr_s   = base_sim["arrival_time_s"]
    arr_soc = base_sim["arrival_soc"]
    print(f"\n[Base] Arrival: {int(arr_s//3600):02d}:{int((arr_s%3600)//60):02d}  "
          f"|  SOC: {arr_soc*100:.1f}%")

    # ── Phase 2B: Loop Optimizer ───────────────────────────────────────────────
    print("\n── Phase 2B: Loop Optimizer ──────────────────────────────────")
    opt_b       = LoopOptimizer(arr_s, arr_soc)
    loop_result = opt_b.optimize()

    n_loops    = loop_result["n_loops"]
    v_kmh      = loop_result["v_loop_kmh"]
    final_soc  = loop_result["final_soc"]
    soc_post_cs = loop_result["soc_after_control_stop"]

    # ── Phase 3: Stitch + Plot ─────────────────────────────────────────────────
    print("\n── Phase 3: Analyst ──────────────────────────────────────────")
    (t_full, v_full, soc_full,
     sol_full, drv_full, aux_full,
     events) = build_full_timeline(base_sim, loop_result, arr_s, route_df)

    total_dist_km = total_km + n_loops * 35
    result_summary = {
        "total_dist_km":  total_dist_km,
        "route_dist_km":  total_km,
        "n_loops":        n_loops,
        "loop_speed_kmh": v_kmh,
        "final_soc":      final_soc,
        "arrival_time_s": arr_s,
    }

    plot_paths = generate_all_plots(
        t_full, v_full, soc_full, sol_full, drv_full, aux_full,
        route_df, events, result_summary
    )

    # ── Final Report ───────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  STRATEGY REPORT")
    print("=" * 62)
    print(f"  Battery model        : {V_BATTERY_NOM}V × {C_RATED_AH}Ah × SOH{SOH} = {BATTERY_CAPACITY_WH:.0f} Wh")
    print(f"  Auxiliary load       : {P_AUXILIARY_W:.0f} W (always-on) = {E_aux_day:.2f} kWh/day")
    print(f"  Route distance       : {total_km:.1f} km")
    print(f"  Departure            : 08:00")
    print(f"  Zeerust arrival      : {int(arr_s//3600):02d}:{int((arr_s%3600)//60):02d}")
    print(f"  Arrival SOC          : {arr_soc*100:.1f}%")
    print(f"  SOC after 30-min stop: {soc_post_cs*100:.1f}%")
    print(f"  Control stop         : 30 min (mandatory)")
    print(f"  Loops completed      : {n_loops} × 35 km")
    print(f"  Optimal loop speed   : {v_kmh:.1f} km/h")
    print(f"  ─────────────────────────────────")
    print(f"  TOTAL DISTANCE       : {total_dist_km:.1f} km")
    print(f"  Final battery SOC    : {final_soc*100:.1f}%")
    soc_ok = final_soc >= MIN_SOC
    print(f"  SOC constraint (≥20%): {'PASS ✓' if soc_ok else 'FAIL ✗'}")
    print("=" * 62)

    # Save report (UTF-8 explicitly — fixes Windows CP1252 issue)
    lines = [
        "SASOL SOLAR CHALLENGE - DAY 2 RESULTS  (v2: Full Master Equation)",
        "=" * 60,
        "MASTER POWER BALANCE EQUATION TERMS:",
        "  V_batt x C_rated x SOH x d(SOC)/dt",
        "  + (DNI x cos_theta + DHI) x A x eta_solar",
        "  = [1/eta_m - eta_r] x (m.a.v + 0.5.rho.Cd.A.v^3 + mu.m.g.v.cos + m.g.v.sin)",
        "  + (P_inverter + P_heat) + (P_lights + P_telemetry + P_other)",
        "",
        "BATTERY",
        f"  Voltage       : {V_BATTERY_NOM} V",
        f"  Capacity      : {C_RATED_AH} Ah",
        f"  SOH           : {SOH}",
        f"  Usable energy : {BATTERY_CAPACITY_WH:.0f} Wh",
        "",
        "AUXILIARY LOADS",
        f"  Total P_aux   : {P_AUXILIARY_W:.0f} W",
        f"  Energy/day    : {E_aux_day:.3f} kWh",
        "",
        "RESULTS",
        f"  Route         : {total_km:.1f} km",
        f"  Arrival       : {int(arr_s//3600):02d}:{int((arr_s%3600)//60):02d}",
        f"  Loops         : {n_loops} x 35 km = {n_loops*35:.0f} km",
        f"  Loop speed    : {v_kmh:.1f} km/h",
        f"  TOTAL DIST    : {total_dist_km:.1f} km",
        f"  Final SOC     : {final_soc*100:.1f}%",
        f"  SOC check     : {'PASS' if soc_ok else 'FAIL'}",
    ]
    report_path = "outputs/strategy_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n  Report saved -> {report_path}")
    print(f"\n  Plots ({len(plot_paths)}):")
    for p in plot_paths:
        print(f"    {p}")

    return result_summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sasol Solar Challenge Day 2 – Full Master Equation Simulator")
    parser.add_argument("--use-cached", action="store_true",
                        help="Skip API calls; reload existing route CSV")
    parser.add_argument("--quick",      action="store_true",
                        help="Use synthetic route (no internet needed)")
    args = parser.parse_args()
    run(use_cached=args.use_cached, quick=args.quick)
