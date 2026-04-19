"""
visualizer.py
=============
Phase 3 – The Analyst

Generates all required and supplementary plots:
  1. Velocity Profile
  2. SOC Profile
  3. Acceleration Profile
  4. Power Balance (Solar vs Demand)
  5. Elevation Profile + slope colouring
  6. Solar Irradiance curve
  7. Summary dashboard figure
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib.collections import LineCollection
from matplotlib import cm
import pandas as pd
import os

from solar_model import solar_profile, RACE_START_S, RACE_END_S
from physics import ms_to_kmh, BATTERY_CAPACITY_WH, MIN_SOC

PLOTS_DIR = "plots"
os.makedirs(PLOTS_DIR, exist_ok=True)

# ── aesthetics ─────────────────────────────────────────────────────────────────
DARK_BG    = "#0d1117"
PANEL_BG   = "#161b22"
GRID_COL   = "#21262d"
TEXT_COL   = "#c9d1d9"
ACCENT     = "#58a6ff"
ORANGE     = "#f0883e"
GREEN      = "#3fb950"
RED        = "#f85149"
PURPLE     = "#bc8cff"
YELLOW     = "#e3b341"

plt.rcParams.update({
    "figure.facecolor":  DARK_BG,
    "axes.facecolor":    PANEL_BG,
    "axes.edgecolor":    GRID_COL,
    "axes.labelcolor":   TEXT_COL,
    "xtick.color":       TEXT_COL,
    "ytick.color":       TEXT_COL,
    "grid.color":        GRID_COL,
    "text.color":        TEXT_COL,
    "legend.facecolor":  PANEL_BG,
    "legend.edgecolor":  GRID_COL,
    "font.family":       "monospace",
    "font.size":         10,
})


def _time_label(t_s):
    """Convert seconds-since-midnight to HH:MM string."""
    h = int(t_s // 3600)
    m = int((t_s % 3600) // 60)
    return f"{h:02d}:{m:02d}"


def _time_axis(ax, t_array):
    """Replace numeric x-axis with HH:MM labels."""
    ticks = np.arange(RACE_START_S, RACE_END_S + 1, 3600)
    ax.set_xticks(ticks)
    ax.set_xticklabels([_time_label(t) for t in ticks], fontsize=8)
    ax.set_xlabel("Time of Day")


def shade_stops(ax, events):
    """Shade control/loop-stop periods as grey bands."""
    for ev in events:
        if ev["type"] in ("control_stop", "loop_stop"):
            ax.axvspan(ev["t_start"], ev["t_end"],
                       color="#888888", alpha=0.18, zorder=0)


# ── individual plots ────────────────────────────────────────────────────────────

def plot_velocity(time_s, velocity_kmh, events, filename="velocity_profile.png"):
    fig, ax = plt.subplots(figsize=(12, 4), facecolor=DARK_BG)
    shade_stops(ax, events)
    ax.plot(time_s, velocity_kmh, color=ACCENT, lw=1.8, label="Vehicle Speed")
    ax.axhline(120, color=RED,    lw=1.2, ls="--", label="Speed limit (120 km/h)")
    ax.axhline(0,   color=GRID_COL, lw=0.8)

    # Mark arrival at Zeerust
    for ev in events:
        if ev["type"] == "control_stop":
            ax.axvline(ev["t_start"], color=ORANGE, lw=1.5, ls=":", alpha=0.9)
            ax.text(ev["t_start"] + 60, ax.get_ylim()[1] * 0.92,
                    "Zeerust", color=ORANGE, fontsize=8, va="top")
            break

    ax.set_ylabel("Speed (km/h)")
    ax.set_title("Velocity Profile – Sasol Solar Challenge Day 2", fontweight="bold")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.4)
    ax.set_ylim(-5, 135)
    _time_axis(ax, time_s)
    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved → {path}")
    return path


def plot_soc(time_s, soc, events, filename="soc_profile.png"):
    fig, ax = plt.subplots(figsize=(12, 4), facecolor=DARK_BG)
    shade_stops(ax, events)

    # Colour-code SOC line: green > 50%, yellow 20-50%, red < 20%
    soc_pct = soc * 100
    ax.plot(time_s, soc_pct, color=GREEN, lw=2.0, label="Battery SOC")
    ax.axhline(MIN_SOC * 100, color=RED, lw=1.8, ls="--",
               label=f"Min SOC ({int(MIN_SOC*100)}%)")
    ax.fill_between(time_s, soc_pct, MIN_SOC * 100,
                    where=soc_pct >= MIN_SOC * 100,
                    alpha=0.12, color=GREEN)
    ax.fill_between(time_s, soc_pct, MIN_SOC * 100,
                    where=soc_pct < MIN_SOC * 100,
                    alpha=0.25, color=RED)

    ax.set_ylabel("State of Charge (%)")
    ax.set_ylim(0, 105)
    ax.set_title("Battery State of Charge – Sasol Solar Challenge Day 2",
                 fontweight="bold")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.4)
    _time_axis(ax, time_s)
    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved → {path}")
    return path


def plot_acceleration(time_s, velocity_ms, filename="acceleration_profile.png"):
    # Compute acceleration as finite difference
    dt    = np.diff(time_s)
    dt    = np.where(dt < 1e-6, 1e-6, dt)
    accel = np.diff(velocity_ms) / dt
    accel = np.append(accel, accel[-1])   # repeat last for same length

    fig, ax = plt.subplots(figsize=(12, 4), facecolor=DARK_BG)
    ax.plot(time_s, accel, color=PURPLE, lw=1.4, label="Acceleration")
    ax.axhline( 1.5, color=ORANGE, lw=1.2, ls="--", label="Max accel (+1.5 m/s²)")
    ax.axhline(-2.5, color=RED,    lw=1.2, ls="--", label="Max decel (−2.5 m/s²)")
    ax.axhline(0,    color=GRID_COL, lw=0.8)
    ax.set_ylabel("Acceleration (m/s²)")
    ax.set_title("Acceleration Profile – Sasol Solar Challenge Day 2",
                 fontweight="bold")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.4)
    ax.set_ylim(-4, 4)
    _time_axis(ax, time_s)
    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved → {path}")
    return path


def plot_power_balance(time_s, solar_W, demand_W, filename="power_balance.png"):
    net = solar_W - demand_W   # positive = charging

    fig, ax = plt.subplots(figsize=(12, 4), facecolor=DARK_BG)
    ax.plot(time_s, solar_W,  color=YELLOW, lw=1.8, label="Solar Power (W)")
    ax.plot(time_s, demand_W, color=RED,    lw=1.8, label="Motor Demand (W)")
    ax.fill_between(time_s, solar_W, demand_W,
                    where=net >= 0, alpha=0.2, color=GREEN,
                    label="Net charge")
    ax.fill_between(time_s, solar_W, demand_W,
                    where=net < 0, alpha=0.2, color=RED,
                    label="Net discharge")
    ax.set_ylabel("Power (W)")
    ax.set_title("Power Balance – Solar vs Motor Demand",  fontweight="bold")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.4)
    _time_axis(ax, time_s)
    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved → {path}")
    return path


def plot_elevation(route_df, filename="elevation_profile.png"):
    dist_km  = route_df["cumulative_distance_m"] / 1000
    alt_m    = route_df["altitude_m"]
    slope    = route_df["slope_pct"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 5),
                                   facecolor=DARK_BG, sharex=True)

    # Elevation with slope-coloured fill
    ax1.fill_between(dist_km, alt_m, alt_m.min() - 20,
                     alpha=0.35, color=ACCENT)
    ax1.plot(dist_km, alt_m, color=ACCENT, lw=1.8)
    ax1.set_ylabel("Altitude (m)")
    ax1.set_title("Route Elevation & Slope – Sasolburg → Zeerust",
                  fontweight="bold")
    ax1.grid(True, alpha=0.4)

    # Slope
    colors = np.where(slope > 0, ORANGE, GREEN)
    ax2.bar(dist_km, slope, width=0.3, color=colors, alpha=0.8)
    ax2.axhline(0, color=GRID_COL, lw=0.8)
    ax2.set_xlabel("Distance from Start (km)")
    ax2.set_ylabel("Slope (%)")
    ax2.grid(True, alpha=0.4)

    pos_patch = mpatches.Patch(color=ORANGE, label="Uphill")
    neg_patch = mpatches.Patch(color=GREEN,  label="Downhill")
    ax2.legend(handles=[pos_patch, neg_patch], loc="upper right")

    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved → {path}")
    return path


def plot_solar_irradiance(filename="solar_irradiance.png"):
    t, G, P = solar_profile()

    fig, ax1 = plt.subplots(figsize=(10, 4), facecolor=DARK_BG)
    ax2 = ax1.twinx()

    ax1.fill_between(t, G, alpha=0.25, color=YELLOW)
    ax1.plot(t, G, color=YELLOW, lw=2.0, label="Irradiance (W/m²)")
    ax2.plot(t, P, color=ORANGE, lw=2.0, ls="--", label="Panel Power (W)")

    ax1.set_ylabel("Irradiance (W/m²)", color=YELLOW)
    ax2.set_ylabel("Panel Power Output (W)", color=ORANGE)
    ax1.set_title("Solar Irradiance & Panel Output – Gaussian Model",
                  fontweight="bold")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
    ax1.grid(True, alpha=0.4)
    _time_axis(ax1, t)
    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved → {path}")
    return path


def plot_energy_budget(time_s, solar_W, demand_W, filename="energy_budget.png"):
    """Cumulative energy plot — shows total energy in/out over the day."""
    dt        = np.gradient(time_s)
    E_solar   = np.cumsum(solar_W  * dt) / 3_600_000   # kWh
    E_demand  = np.cumsum(demand_W * dt) / 3_600_000
    E_net     = E_solar - E_demand

    fig, ax = plt.subplots(figsize=(12, 4), facecolor=DARK_BG)
    ax.plot(time_s, E_solar,  color=YELLOW, lw=2.0, label="Cumulative Solar (kWh)")
    ax.plot(time_s, E_demand, color=RED,    lw=2.0, label="Cumulative Motor (kWh)")
    ax.plot(time_s, E_net,    color=GREEN,  lw=1.5, ls="--",
            label="Net Energy Balance (kWh)")
    ax.axhline(0, color=GRID_COL, lw=0.8)
    ax.set_ylabel("Energy (kWh)")
    ax.set_title("Cumulative Energy Budget Throughout Day 2", fontweight="bold")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.4)
    _time_axis(ax, time_s)
    fig.tight_layout()
    path = os.path.join(PLOTS_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved → {path}")
    return path


def plot_dashboard(time_s, velocity_kmh, soc, solar_W, demand_W, route_df,
                   result_summary: dict, filename="dashboard.png"):
    """
    Master summary figure — 2×2 grid of the most important plots.
    """
    fig = plt.figure(figsize=(16, 9), facecolor=DARK_BG)
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.38, wspace=0.32)

    ax_v   = fig.add_subplot(gs[0, 0])
    ax_soc = fig.add_subplot(gs[0, 1])
    ax_pwr = fig.add_subplot(gs[1, 0])
    ax_ele = fig.add_subplot(gs[1, 1])

    for ax in [ax_v, ax_soc, ax_pwr, ax_ele]:
        ax.set_facecolor(PANEL_BG)
        ax.grid(True, alpha=0.3)

    # Velocity
    ax_v.plot(time_s, velocity_kmh, color=ACCENT, lw=1.6)
    ax_v.axhline(120, color=RED, lw=1.0, ls="--", alpha=0.7)
    ax_v.set_title("Velocity (km/h)", fontweight="bold")
    ax_v.set_ylabel("km/h")
    ax_v.set_ylim(-5, 135)
    _time_axis(ax_v, time_s)

    # SOC
    soc_pct = soc * 100
    ax_soc.plot(time_s, soc_pct, color=GREEN, lw=1.6)
    ax_soc.axhline(MIN_SOC * 100, color=RED, lw=1.2, ls="--")
    ax_soc.fill_between(time_s, soc_pct, MIN_SOC * 100,
                         where=soc_pct >= MIN_SOC * 100, alpha=0.15, color=GREEN)
    ax_soc.set_title("Battery SOC (%)", fontweight="bold")
    ax_soc.set_ylabel("%")
    ax_soc.set_ylim(0, 105)
    _time_axis(ax_soc, time_s)

    # Power balance
    net = solar_W - demand_W
    ax_pwr.plot(time_s, solar_W,  color=YELLOW, lw=1.4, label="Solar")
    ax_pwr.plot(time_s, demand_W, color=RED,    lw=1.4, label="Motor")
    ax_pwr.fill_between(time_s, solar_W, demand_W,
                         where=net >= 0, alpha=0.15, color=GREEN)
    ax_pwr.fill_between(time_s, solar_W, demand_W,
                         where=net < 0, alpha=0.15, color=RED)
    ax_pwr.set_title("Power Balance (W)", fontweight="bold")
    ax_pwr.set_ylabel("W")
    ax_pwr.legend(fontsize=8)
    _time_axis(ax_pwr, time_s)

    # Elevation
    dist_km = route_df["cumulative_distance_m"] / 1000
    alt_m   = route_df["altitude_m"]
    ax_ele.fill_between(dist_km, alt_m, alt_m.min() - 20,
                         alpha=0.3, color=ACCENT)
    ax_ele.plot(dist_km, alt_m, color=ACCENT, lw=1.6)
    ax_ele.set_title("Elevation Profile (m)", fontweight="bold")
    ax_ele.set_ylabel("Altitude (m)")
    ax_ele.set_xlabel("Distance (km)")

    # Summary text overlay
    summary = (
        f"Total Distance: {result_summary.get('total_dist_km', 0):.1f} km\n"
        f"Loops: {result_summary.get('n_loops', 0)}  ×  35 km\n"
        f"Final SOC: {result_summary.get('final_soc', 0)*100:.1f}%\n"
        f"Arrival: {_time_label(result_summary.get('arrival_time_s', 0))}"
    )
    fig.text(0.5, 0.98, "Sasol Solar Challenge – Day 2  |  Strategy Dashboard",
             ha="center", va="top", fontsize=14, fontweight="bold", color=TEXT_COL)
    fig.text(0.01, 0.02, summary, va="bottom", ha="left",
             fontsize=9, color=ACCENT,
             bbox=dict(facecolor=PANEL_BG, edgecolor=GRID_COL,
                       boxstyle="round,pad=0.4"))

    path = os.path.join(PLOTS_DIR, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved → {path}")
    return path


def generate_all_plots(full_time_s, full_velocity_ms, full_soc,
                       full_solar_W, full_demand_W,
                       route_df, events, result_summary):
    """
    Convenience wrapper: generate every standard plot.
    """
    v_kmh = ms_to_kmh(full_velocity_ms)
    paths = []
    paths.append(plot_velocity(full_time_s, v_kmh, events))
    paths.append(plot_soc(full_time_s, full_soc, events))
    paths.append(plot_acceleration(full_time_s, full_velocity_ms))
    paths.append(plot_power_balance(full_time_s, full_solar_W, full_demand_W))
    paths.append(plot_elevation(route_df))
    paths.append(plot_solar_irradiance())
    paths.append(plot_energy_budget(full_time_s, full_solar_W, full_demand_W))
    paths.append(plot_dashboard(full_time_s, v_kmh, full_soc,
                                full_solar_W, full_demand_W,
                                route_df, result_summary))
    return paths
