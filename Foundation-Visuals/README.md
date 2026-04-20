# ⚙️ Foundation Visualisations – Agnirath Strat

Exploratory **physics and energy visualisations** for Agnirath’s solar car. This module is a sandbox to understand how forces, power, solar input, battery degradation, and full power balance behave **before** wiring everything into the full Sasol Solar Challenge strategy engine.  

***

## What this module does

This script collects a set of small, focused experiments:

- Force and power breakdown vs. velocity on an incline (drag, rolling, gravity).  
- Solar panel power under clear vs. cloudy conditions and different tilt angles.  
- Long‑term battery degradation (SOH and usable capacity vs. cycles).  
- Race‑level energy budget (solar in vs. motor out → final SOC).  
- Uphill–downhill cycle efficiency and regen losses.  
- Full master **power balance** including SOC rate, solar, drivetrain, auxiliaries.  
- “Energy positive / neutral / negative” regions vs. velocity for a given solar condition.  

The goal is to give the strategy team and new members **intuition for orders of magnitude** (e.g., “how bad is 90 km/h vs 45 km/h?”, “how much do clouds hurt?”, “what does 0.02% SOH loss per cycle actually mean?”) long before running full route optimisations.  

***

## Contents

All of the following live in one script / notebook inside `Foundation-Visuals`:

### 1. Forces & Power vs Velocity

```python
calculate_forces_and_power(...)
plot_enhanced_graphs(velocities_kmh)
```

- Models a lightweight solar car on a **5° incline** with realistic drag, frontal area, rolling resistance, and air density.  
- Produces a 2×2 figure:  
  - Forces vs velocity (drag, rolling, gravitational).  
  - Power vs velocity (linear scale, with annotations at 45 km/h and 90 km/h).  
  - Power vs velocity (log scale, to highlight drag dominance at high speed).  
  - Power ratio \(P(v) / P(45\ \text{km/h})\) to show how quickly energy demand explodes with speed.  

Use it to justify “don’t cruise at 90 km/h unless you really have to”.

***

### 2. Solar Power Under Clear vs Cloudy Skies

```python
calculate_solar_power(dni, dhi, panel_efficiency, panel_area, sun_angle_deg, panel_tilt_deg=0)
```

- Simple Global Tilted Irradiance (GTI) model using **DNI + DHI** and a flat/tilted panel.  
- Demo compares a “clear” case (`dni=800, dhi=100`) vs a “cloudy” case (`dni=50, dhi=400`) at the same sun angle, showing how clouds shift energy from beam to diffuse.  
- Good for explaining why panel orientation and tracking matter much less under heavy cloud.  

***

### 3. Battery Degradation & SOH

```python
simulate_battery_degradation(...)
plot_degradation(results)
```

- Exponential SOH decay over cycles, with tunable **SOH loss per cycle** and **temperature effect**.  
- Outputs:  
  - SOH vs number of cycles.  
  - Usable capacity (Ah) vs number of cycles.  

Use this to reason about “Day‑2 battery is not Day‑0 battery” and to select realistic SOH for race simulations.

***

### 4. Race‑Level Energy Budget

```python
simulate_race_energy(
    distance_km=1000,
    avg_speed_kmh=60,
    solar_power_w=500,
    motor_power_w=1000,
    initial_capacity_ah=50,
    voltage_v=48,
    soh=0.9,
)
```

- Back‑of‑the‑envelope race model:  
  - Computes race time from distance and average speed.  
  - Integrates **solar power** and **motor power** over that time.  
  - Applies current SOH to get usable battery capacity, then returns **final SOC**.  

Great for sanity‑checking full‑route simulations (“do my detailed numbers roughly match this envelope?”).

***

### 5. Uphill–Downhill Cycle & Regen

```python
simulate_hill_cycle(
    hill_height_m=100,
    car_mass_kg=200,
    motor_efficiency=0.9,
    regen_efficiency=0.7,
)
```

- Treats a hill as pure potential‑energy storage: climb up, regen down.  
- Computes:  
  - Potential energy required to climb.  
  - Energy drawn from the battery uphill (motor efficiency).  
  - Energy recovered downhill (regen efficiency).  
  - Net energy loss and round‑trip efficiency.  

This gives a clean demonstration that **regen helps a lot, but never makes hills free**.

***

### 6. Complete Power Balance (Master Equation)

```python
power_balance_complete(
    soc_rate,
    velocity_kmh,
    acceleration_ms2,
    incline_angle_deg,
    dni,
    dhi,
    panel_area,
    panel_efficiency,
    car_mass_kg,
    drag_coefficient,
    frontal_area_m2,
    rolling_resistance_coeff,
    motor_efficiency,
    regen_efficiency,
    battery_voltage=48,
    rated_capacity_ah=50,
    soh=0.9,
    inverter_losses_w=20,
    heat_losses_w=30,
    auxiliary_power_w=50,
)
```

- Assembles a **full budget** of:  
  - Battery power from SOC rate and usable capacity.  
  - Solar power (DNI, DHI, panel area, efficiency).  
  - Mechanical power from acceleration and total road‑load forces (drag, rolling, grade).  
  - Fixed losses: inverter, heat, auxiliaries.  
- Returns left‑hand vs right‑hand side and labels the state as **Energy Positive / Neutral / Negative**.  

This is a small, isolated version of the master equation used in your Day‑2 dashboard.

***

### 7. Energy States vs Velocity

```python
results = analyze_energy_states(velocities_kmh)
plot_energy_states(results)
```

- Sweeps a range of velocities under fixed irradiance and incline.  
- Treats the battery as passive (focus purely on **solar vs mechanical + losses**).  
- Produces a plot of **power balance vs velocity** with green (energy positive), red (energy negative), and a zero line.  

This gives an immediate “strategy picture”:  
- Below some speed → the sun alone can carry you (battery charges).  
- Near the neutral point → roughly SOC‑flat.  
- Above that speed → you are burning battery faster than the sun can refill it.

***

## How to run

From the `Foundation-Visuals` folder (or from repo root with the module on your path):

```bash
pip install numpy matplotlib
python foundation_visualisations.py   # or run the notebook cell-by-cell
```

- The script is written so that **each section can be run independently**.  
- All visualisations use Matplotlib and will pop up interactive windows when run locally.  

***

## How this fits into Agnirath‑Strat

These foundation visualisations are **not** the optimizer or the final race dashboard. Instead, they act as:

- A **teaching tool** for new team members.  
- A **physics sanity‑check** before plugging values into more complex models.  
- A **playground** for “what‑if” questions (different masses, panel sizes, efficiencies, SOH, etc.).  

Once the team is confident that these toy models behave as expected, the same equations and assumptions are scaled up into the main `Foundation-Visuals/visualizer.py` + route‑based master‑equation plots and the higher‑level strategy modules.
