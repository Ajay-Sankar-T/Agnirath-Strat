"""
visualizer.py
=============
Phase 3 – The Analyst

Generates 9 publication-quality plots:
  1. Velocity profile
  2. SOC profile
  3. Acceleration profile
  4. Power balance (solar vs drivetrain vs auxiliary)
  5. Elevation + slope
  6. Solar irradiance (GHI / DNI / DHI / cosθ / panel output)
  7. Cumulative energy budget
  8. Force decomposition (per segment)
  9. Master dashboard (2×3 grid)
"""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import pandas as pd

from constants import (
    MIN_SOC, RACE_START_S, RACE_END_S,
    P_AUXILIARY_W, BATTERY_CAPACITY_WH,
    V_MAX_MS,
)
from physics import ms_to_kmh, f_aero_N, f_rolling_N, f_grade_N
from solar_model import solar_profile

PLOTS_DIR = "plots"
os.makedirs(PLOTS_DIR, exist_ok=True)

# ── dark theme ─────────────────────────────────────────────────────────────────
BG      = "#0d1117"
PANEL   = "#161b22"
GRID    = "#21262d"
FG      = "#c9d1d9"
BLUE    = "#58a6ff"
ORANGE  = "#f0883e"
GREEN   = "#3fb950"
RED     = "#f85149"
PURPLE  = "#bc8cff"
YELLOW  = "#e3b341"
TEAL    = "#39d0d8"
PINK    = "#ff7b72"

plt.rcParams.update({
    "figure.facecolor": BG,  "axes.facecolor":   PANEL,
    "axes.edgecolor":   GRID, "axes.labelcolor":  FG,
    "xtick.color":      FG,   "ytick.color":      FG,
    "grid.color":       GRID, "text.color":       FG,
    "legend.facecolor": PANEL,"legend.edgecolor": GRID,
    "font.family":      "monospace", "font.size":  9,
})


def _hm(t_s):
    return f"{int(t_s//3600):02d}:{int((t_s%3600)//60):02d}"


def _time_axis(ax, t_arr):
    ticks = np.arange(RACE_START_S, RACE_END_S + 1, 3600)
    ax.set_xticks(ticks)
    ax.set_xticklabels([_hm(t) for t in ticks], fontsize=7)
    ax.set_xlabel("Time of Day (SAST)")


def _shade_stops(ax, events):
    for ev in events:
        if ev["type"] in ("control_stop", "loop_stop"):
            ax.axvspan(ev["t_start"], ev["t_end"], color="#555", alpha=0.15, zorder=0)


def _save(fig, name):
    path = os.path.join(PLOTS_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] → {path}")
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 1. Velocity
# ─────────────────────────────────────────────────────────────────────────────

def plot_velocity(time_s, velocity_ms, events):
    v_kmh = ms_to_kmh(velocity_ms)
    fig, ax = plt.subplots(figsize=(13, 4), facecolor=BG)
    _shade_stops(ax, events)
    ax.plot(time_s, v_kmh, color=BLUE, lw=1.6, label="Vehicle speed")
    ax.axhline(ms_to_kmh(V_MAX_MS), color=RED, lw=1.2, ls="--", label="120 km/h limit")
    ax.axhline(0, color=GRID, lw=0.8)
    # Mark Zeerust arrival
    for ev in events:
        if ev["type"] == "control_stop":
            ax.axvline(ev["t_start"], color=ORANGE, lw=1.5, ls=":", alpha=0.9)
            ax.text(ev["t_start"] + 120, 118,
                    "Zeerust", color=ORANGE, fontsize=8, va="top")
            break
    ax.set_ylabel("Speed (km/h)")
    ax.set_ylim(-5, 135)
    ax.set_title("Velocity Profile – Day 2", fontweight="bold")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.35)
    _time_axis(ax, time_s)
    fig.tight_layout()
    return _save(fig, "01_velocity_profile.png")


# ─────────────────────────────────────────────────────────────────────────────
# 2. SOC
# ─────────────────────────────────────────────────────────────────────────────

