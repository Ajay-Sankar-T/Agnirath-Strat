"""
physics.py
==========
Vehicle physics and energy model for the Sasol Solar Car.

All parameters are kept in one place so the optimiser can call
  power_demand_W(v, slope_pct, dt)
without worrying about the underlying mechanics.

Energy sign convention
----------------------
  Positive  →  energy OUT of battery  (motor draw)
  Negative  →  energy INTO battery    (regen or solar)

The battery SOC equation at each time-step is:
  E_batt(t+dt) = E_batt(t) + P_solar(t)·dt − P_demand(t)·dt
"""

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# Vehicle Constants  (Sasol / Wits Solar Car class)
# ─────────────────────────────────────────────────────────────────────────────

# Mass
VEHICLE_MASS_KG     = 250.0        # car + driver (kg)

# Aerodynamics
DRAG_COEFFICIENT    = 0.13         # Cd  — very low for solar car bodywork
FRONTAL_AREA_M2     = 0.95         # A   (m²)
AIR_DENSITY         = 1.225        # ρ   (kg/m³) at sea level / 1500 m correction below

# Rolling resistance
ROLLING_COEFF       = 0.003        # Crr — specialised solar-car tyres

# Gravity
G_ACC               = 9.81         # m/s²

# Drivetrain
MOTOR_EFFICIENCY    = 0.92         # η_motor (motor + controller combined)
REGEN_EFFICIENCY    = 0.70         # η_regen (less efficient on recovery)
MAX_MOTOR_POWER_W   = 2_000.0      # continuous motor power limit (W)

# Battery
BATTERY_CAPACITY_WH = 5_000.0      # 5 kWh — realistic for a top-class solar car
BATTERY_CAPACITY_J  = BATTERY_CAPACITY_WH * 3_600.0
INITIAL_SOC         = 0.80         # 80 % at start of Day 2
MIN_SOC             = 0.20         # 20 % hard floor (survival constraint)

# Velocity limits
V_MIN_MS            = 0.0          # m/s
V_MAX_MS            = 120 / 3.6    # 120 km/h → 33.33 m/s (South African N-road limit)
V_CRUISE_MS         = 100 / 3.6    # practical cruise target

# Acceleration limits  (derived from motor power / comfort)
A_MAX_MS2           =  1.5         # m/s²
A_MIN_MS2           = -2.5         # m/s² (braking — not regen-limited)

# Air density correction for altitude (~1 200 m average on route)
ALTITUDE_M          = 1_200.0
AIR_DENSITY_CORRECTED = AIR_DENSITY * np.exp(-0.0001184 * ALTITUDE_M)


# ─────────────────────────────────────────────────────────────────────────────
# Core Physics Functions
# ─────────────────────────────────────────────────────────────────────────────

def aero_drag_force_N(v_ms: float) -> float:
    """Aerodynamic drag force [N] at velocity v [m/s]."""
    return 0.5 * AIR_DENSITY_CORRECTED * DRAG_COEFFICIENT * FRONTAL_AREA_M2 * v_ms**2


def rolling_resistance_N(slope_pct: float = 0.0) -> float:
    """
    Rolling resistance force [N].
    Includes slight increase on slopes via cos(θ) correction.
    For small angles (< 10 %), cos ≈ 1.
    """
    theta = np.arctan(slope_pct / 100.0)
    return VEHICLE_MASS_KG * G_ACC * ROLLING_COEFF * np.cos(theta)


def gravity_force_N(slope_pct: float) -> float:
    """
    Grade-resistance force [N].
    Positive on uphill (adds to motor load), negative on downhill (assists).
    """
    theta = np.arctan(slope_pct / 100.0)
    return VEHICLE_MASS_KG * G_ACC * np.sin(theta)


def total_road_load_N(v_ms: float, slope_pct: float) -> float:
    """Sum of all road forces [N] the motor must overcome."""
    return (aero_drag_force_N(v_ms)
            + rolling_resistance_N(slope_pct)
            + gravity_force_N(slope_pct))


def power_demand_W(v_ms: float, slope_pct: float,
                   accel_ms2: float = 0.0) -> float:
    """
    Net mechanical power demand [W] from the battery.

    Parameters
    ----------
    v_ms       : vehicle speed (m/s)
    slope_pct  : road grade (%)  positive = uphill
    accel_ms2  : vehicle acceleration (m/s²)

    Returns
    -------
    float
        Positive  → power drawn from battery
        Negative  → power returned to battery (regenerative braking)
    """
    if v_ms < 1e-6:
        return 0.0

    # Force required for steady-state driving + acceleration
    F_road  = total_road_load_N(v_ms, slope_pct)
    F_accel = VEHICLE_MASS_KG * accel_ms2
    F_total = F_road + F_accel
    P_mech  = F_total * v_ms

    if P_mech >= 0:
        # Motoring — motor draws from battery
        return P_mech / MOTOR_EFFICIENCY
    else:
        # Regen braking
        return P_mech * REGEN_EFFICIENCY


def soc_update(soc: float, P_solar_W: float, P_demand_W: float,
               dt_s: float) -> float:
    """
    Update battery State of Charge.

    Parameters
    ----------
    soc        : current SOC  [0, 1]
    P_solar_W  : solar panel output (W)
    P_demand_W : motor power demand (W, positive = consuming)
    dt_s       : time step (s)

    Returns
    -------
    float : new SOC, clamped to [0, 1]
    """
    net_power_W  = P_solar_W - P_demand_W          # positive → charging
    delta_energy = net_power_W * dt_s              # J
    new_energy   = soc * BATTERY_CAPACITY_J + delta_energy
    new_soc      = new_energy / BATTERY_CAPACITY_J
    return float(np.clip(new_soc, 0.0, 1.0))


def energy_budget_J(v_ms: float, slope_pct: float,
                    distance_m: float) -> float:
    """
    Energy consumed to travel distance_m at constant speed v on slope.
    Useful for quick feasibility checks.
    """
    time_s    = distance_m / max(v_ms, 1e-9)
    P_demand  = power_demand_W(v_ms, slope_pct)
    return P_demand * time_s


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: velocity → km/h and back
# ─────────────────────────────────────────────────────────────────────────────

def ms_to_kmh(v: float) -> float:
    return v * 3.6

def kmh_to_ms(v: float) -> float:
    return v / 3.6


if __name__ == "__main__":
    print("=== Physics Sanity Check ===")
    for v_kmh, slope in [(60, 0), (80, 0), (100, 0), (80, 2), (80, -2)]:
        v = kmh_to_ms(v_kmh)
        P = power_demand_W(v, slope)
        print(f"  v={v_kmh} km/h  slope={slope:+.1f}%  →  P_demand = {P:.0f} W")
    print(f"\nBattery capacity : {BATTERY_CAPACITY_WH:.0f} Wh")
    print(f"Initial SOC      : {INITIAL_SOC*100:.0f} %")
    print(f"Min SOC          : {MIN_SOC*100:.0f} %")
    print(f"Usable energy    : {(INITIAL_SOC - MIN_SOC) * BATTERY_CAPACITY_WH:.0f} Wh")
