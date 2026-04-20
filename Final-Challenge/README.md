🌞 Sasol Solar Challenge – Day 2 Master Equation Dashboard
A modular analysis and visualization toolkit for the Sasol Solar Challenge Day 2 stage. This project couples a physics‑based master power‑balance equation with high‑resolution route data and a Gaussian solar model to produce a publication‑ready dashboard of velocity, SOC, power, forces, and energy over the Sasolburg → Zeerust route plus loops.

System Architecture
bash
sasol_solar_day2/
├── solar_model.py      # Solar irradiance + panel power (Gaussian model)
├── physics.py          # Vehicle forces: aero, rolling, grade  (imported)
├── constants.py        # All fixed parameters and race timing  (imported)
├── visualizer.py       # Phase 3: all plots + 6‑panel dashboard
├── data/
│   └── route_data.csv  # Route with GPS, distance, altitude, slope
├── plots/              # Generated PNG plots (created on demand)
├── outputs/
│   └── strategy_report.txt  # Example master‑equation summary
└── 09_dashboard.jpg    # Sample dashboard output
Data & Model Flow
text
route_data.csv ─────► route_df (distance, altitude, slope)
                          │
                          ▼
                    physics.py + constants.py
                          │
solar_model.py ───► P_solar(t), GHI/DNI/DHI, cos(θ)
                          │
                          ▼
   times, v(t), SOC(t), P_drive(t), P_aux(t)
                          │
                          ▼
                   visualizer.generate_all_plots()
                          │
                          ▼
      9 PNG plots + Day‑2 master dashboard (dark theme)
Installation
bash
pip install numpy pandas matplotlib
The code assumes local physics.py and constants.py modules are on the Python path, providing vehicle parameters, race start/end times, and battery/limit settings.

Usage
1. Prepare inputs
You need time‑series data for:

times – seconds since midnight SAST

velocity_ms – vehicle speed (m/s)

soc – battery SOC as fraction (0–1)

solar_W, drive_W, aux_W – solar array output, drivetrain demand, and auxiliary load (W)

route_df – pandas.DataFrame from data/route_data.csv with cumulativedistancem, altitudem, slopepct columns

events – list of control‑stop / loop‑segment dicts

result_summary – dict with total_dist_km, n_loops, final_soc, arrival_time_s (for the footer line)

You can generate consistent solar input using solar_model.solar_profile(...).

2. Generate all figures
python
import pandas as pd
from visualizer import generate_all_plots
from solar_model import solar_profile
from constants import RACESTARTS, RACEENDS  # race window (s)

# Route
route_df = pd.read_csv("data/route_data.csv")

# Solar profile over the race window
t, GHI, DNI, DHI, cos_theta, P_solar = solar_profile(
    tstarts=RACESTARTS,
    tends=RACEENDS,
    dts=60.0,
)

# Your simulation here: v(t), SOC(t), P_drive(t), P_aux(t)
times = t
velocity_ms = ...
soc = ...
drive_W = ...
aux_W = ...

events = [...]          # control stop + loop segments
result_summary = {...}  # total distance, loops, final SOC, arrival time

paths = generate_all_plots(
    times,
    velocity_ms,
    soc,
    P_solar,
    drive_W,
    aux_W,
    route_df,
    events,
    result_summary,
)

print("Saved plots:", paths)
All PNGs are written into plots/ (created automatically if it does not exist).

Phase 1: Solar & Route Models
Gaussian Solar Irradiance
solar_model.py implements a smooth diurnal curve for Global Horizontal Irradiance 
G
(
t
)
G(t), then splits it into DNI and DHI, and projects onto the array using an approximate incidence model for a horizontal car roof in South Africa in October.

Core pieces:

ghi_Wm2(t) – Gaussian GHI vs time (clamped at zero outside daylight).

dni_dhi_Wm2(t) – Partition of GHI into direct and diffuse components via a constant diffuse fraction.

cos_incidence(t) – Sinusoidal variation of incidence angle between sunrise and sunset (06:00–18:00), centred on solar noon.

solar_power_W(t) – Net electrical panel power using area and efficiency from constants.py.

Route & Elevation
route_data.csv contains the fixed Sasolburg → Zeerust route and loop section sampled at fine spatial resolution.

Columns include:

latitude, longitude – GPS coordinates

cumulativedistancem – distance from start (m)

altitudem – elevation (m)

bearingdeg – track heading

slopepct – grade between samples (%)

The visualizer uses this for elevation plots and for decomposing road‑load into aero, rolling, and grade components along the distance axis.

Phase 2: Master Power Balance
The dashboard is built around the full master power‑balance equation:

Battery term: 
V
batt
×
C
rated
×
SOH
×
d
SOC
/
d
t
V 
batt
​
 ×C 
rated
​
 ×SOH×dSOC/dt.

Solar term: 
P
solar
(
t
)
=
(
DNI
⋅
cos
⁡
θ
+
DHI
)
A
panel
η
solar
P 
solar
​
 (t)=(DNI⋅cosθ+DHI)A 
panel
​
 η 
solar
​
 .

Drivetrain term: power from aero drag, rolling resistance, and grade forces times speed.

Auxiliary term: constant loads (lights, telemetry, etc.) via PAUXILIARY_W.

visualizer.py does not solve the ODEs itself; instead, it expects time‑aligned arrays for all terms and uses them to compute derived quantities like cumulative energy and road‑load decomposition.

Phase 3: Plots & Dashboard
visualizer.py configures a dark GitHub‑style theme and provides both individual plots and a 6‑panel dashboard, all saved as PNG.

Plots Generated
File	Description
01_velocity_profile.png	Velocity vs time, with 120 km/h limit and control‑stop markers
02_soc_profile.png	SOC (%) vs time, with MINSOC floor and violation shading
03_acceleration_profile.png	Longitudinal acceleration vs time, with ±acceleration bounds
04_power_balance.png	Solar vs drivetrain vs auxiliary power, net charge/discharge shading
05_elevation_slope.png	Elevation vs distance + slope bar chart (uphill vs downhill)
06_solar_irradiance.png| GHI/DNI/DHI + incidence cosine and panel power	
07_energy_budget.png	Cumulative solar, drivetrain, auxiliary, and net energy (kWh)
08_force_decomposition.png	Aero, rolling, and grade forces stacked vs distance
09_dashboard.png	2×3 master dashboard with headline and footer summary

Each figure uses shared styling: dark background, colored panels, subtle grid, monospace font, and consistent color mapping (blue = velocity/drive, green = SOC/net positive, red = limits/deficit, yellow = solar, orange = grade/uphill, teal = downhill).

Repository Structure
bash
├── solar_model.py          # Gaussian solar + panel model
├── visualizer.py           # All plots, dark theme, dashboard
├── physics.py              # Forces & unit helpers (imported)
├── constants.py            # Battery, solar, and race constants
├── data/
│   └── route_data.csv      # Route & elevation data
├── plots/                  # Output figures (auto-created)
├── outputs/
│   └── strategy_report.txt # Example SOC + distance results
├── 09_dashboard.jpg        # Example dashboard export
└── README.md
Built for Sasol Solar Challenge analysis and strategy visualization — plug in your own solver, and this repo turns it into a story your race engineers and drivers can read at a glance.