def plot_soc(time_s, soc, events):
    pct = soc * 100
    fig, ax = plt.subplots(figsize=(13, 4), facecolor=BG)
    _shade_stops(ax, events)
    ax.plot(time_s, pct, color=GREEN, lw=2.0, label="Battery SOC")
    ax.axhline(MIN_SOC * 100, color=RED, lw=1.8, ls="--",
               label=f"Min SOC floor ({int(MIN_SOC*100)}%)")
    ax.fill_between(time_s, pct, MIN_SOC * 100,
                    where=pct >= MIN_SOC * 100, alpha=0.12, color=GREEN)
    ax.fill_between(time_s, pct, MIN_SOC * 100,
                    where=pct < MIN_SOC * 100,  alpha=0.28, color=RED)
    ax.set_ylabel("State of Charge (%)")
    ax.set_ylim(0, 105)
    ax.set_title("Battery SOC Profile – Master Equation  "
                 f"[V·C·SOH·d(SOC)/dt]", fontweight="bold")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.35)
    _time_axis(ax, time_s)
    fig.tight_layout()
    return _save(fig, "02_soc_profile.png")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Acceleration
# ─────────────────────────────────────────────────────────────────────────────

def plot_acceleration(time_s, velocity_ms):
    dt    = np.diff(time_s)
    dt    = np.where(dt < 1e-6, 1e-6, dt)
    accel = np.diff(velocity_ms) / dt
    accel = np.append(accel, accel[-1])

    fig, ax = plt.subplots(figsize=(13, 4), facecolor=BG)
    ax.plot(time_s, accel, color=PURPLE, lw=1.2, label="Acceleration")
    ax.axhline( 1.5, color=ORANGE, lw=1.2, ls="--", label="+1.5 m/s² limit")
    ax.axhline(-2.5, color=RED,    lw=1.2, ls="--", label="−2.5 m/s² limit")
    ax.axhline(0,    color=GRID,   lw=0.8)
    ax.set_ylabel("Acceleration (m/s²)")
    ax.set_ylim(-4, 4)
    ax.set_title("Acceleration Profile", fontweight="bold")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.35)
    _time_axis(ax, time_s)
    fig.tight_layout()
    return _save(fig, "03_acceleration_profile.png")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Power Balance (3-way: solar / drivetrain / auxiliary)
# ─────────────────────────────────────────────────────────────────────────────

def plot_power_balance(time_s, solar_W, drive_W, aux_W):
    net = solar_W - drive_W - aux_W

    fig, ax = plt.subplots(figsize=(13, 5), facecolor=BG)
    ax.plot(time_s, solar_W, color=YELLOW, lw=1.8, label="P_solar  (DNI·cosθ + DHI)·A·η")
    ax.plot(time_s, drive_W, color=BLUE,   lw=1.8, label="P_drivetrain  [1/η_m − η_r]·(forces·v)")
    ax.axhline(P_AUXILIARY_W, color=PINK, lw=1.5, ls="--",
               label=f"P_auxiliary  ({P_AUXILIARY_W:.0f} W constant)")
    ax.fill_between(time_s, solar_W, drive_W + aux_W,
                    where=net >= 0, alpha=0.15, color=GREEN,  label="Net charge")
    ax.fill_between(time_s, solar_W, drive_W + aux_W,
                    where=net < 0,  alpha=0.15, color=RED,    label="Net discharge")
    ax.set_ylabel("Power (W)")
    ax.set_title("Power Balance – Full Master Equation", fontweight="bold")
    ax.legend(loc="upper right", fontsize=8, ncol=2)
    ax.grid(True, alpha=0.35)
    _time_axis(ax, time_s)
    fig.tight_layout()
    return _save(fig, "04_power_balance.png")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Elevation + slope
# ─────────────────────────────────────────────────────────────────────────────

