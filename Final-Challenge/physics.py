"""
physics.py
==========
Implements the complete master power balance equation:

    V_batt · C_rated · SOH · d(SOC)/dt  +  (DNI·cosθ + DHI)·A·η_solar
        =  [1/η_m  −  η_r] · [m·a·v  +  ½ρ·Cd·A·v³  +  μ·m·g·v·cosθ_road  +  m·g·v·sinθ_road]
           +  (P_inverter  +  P_heat)
           +  (P_lights  +  P_telemetry  +  P_other)

Rearranged for d(SOC)/dt:

    d(SOC)/dt = [P_solar  −  P_drivetrain  −  P_auxiliary]
                / [V_batt · C_rated · SOH · 3600]

Sign convention
---------------
    P_drivetrain > 0  →  motoring   (battery discharges)
    P_drivetrain < 0  →  regen      (battery charges)
    P_auxiliary  > 0  →  always discharging
    P_solar      > 0  →  always charging
"""

import numpy as np
from constants import (
    VEHICLE_MASS_KG, DRAG_COEFF, FRONTAL_AREA_M2,
    ROLLING_COEFF, G_ACC, AIR_DENSITY,
    ETA_MOTOR, ETA_REGEN,
    V_BATTERY_NOM, C_RATED_AH, SOH,
    BATTERY_CAPACITY_WH, BATTERY_CAPACITY_J,
    P_AUXILIARY_W,
    V_MAX_MS, V_MIN_DRIVE_MS, A_MAX_MS2, A_MIN_MS2,
    INITIAL_SOC, MIN_SOC,
)


# ─────────────────────────────────────────────────────────────────────────────
# Force decomposition
# ─────────────────────────────────────────────────────────────────────────────

def f_accel_N(accel_ms2: float) -> float:
    """Inertial force: F = m·a"""
    return VEHICLE_MASS_KG * accel_ms2


def f_aero_N(v_ms: float) -> float:
    """Aerodynamic drag force: ½·ρ·Cd·A·v²"""
    return 0.5 * AIR_DENSITY * DRAG_COEFF * FRONTAL_AREA_M2 * v_ms ** 2


def f_rolling_N(slope_pct: float) -> float:
    """Rolling resistance: μ_rr · m · g · cos(θ_road)"""
    theta = np.arctan(slope_pct / 100.0)
    return ROLLING_COEFF * VEHICLE_MASS_KG * G_ACC * np.cos(theta)


def f_grade_N(slope_pct: float) -> float:
    """Grade resistance: m · g · sin(θ_road)  (+ uphill, − downhill)"""
    theta = np.arctan(slope_pct / 100.0)
    return VEHICLE_MASS_KG * G_ACC * np.sin(theta)


# ─────────────────────────────────────────────────────────────────────────────
# Master equation: drivetrain power term
# ─────────────────────────────────────────────────────────────────────────────

def drivetrain_power_W(v_ms: float, slope_pct: float,
                       accel_ms2: float = 0.0) -> float:
    """
    Drivetrain power demand from the battery [W] using the master equation bracket:

        P_drive = [1/η_m  −  η_r] · [m·a·v  +  ½ρ·Cd·A·v³  +  μ·m·g·v·cosθ  +  m·g·v·sinθ]

    Wait — that's not right dimensionally. The correct interpretation of the
    master equation bracket is that η_m applies when motoring and η_r applies
    when regenerating. The bracket selects one efficiency branch:

        if P_mech ≥ 0:   P_battery = P_mech / η_m         (motor draws more)
        if P_mech <  0:   P_battery = P_mech × η_r         (regen returns less)

    This is equivalent to: P_battery = P_mech · (1/η_m) for motor,
                                        P_battery = P_mech · η_r  for regen.
    The master equation writes this compactly as [1/η_m − η_r] selecting the
    appropriate branch by sign of P_mech.

    Parameters
    ----------
    v_ms      : speed (m/s)
    slope_pct : road grade (%, + uphill)
    accel_ms2 : vehicle acceleration (m/s²)

    Returns
    -------
    float : power in W (positive = discharge, negative = regen charge)
    """
    if v_ms < 1e-6:
        return 0.0

    # Mechanical power at the wheel [W]  — master equation inner bracket
    P_mech = (
          f_accel_N(accel_ms2) * v_ms          # m·a·v
        + f_aero_N(v_ms)       * v_ms          # ½ρCdAv³  (= f_aero × v)
        + f_rolling_N(slope_pct) * v_ms        # μ·m·g·cosθ·v
        + f_grade_N(slope_pct)   * v_ms        # m·g·sinθ·v
    )

    # Apply efficiency branch: [1/η_m] motoring | [η_r] regenerating
    if P_mech >= 0:
        return P_mech / ETA_MOTOR              # battery supplies more than wheel needs
    else:
        return P_mech * ETA_REGEN              # regen returns less than wheel produces


