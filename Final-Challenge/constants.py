"""
constants.py
============
Single source of truth for every physical parameter in the simulation.
Change values here — nothing else needs editing.
"""

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# RACE SCHEDULE
# ─────────────────────────────────────────────────────────────────────────────
RACE_START_S      = 8  * 3600          # 08:00 in seconds since midnight
RACE_END_S        = 17 * 3600          # 17:00
CONTROL_STOP_S    = 30 * 60            # mandatory 30-min control stop at Zeerust
LOOP_STOP_S       = 5  * 60            # mandatory 5-min inter-loop stop
LOOP_DIST_M       = 35_000             # 35 km loop distance

# ─────────────────────────────────────────────────────────────────────────────
# ROUTE
# ─────────────────────────────────────────────────────────────────────────────
SASOLBURG         = (-26.8178, 27.8322)
ZEERUST           = (-25.5487, 26.0822)
RESOLUTION_M      = 500                # waypoint spacing (metres)

# ─────────────────────────────────────────────────────────────────────────────
# SOLAR PANEL
# ─────────────────────────────────────────────────────────────────────────────
PANEL_AREA_M2     = 4.0                # m²
PANEL_EFF         = 0.224              # 22.4 % mono-crystalline Si

# Gaussian daylight model
PEAK_DNI          = 1073.0             # W/m²  at solar noon
SOLAR_NOON_S      = 12 * 3600          # 43 200 s since midnight
SIGMA_S           = 11_600.0           # std-dev of daylight curve (s)

# Panel tilt / orientation (for cosθ correction)
# The Sasol car roof is approximately horizontal → tilt ≈ 0°
# In South Africa (lat ~26°S) the sun transits slightly north of zenith in Oct,
# so we apply a fixed mean incidence angle of 20° as a conservative estimate.
PANEL_TILT_DEG    = 0.0                # roof tilt from horizontal (°)
MEAN_INCIDENCE_DEG = 20.0             # mean sun-to-panel angle over the day (°)

# Diffuse fraction of total irradiance (typical clear-sky South Africa)
DHI_FRACTION      = 0.12               # DHI ≈ 12 % of GHI

# ─────────────────────────────────────────────────────────────────────────────
# BATTERY PACK  (master equation: V_batt · C_rated · SOH · d(SOC)/dt)
# ─────────────────────────────────────────────────────────────────────────────
V_BATTERY_NOM     = 130.0              # V   nominal pack voltage
C_RATED_AH        = 38.5              # Ah  → 130 V × 38.5 Ah = 5 005 Wh ≈ 5 kWh
SOH               = 0.97              # State of Health (3 % degradation)

# Derived
BATTERY_CAPACITY_WH  = V_BATTERY_NOM * C_RATED_AH * SOH   # usable Wh
BATTERY_CAPACITY_J   = BATTERY_CAPACITY_WH * 3_600         # usable J

INITIAL_SOC       = 0.80              # 80 % at start of Day 2
MIN_SOC           = 0.20              # 20 % hard floor (survival constraint)

# ─────────────────────────────────────────────────────────────────────────────
# VEHICLE DYNAMICS
# ─────────────────────────────────────────────────────────────────────────────
VEHICLE_MASS_KG   = 250.0             # car + driver (kg)
DRAG_COEFF        = 0.13              # Cd
FRONTAL_AREA_M2   = 0.95              # m²
ROLLING_COEFF     = 0.003             # Crr (specialised solar-car tyres)
G_ACC             = 9.81              # m/s²

# Air density — corrected for mean route altitude ~1 200 m (barometric formula)
AIR_DENSITY_SL    = 1.225             # kg/m³ at sea level
ALTITUDE_M        = 1_200.0
AIR_DENSITY       = AIR_DENSITY_SL * np.exp(-0.0001184 * ALTITUDE_M)  # ~1.083

# ─────────────────────────────────────────────────────────────────────────────
# DRIVETRAIN   [1/η_m  −  η_r] bracket from master equation
# ─────────────────────────────────────────────────────────────────────────────
ETA_MOTOR         = 0.92              # motoring efficiency (motor + controller)
ETA_REGEN         = 0.70              # regenerative braking efficiency

# Combined efficiency terms (master equation notation)
INV_ETA_MOTOR     = 1.0 / ETA_MOTOR  # = 1/η_m   (amplifies demand when motoring)
NEG_ETA_REGEN     = ETA_REGEN        # = η_r      (attenuates recovery when braking)

# Motor power cap
MAX_MOTOR_W       = 2_000.0          # W continuous

# ─────────────────────────────────────────────────────────────────────────────
# AUXILIARY / PARASITIC LOADS  (master equation: P_inv + P_heat + P_lights + …)
# ─────────────────────────────────────────────────────────────────────────────
P_INVERTER_W      = 80.0             # inverter switching losses
P_HEAT_W          = 40.0             # motor + electronics heat dissipation
P_LIGHTS_W        = 15.0             # running lights + indicators
P_TELEMETRY_W     = 20.0             # GPS, data logger, radio
P_OTHER_W         = 10.0             # misc. (cooling fan, sensors)

P_AUXILIARY_W     = (P_INVERTER_W + P_HEAT_W
                     + P_LIGHTS_W + P_TELEMETRY_W + P_OTHER_W)  # 165 W total

# ─────────────────────────────────────────────────────────────────────────────
# VELOCITY / ACCELERATION LIMITS
# ─────────────────────────────────────────────────────────────────────────────
V_MAX_MS          = 120 / 3.6        # 120 km/h → 33.33 m/s  (N-road legal limit)
V_MIN_DRIVE_MS    = 30  / 3.6        # 30  km/h → 8.33  m/s  (minimum cruise)
A_MAX_MS2         =  1.5             # m/s²  max acceleration
A_MIN_MS2         = -2.5             # m/s²  max deceleration (braking)


def summary():
    print("=" * 55)
    print("  VEHICLE & RACE CONSTANTS")
    print("=" * 55)
    print(f"  Battery capacity  : {BATTERY_CAPACITY_WH:.0f} Wh  ({V_BATTERY_NOM} V × {C_RATED_AH} Ah × SOH {SOH})")
    print(f"  Usable energy     : {(INITIAL_SOC - MIN_SOC) * BATTERY_CAPACITY_WH:.0f} Wh  ({(INITIAL_SOC-MIN_SOC)*100:.0f}% window)")
    print(f"  Panel output peak : {PEAK_DNI * np.cos(np.radians(MEAN_INCIDENCE_DEG)) * PANEL_AREA_M2 * PANEL_EFF:.0f} W")
    print(f"  Auxiliary loads   : {P_AUXILIARY_W:.0f} W  (always-on)")
    print(f"  Air density       : {AIR_DENSITY:.4f} kg/m³  @ {ALTITUDE_M:.0f} m")
    print(f"  Speed range       : {V_MIN_DRIVE_MS*3.6:.0f} – {V_MAX_MS*3.6:.0f} km/h")
    print("=" * 55)


if __name__ == "__main__":
    summary()