def plot_elevation(route_df):
    dist  = route_df["cumulative_distance_m"] / 1000
    alt   = route_df["altitude_m"]
    slope = route_df["slope_pct"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 5),
                                    facecolor=BG, sharex=True)
    ax1.fill_between(dist, alt, alt.min() - 30, alpha=0.3, color=BLUE)
    ax1.plot(dist, alt, color=BLUE, lw=1.6)
    ax1.set_ylabel("Altitude (m)")
    ax1.set_title("Route Elevation & Slope – Sasolburg → Zeerust", fontweight="bold")
    ax1.grid(True, alpha=0.35)

    colors = [ORANGE if s > 0 else TEAL for s in slope]
    ax2.bar(dist, slope, width=(dist.iloc[-1]/len(dist))*0.9, color=colors, alpha=0.75)
    ax2.axhline(0, color=GRID, lw=0.8)
    ax2.set_xlabel("Distance from Sasolburg (km)")
    ax2.set_ylabel("Slope (%)")
    ax2.grid(True, alpha=0.35)

    up_patch   = mpatches.Patch(color=ORANGE, label="Uphill (grade > 0%)")
    down_patch = mpatches.Patch(color=TEAL,   label="Downhill (grade < 0%)")
    ax2.legend(handles=[up_patch, down_patch], fontsize=8)

    fig.tight_layout()
    return _save(fig, "05_elevation_slope.png")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Solar irradiance breakdown
# ─────────────────────────────────────────────────────────────────────────────

def plot_solar_irradiance():
    t, GHI, DNI, DHI, cosθ, P = solar_profile()

    fig, axes = plt.subplots(2, 1, figsize=(13, 5), facecolor=BG, sharex=True)
    ax1, ax2 = axes

    ax1.fill_between(t, GHI, alpha=0.18, color=YELLOW)
    ax1.plot(t, GHI, color=YELLOW, lw=1.8, label="GHI (total)")
    ax1.plot(t, DNI, color=ORANGE, lw=1.5, ls="--", label="DNI (direct beam)")
    ax1.plot(t, DHI, color=TEAL,   lw=1.5, ls=":",  label="DHI (diffuse)")
    ax1.set_ylabel("Irradiance (W/m²)")
    ax1.set_title("Solar Irradiance Decomposition  —  (DNI·cosθ + DHI)·A·η",
                  fontweight="bold")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.35)

    ax2_twin = ax2.twinx()
    ax2.plot(t, cosθ, color=PURPLE, lw=1.8, label="cosθ (panel incidence)")
    ax2_twin.plot(t, P, color=GREEN, lw=2.0, ls="--", label="P_panel (W)")
    ax2.set_ylabel("cosθ", color=PURPLE)
    ax2_twin.set_ylabel("Panel Output (W)", color=GREEN)
    ax2.set_ylim(0, 1.1)
    ax2.grid(True, alpha=0.35)
    lines = ax2.get_lines() + ax2_twin.get_lines()
    ax2.legend(lines, [l.get_label() for l in lines], fontsize=8, loc="lower center")

    _time_axis(ax2, t)
    fig.tight_layout()
    return _save(fig, "06_solar_irradiance.png")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Cumulative energy budget
# ─────────────────────────────────────────────────────────────────────────────

def plot_energy_budget(time_s, solar_W, drive_W, aux_W):
    dt         = np.gradient(time_s)
    E_solar    = np.cumsum(solar_W  * dt) / 3_600_000     # kWh
    E_drive    = np.cumsum(drive_W  * dt) / 3_600_000
    E_aux      = np.cumsum(aux_W    * dt) / 3_600_000
    E_total    = E_drive + E_aux
    E_net      = E_solar - E_total

    fig, ax = plt.subplots(figsize=(13, 4), facecolor=BG)
    ax.plot(time_s, E_solar, color=YELLOW, lw=2.0, label="Cumulative solar input")
    ax.plot(time_s, E_drive, color=BLUE,   lw=1.8, label="Cumulative drivetrain")
    ax.plot(time_s, E_aux,   color=PINK,   lw=1.5, ls="--", label="Cumulative auxiliary")
    ax.plot(time_s, E_net,   color=GREEN,  lw=1.5, ls=":",  label="Net balance")
    ax.axhline(0, color=GRID, lw=0.8)
    ax.set_ylabel("Energy (kWh)")
    ax.set_title("Cumulative Energy Budget – All Terms", fontweight="bold")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(True, alpha=0.35)
    _time_axis(ax, time_s)
    fig.tight_layout()
    return _save(fig, "07_energy_budget.png")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Force decomposition