def auxiliary_power_W() -> float:
    """
    Total auxiliary / parasitic load [W] — the constant always-on term:
        P_inverter + P_heat + P_lights + P_telemetry + P_other
    """
    return P_AUXILIARY_W


# ─────────────────────────────────────────────────────────────────────────────
# Master equation: SOC update
# ─────────────────────────────────────────────────────────────────────────────

def soc_derivative(soc: float, P_solar_W: float,
                   P_drive_W: float) -> float:
    """
    d(SOC)/dt from the master power balance equation:

        V_batt · C_rated · SOH · d(SOC)/dt = P_solar − P_drive − P_aux

    Rearranged:
        d(SOC)/dt = (P_solar − P_drive − P_aux) / (V_batt · C_rated · SOH · 3600)

    The denominator has units of [V · Ah] = [Wh], converted to [Ws = J] via ×3600.

    Returns
    -------
    float : d(SOC)/dt in s⁻¹  (i.e. SOC change per second)
    """
    net_power_W    = P_solar_W - P_drive_W - P_AUXILIARY_W
    # V_batt × C_rated × SOH gives usable Wh; ×3600 → Ws (joules)
    denom_J        = V_BATTERY_NOM * C_RATED_AH * SOH * 3_600.0
    return net_power_W / denom_J


def soc_update(soc: float, P_solar_W: float,
               P_drive_W: float, dt_s: float) -> float:
    """
    Euler integration of d(SOC)/dt over time step dt_s.

    Parameters
    ----------
    soc       : current SOC [0, 1]
    P_solar_W : solar panel output (W)
    P_drive_W : drivetrain power from battery (W)
    dt_s      : time step (s)

    Returns
    -------
    float : new SOC, clamped to [0, 1]
    """
    dsoc    = soc_derivative(soc, P_solar_W, P_drive_W)
    new_soc = soc + dsoc * dt_s
    return float(np.clip(new_soc, 0.0, 1.0))


# ─────────────────────────────────────────────────────────────────────────────
# Net power balance (convenience)
# ─────────────────────────────────────────────────────────────────────────────

def net_power_W(P_solar_W: float, P_drive_W: float) -> float:
    """
    Net power flowing into battery [W].
    Positive  → battery charging
    Negative  → battery discharging
    """
    return P_solar_W - P_drive_W - P_AUXILIARY_W


# ─────────────────────────────────────────────────────────────────────────────
# Unit helpers
# ─────────────────────────────────────────────────────────────────────────────

def ms_to_kmh(v): return v * 3.6
def kmh_to_ms(v): return v / 3.6


if __name__ == "__main__":
    from solar_model import solar_power_W

    print("=== Physics Master Equation Check ===")
    print(f"\nAuxiliary load: {auxiliary_power_W():.0f} W  (always-on)")
    print(f"\n{'Speed':>8} | {'Slope':>6} | {'P_drive':>9} | {'P_solar@noon':>13} | {'Net':>8}")
    print("-" * 55)
    t_noon = 12 * 3600
    for v_kmh, sl in [(60,0),(80,0),(100,0),(80,2),(80,-2),(100,0)]:
        v  = kmh_to_ms(v_kmh)
        Pd = drivetrain_power_W(v, sl)
        Ps = solar_power_W(t_noon)
        Pn = net_power_W(Ps, Pd)
        print(f"  {v_kmh:3d} km/h | {sl:+5.1f}% | {Pd:8.0f} W | {Ps:12.0f} W | {Pn:+7.0f} W")

    print(f"\nBattery: {V_BATTERY_NOM}V × {C_RATED_AH}Ah × SOH{SOH} = {BATTERY_CAPACITY_WH:.0f} Wh")
    print(f"Usable window (20–80%): {(0.80-0.20)*BATTERY_CAPACITY_WH:.0f} Wh")
