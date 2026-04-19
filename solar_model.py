"""
solar_model.py
==============
Phase 1 – The Solar Model

Computes incident solar irradiance and net panel power as a function of time,
using a Gaussian approximation of the diurnal solar curve.

Key parameters (from Sasol Solar Challenge orientation):
  Panel area       : 4.0  m²   (typical top-surface of a solar car)
  Panel efficiency : 0.224      (22.4 % — high-grade mono-crystalline Si)
  Peak irradiance  : 1073 W/m²  at solar noon (12:00 PM local time)
  Gaussian σ       : 11 600 s   (~3.22 h) — gives realistic dawn/dusk ramp

Usage:
  from solar_model import solar_power_W, irradiance_W_m2
  P = solar_power_W(t_seconds_since_midnight)
"""

import numpy as np

# ── panel constants ────────────────────────────────────────────────────────────
PANEL_AREA_M2      = 4.0          # m²
PANEL_EFFICIENCY   = 0.224        # dimensionless  (22.4 %)

# ── irradiance curve constants ─────────────────────────────────────────────────
PEAK_IRRADIANCE    = 1073.0       # W/m²  at solar noon
SOLAR_NOON_S       = 12 * 3600    # seconds since midnight  →  43 200 s
SIGMA_S            = 11_600.0     # standard deviation in seconds

# ── race window ────────────────────────────────────────────────────────────────
RACE_START_S       = 8  * 3600   # 08:00
RACE_END_S         = 17 * 3600   # 17:00


def irradiance_W_m2(t_s: float) -> float:
    """
    Incident solar irradiance [W/m²] at time t_s (seconds since midnight).

    Model:  G(t) = G_peak · exp( -(t - t_noon)² / (2σ²) )

    The Gaussian naturally goes to zero before sunrise and after sunset, which
    is physically correct for South Africa in October (Sasol race month).
    Negative values are clamped to zero (no 'negative sun').

    Parameters
    ----------
    t_s : float
        Seconds since midnight (local South African Standard Time, UTC+2).

    Returns
    -------
    float
        Irradiance in W/m².
    """
    exponent = -((t_s - SOLAR_NOON_S) ** 2) / (2.0 * SIGMA_S ** 2)
    G = PEAK_IRRADIANCE * np.exp(exponent)
    return float(np.maximum(G, 0.0))


def solar_power_W(t_s: float) -> float:
    """
    Net electrical power delivered by the solar array [W].

    P_solar(t) = G(t) · A_panel · η_panel

    Parameters
    ----------
    t_s : float
        Seconds since midnight.

    Returns
    -------
    float
        Solar panel output in Watts.
    """
    G = irradiance_W_m2(t_s)
    return G * PANEL_AREA_M2 * PANEL_EFFICIENCY


def total_solar_energy_J(t_start_s: float, t_end_s: float,
                          n_steps: int = 1000) -> float:
    """
    Numerically integrate solar energy available over [t_start_s, t_end_s].

    Returns
    -------
    float
        Energy in Joules.
    """
    t = np.linspace(t_start_s, t_end_s, n_steps)
    P = np.array([solar_power_W(ti) for ti in t])
    return float(np.trapezoid(P, t) if hasattr(np, 'trapezoid') else np.trapz(P, t))


def solar_profile(t_start_s: float = RACE_START_S,
                  t_end_s: float   = RACE_END_S,
                  dt_s: float      = 60.0):
    """
    Return arrays of (time_s, irradiance, power) for the race window.
    Useful for plotting.
    """
    t = np.arange(t_start_s, t_end_s + dt_s, dt_s)
    G = np.array([irradiance_W_m2(ti) for ti in t])
    P = G * PANEL_AREA_M2 * PANEL_EFFICIENCY
    return t, G, P


if __name__ == "__main__":
    # Quick sanity check
    print("=== Solar Model Sanity Check ===")
    for hour in [8, 10, 12, 14, 16]:
        t = hour * 3600
        print(f"  {hour:02d}:00  |  G = {irradiance_W_m2(t):7.1f} W/m²  "
              f"|  P_panel = {solar_power_W(t):6.1f} W")

    E_day = total_solar_energy_J(RACE_START_S, RACE_END_S)
    print(f"\nTotal solar energy available during race window: "
          f"{E_day/3_600_000:.3f} kWh")
    print(f"Panel area: {PANEL_AREA_M2} m²  |  Efficiency: {PANEL_EFFICIENCY*100:.1f} %")