# ─────────────────────────────────────────────────────────────────────────────

def plot_force_decomposition(time_s, velocity_ms, route_df):
    """Show how aero, rolling, and grade forces share the load over the route."""
    n_route = len(route_df)
    n_sim   = len(time_s)
    n       = min(n_route, n_sim)

    slopes  = route_df["slope_pct"].values[:n]
    vs      = velocity_ms[:n]

    F_aero  = np.array([f_aero_N(v)       for v in vs])
    F_roll  = np.array([f_rolling_N(s)    for s in slopes])
    F_grade = np.array([f_grade_N(s)      for s in slopes])
    dist_km = route_df["cumulative_distance_m"].values[:n] / 1000

    fig, ax = plt.subplots(figsize=(13, 4), facecolor=BG)
    ax.stackplot(dist_km,
                 F_aero, F_roll, np.maximum(F_grade, 0),
                 labels=["Aerodynamic drag", "Rolling resistance", "Grade (uphill)"],
                 colors=[BLUE, ORANGE, RED], alpha=0.75)
    ax.fill_between(dist_km, 0, np.minimum(F_grade, 0),
                    color=GREEN, alpha=0.5, label="Grade (downhill / regen)")
    ax.axhline(0, color=GRID, lw=0.8)
    ax.set_xlabel("Distance from Sasolburg (km)")
    ax.set_ylabel("Force (N)")
    ax.set_title("Road-Load Force Decomposition Along Route", fontweight="bold")
    ax.legend(fontsize=8, loc="upper right", ncol=2)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return _save(fig, "08_force_decomposition.png")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Dashboard (2×3 master grid)
# ─────────────────────────────────────────────────────────────────────────────

