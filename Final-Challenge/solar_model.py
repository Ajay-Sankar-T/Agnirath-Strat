"""
solar_model.py
==============
Implements the solar input term of the master power balance equation:

    P_solar = (DNI·cosθ  +  DHI)  ×  A  ×  η_panel

Where:
    DNI  = Direct Normal Irradiance  — beam radiation (W/m²)
    DHI  = Diffuse Horizontal Irradiance — sky scatter (W/m²)
    cosθ = cosine of incidence angle between sun beam and panel normal
    A    = panel area (m²)
    η    = panel efficiency

The total GHI (Global Horizontal Irradiance) is modelled as a Gaussian:

    GHI(t) = G_peak · exp( -(t - t_noon)² / (2σ²) )

Then split into:
    DNI = GHI · (1 - DHI_fraction)
    DHI = GHI · DHI_fraction

The incidence angle θ depends on panel tilt, azimuth, and solar position.
For a horizontal car roof in South Africa in October, the sun transits
slightly north of overhead. We model this with a fixed mean incidence
angle (MEAN_INCIDENCE_DEG) rather than a full sun-position model —
this captures the cosθ loss without requiring latitude/longitude inputs
at every time step.
"""

import numpy as np
from constants import (
    PEAK_DNI, SOLAR_NOON_S, SIGMA_S,
    PANEL_AREA_M2, PANEL_EFF,
    PANEL_TILT_DEG, MEAN_INCIDENCE_DEG, DHI_FRACTION,
    RACE_START_S, RACE_END_S,
)


# ─────────────────────────────────────────────────────────────────────────────
# Core irradiance model
# ─────────────────────────────────────────────────────────────────────────────

def ghi_W_m2(t_s: float) -> float:
    """
    Global Horizontal Irradiance [W/m²] at time t_s (seconds since midnight).
    Gaussian model: GHI(t) = G_peak · exp(-(t - t_noon)² / 2σ²)
    Clamped to ≥ 0.
    """
    return float(np.maximum(
        PEAK_DNI * np.exp(-((t_s - SOLAR_NOON_S) ** 2) / (2.0 * SIGMA_S ** 2)),
        0.0
    ))


def dni_dhi_W_m2(t_s: float) -> tuple[float, float]:
    """
    Split GHI into Direct Normal Irradiance and Diffuse Horizontal Irradiance.

    Returns
    -------
    (DNI, DHI)  both in W/m²
    """
    G   = ghi_W_m2(t_s)
    dhi = G * DHI_FRACTION
    dni = G * (1.0 - DHI_FRACTION)
    return dni, dhi


def cos_incidence(t_s: float) -> float:
    """
    Cosine of the angle between the sun beam and the panel normal.

    For a horizontal panel in South Africa (lat ~26°S) in October, the sun
    is slightly north of overhead, producing a time-varying incidence angle.
    We approximate this with a sinusoidal variation around the mean:

        θ(t) = MEAN_INCIDENCE_DEG · (1 + 0.3·sin(π·(t - t_rise)/(t_set - t_rise)))

    This peaks near noon and tapers at dawn/dusk, which is physically correct —
    the incidence angle is smallest (cosθ largest) when the sun is highest.
    """
    # Approximate sunrise/sunset for Oct in South Africa
    t_rise = 6   * 3600    # 06:00
    t_set  = 18  * 3600    # 18:00

    # Normalised position in daylight window [0, 1]
    frac = np.clip((t_s - t_rise) / (t_set - t_rise), 0.0, 1.0)

    # Incidence is smallest at solar noon (frac ≈ 0.5) → sinusoid centred at noon
    angle_deg = MEAN_INCIDENCE_DEG * (1.0 - 0.4 * np.sin(np.pi * frac))
    return float(np.cos(np.radians(angle_deg)))


def solar_power_W(t_s: float) -> float:
    """
    Net electrical power from the solar array [W] using the full master equation:

        P_solar = (DNI·cosθ  +  DHI)  ×  A  ×  η

    Parameters
    ----------
    t_s : float
        Seconds since midnight (SAST, UTC+2).

    Returns
    -------
    float
        Panel electrical output in Watts.
    """
    dni, dhi   = dni_dhi_W_m2(t_s)
    cos_theta  = cos_incidence(t_s)
    irr_panel  = dni * cos_theta + dhi          # effective irradiance on panel surface
    return float(np.maximum(irr_panel * PANEL_AREA_M2 * PANEL_EFF, 0.0))


def total_solar_energy_J(t_start_s: float, t_end_s: float,
                          n_steps: int = 2000) -> float:
    """Numerically integrate solar energy over [t_start_s, t_end_s] in Joules."""
    t = np.linspace(t_start_s, t_end_s, n_steps)
    P = np.array([solar_power_W(ti) for ti in t])
    dt = (t_end_s - t_start_s) / (n_steps - 1)
    return float(np.sum(P) * dt)


def solar_profile(t_start_s=RACE_START_S, t_end_s=RACE_END_S, dt_s=60.0):
    """Return (time_s, GHI, DNI, DHI, cosθ, P_panel) arrays for the race window."""
    t      = np.arange(t_start_s, t_end_s + dt_s, dt_s)
    GHI    = np.array([ghi_W_m2(ti)        for ti in t])
    DNIs   = np.array([dni_dhi_W_m2(ti)[0] for ti in t])
    DHIs   = np.array([dni_dhi_W_m2(ti)[1] for ti in t])
    cosθs  = np.array([cos_incidence(ti)   for ti in t])
    P      = np.array([solar_power_W(ti)   for ti in t])
    return t, GHI, DNIs, DHIs, cosθs, P


if __name__ == "__main__":
    print("=== Solar Model Sanity Check ===")
    print(f"{'Hour':>6} | {'GHI':>8} | {'DNI':>8} | {'DHI':>7} | {'cosθ':>6} | {'P_panel':>8}")
    print("-" * 55)
    for h in range(6, 19):
        t = h * 3600
        G = ghi_W_m2(t)
        d, dh = dni_dhi_W_m2(t)
        c = cos_incidence(t)
        P = solar_power_W(t)
        print(f"  {h:02d}:00 | {G:7.1f}W | {d:7.1f}W | {dh:6.1f}W | {c:5.3f} | {P:7.1f}W")

    E = total_solar_energy_J(RACE_START_S, RACE_END_S)
    print(f"\nTotal solar energy (race window): {E/3_600_000:.3f} kWh")