def plot_dashboard(time_s, velocity_ms, soc, solar_W, drive_W, aux_W,
                   route_df, result_summary):
    v_kmh = ms_to_kmh(velocity_ms)
    pct   = soc * 100
    net   = solar_W - drive_W - aux_W

    fig = plt.figure(figsize=(16, 9), facecolor=BG)
    gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.42, wspace=0.35)

    panels = [fig.add_subplot(gs[r, c]) for r in range(2) for c in range(3)]
    for ax in panels:
        ax.set_facecolor(PANEL)
        ax.grid(True, alpha=0.3)

    ax_v, ax_s, ax_e, ax_p, ax_el, ax_f = panels

    # Velocity
    ax_v.plot(time_s, v_kmh, color=BLUE, lw=1.4)
    ax_v.axhline(ms_to_kmh(V_MAX_MS), color=RED, lw=0.9, ls="--")
    ax_v.set_title("Velocity (km/h)", fontweight="bold")
    ax_v.set_ylim(-5, 135)
    _time_axis(ax_v, time_s)

    # SOC
    ax_s.plot(time_s, pct, color=GREEN, lw=1.6)
    ax_s.axhline(MIN_SOC*100, color=RED, lw=1.2, ls="--")
    ax_s.fill_between(time_s, pct, MIN_SOC*100,
                      where=pct >= MIN_SOC*100, alpha=0.12, color=GREEN)
    ax_s.set_title("SOC (%)", fontweight="bold")
    ax_s.set_ylim(0, 105)
    _time_axis(ax_s, time_s)

    # Cumulative energy
    dt_arr  = np.gradient(time_s)
    E_sol   = np.cumsum(solar_W * dt_arr) / 3_600_000
    E_dem   = np.cumsum((drive_W + aux_W) * dt_arr) / 3_600_000
    ax_e.plot(time_s, E_sol, color=YELLOW, lw=1.4, label="Solar")
    ax_e.plot(time_s, E_dem, color=RED,    lw=1.4, label="Demand")
    ax_e.set_title("Energy (kWh)", fontweight="bold")
    ax_e.legend(fontsize=7)
    _time_axis(ax_e, time_s)

    # Power balance
    ax_p.plot(time_s, solar_W, color=YELLOW, lw=1.4, label="Solar")
    ax_p.plot(time_s, drive_W, color=BLUE,   lw=1.4, label="Drive")
    ax_p.axhline(P_AUXILIARY_W, color=PINK, lw=1.2, ls="--", label="Aux")
    ax_p.fill_between(time_s, solar_W, drive_W + aux_W,
                      where=net >= 0, alpha=0.12, color=GREEN)
    ax_p.fill_between(time_s, solar_W, drive_W + aux_W,
                      where=net < 0,  alpha=0.12, color=RED)
    ax_p.set_title("Power Balance (W)", fontweight="bold")
    ax_p.legend(fontsize=7)
    _time_axis(ax_p, time_s)

    # Elevation
    dist = route_df["cumulative_distance_m"] / 1000
    alt  = route_df["altitude_m"]
    ax_el.fill_between(dist, alt, alt.min()-30, alpha=0.28, color=BLUE)
    ax_el.plot(dist, alt, color=BLUE, lw=1.4)
    ax_el.set_title("Elevation (m)", fontweight="bold")
    ax_el.set_xlabel("Distance (km)")

    # Force decomposition (simplified)
    n    = min(len(route_df), len(velocity_ms))
    slp  = route_df["slope_pct"].values[:n]
    vs   = velocity_ms[:n]
    dist2 = route_df["cumulative_distance_m"].values[:n] / 1000
    ax_f.stackplot(dist2,
                   [f_aero_N(v) for v in vs],
                   [f_rolling_N(s) for s in slp],
                   colors=[BLUE, ORANGE], alpha=0.7,
                   labels=["Aero", "Rolling"])
    ax_f.set_title("Road Forces (N)", fontweight="bold")
    ax_f.legend(fontsize=7)
    ax_f.set_xlabel("Distance (km)")

    # Summary text
    txt = (f"Total: {result_summary.get('total_dist_km',0):.1f} km  |  "
           f"Loops: {result_summary.get('n_loops',0)} × 35 km  |  "
           f"Final SOC: {result_summary.get('final_soc',0)*100:.1f}%  |  "
           f"Arrival: {_hm(result_summary.get('arrival_time_s', RACE_START_S))}")
    fig.text(0.5, 0.98, "Sasol Solar Challenge – Day 2  │  Master Equation Dashboard",
             ha="center", va="top", fontsize=13, fontweight="bold", color=FG)
    fig.text(0.5, 0.005, txt, ha="center", va="bottom", fontsize=9, color=BLUE)

    return _save(fig, "09_dashboard.png")


# ─────────────────────────────────────────────────────────────────────────────
# Convenience wrapper
# ─────────────────────────────────────────────────────────────────────────────

def generate_all_plots(time_s, velocity_ms, soc, solar_W, drive_W, aux_W,
                       route_df, events, result_summary):
    paths = []
    paths.append(plot_velocity(time_s, velocity_ms, events))
    paths.append(plot_soc(time_s, soc, events))
    paths.append(plot_acceleration(time_s, velocity_ms))
    paths.append(plot_power_balance(time_s, solar_W, drive_W, aux_W))
    paths.append(plot_elevation(route_df))
    paths.append(plot_solar_irradiance())
    paths.append(plot_energy_budget(time_s, solar_W, drive_W, aux_W))
    paths.append(plot_force_decomposition(time_s, velocity_ms, route_df))
    paths.append(plot_dashboard(time_s, velocity_ms, soc, solar_W,
                                drive_W, aux_W, route_df, result_summary))
    return paths
