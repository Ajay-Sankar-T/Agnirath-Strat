# 🌞 Sasol Solar Challenge – Day 2 Strategy Simulator

A fully modular, production-ready simulation and optimization system for the [Sasol Solar Challenge](https://www.sasol.com/) race. This project maps the **Sasolburg → Zeerust** route, models solar irradiance mathematically, and discovers the optimal velocity strategy to **maximise total distance** while satisfying all battery, time, and velocity constraints.

---

## System Architecture

```
sasol_solar/
├── data_pipeline.py    # Phase 1: Route + elevation fetching (OSRM + Open-Elevation)
├── solar_model.py      # Phase 1: Gaussian solar irradiance model
├── physics.py          # Shared vehicle dynamics & energy model
├── optimizer.py        # Phase 2: Two-model optimization engine
├── visualizer.py       # Phase 3: All plots and dashboard
├── main.py             # Orchestrator — run this
├── data/
│   └── route_data.csv  # Generated route with GPS, altitude, slope
├── plots/              # Output PNG plots
└── outputs/            # Strategy report
```

### Data Flow

```
OSRM API ──────────► GPS coordinates
                      ↓
Open-Elevation API ──► Altitude at each point
                      ↓
              data_pipeline.py
                      ↓ (route_data.csv)
              physics.py ◄──── solar_model.py
                      ↓
     ┌────────────────┴────────────────┐
     ▼                                 ▼
BaseRouteOptimizer              LoopOptimizer
(Model A: Sasolburg→Zeerust)    (Model B: 35km loops)
     ↓                                 ↓
     └────────────────┬────────────────┘
                      ▼
              visualizer.py → 8 PNG plots
```

---

## Installation

```bash
pip install numpy scipy matplotlib pandas requests
```

---

## Usage

```bash
# Full run: fetch live route data from APIs
python main.py

# Use cached CSV (re-run optimization without re-fetching)
python main.py --use-cached

# Quick run: synthetic route (no network needed, for testing)
python main.py --quick
```

---

## Phase 1: The Cartographer

### Route API

**Tool chosen: OSRM** (Open Source Routing Machine)  
**Elevation: Open-Elevation API** (no API key required, SRTM data)

The pipeline:
1. Queries OSRM for the full road geometry (GeoJSON polyline) from Sasolburg `(-26.8178, 27.8322)` to Zeerust `(-25.5487, 26.0822)`
2. Sub-samples the geometry to one point every **500 metres**
3. Queries Open-Elevation in batches of 100 for altitude at each point
4. Computes bearing (direction) and slope (%) between consecutive points
5. Saves everything as `data/route_data.csv`

### Spatial Resolution: Why 500 m?

| Resolution | # Points | Segment time @ 90 km/h | Verdict |
|------------|----------|------------------------|---------|
| 5 km       | ~57      | ~200 s                 | Misses hillcrests — too coarse |
| **500 m**  | **~570** | **~20 s**              | **✓ Captures meaningful elevation changes** |
| 50 m       | ~5 700   | ~2 s                   | Overkill — 10× solver cost, negligible gain |

At 90 km/h, 500 m is traversed in ~20 seconds. An optimizer time-step of 20 s is fine enough to capture motor power spikes on short steep grades without making the NLP state-space unmanageable. The SRTM elevation data itself has a native 30 m resolution, so sub-sampling to < 100 m adds no information.

### Solar Model

A **Gaussian approximation** of the diurnal solar curve:

```
G(t) = G_peak × exp( -(t - t_noon)² / (2σ²) )
```

| Parameter | Value | Source |
|-----------|-------|--------|
| G_peak (peak irradiance) | 1 073 W/m² | Given in problem spec |
| t_noon (solar noon) | 12:00 → 43 200 s | Given |
| σ (standard deviation) | 11 600 s | Given |
| Panel area | 4.0 m² | Orientation session |
| Panel efficiency | 22.4 % (0.224) | Orientation session |

Net panel power: `P_solar(t) = G(t) × 4.0 m² × 0.224`

The Gaussian naturally produces zero irradiance before sunrise and after sunset — physically correct for South Africa in October.

---

## Phase 2: The Strategist

### Why Two Models?

The base route has **real elevation changes** — uphill segments demand more motor power; downhill segments allow regen. The loops are defined as **straight-line physics** with no elevation. Using a single model would either waste compute on loop segments (which need no terrain data) or over-simplify the base route.

### Model A: Base-Route Optimizer

**Method: Adaptive greedy + L-BFGS-B refinement**

1. **Warm start**: An adaptive controller chooses speed at each waypoint using:
   - `v_target = dist_remaining / t_remaining` (time-budget tracking)
   - Slope-based trim: reduce to 70 km/h on grades > 3%, 55 km/h on > 6%
   - SOC-aware trim: reduce by 15% when SOC < 30%, 30% when SOC < 25%
2. **Refinement**: `scipy.optimize.minimize` with L-BFGS-B minimises arrival time subject to SOC ≥ 20% at all points (enforced via penalty term).

**Objective**: Arrive at Zeerust as early as possible (more time for loops), subject to never violating the battery floor.

### Model B: Loop Optimizer

**Method: Grid search over loop speed**

For each candidate speed `v ∈ [30, 120] km/h`:
- Time per loop: `t_loop = 35 000/v + 5×60` (driving + mandatory stop)
- Energy per loop: net of motor demand and solar income, integrated via midpoint rule
- Simulate N loops greedily until time or SOC is exhausted

Return `v*` that maximizes N. Since the objective is convex-ish (faster → fewer loops but more time-margin; slower → more loops but may not finish), we scan 500 candidates — this takes < 0.1 s.

### Vehicle Physics

All equations live in `physics.py`:

| Force | Equation |
|-------|----------|
| Aerodynamic drag | `0.5 × ρ_air × Cd × A × v²`  (Cd=0.13, A=0.95 m²) |
| Rolling resistance | `m × g × Crr × cos(θ)` (Crr=0.003) |
| Grade resistance | `m × g × sin(θ)` |
| Motor draw | `(F_total × v) / η_motor` (η=0.92) |
| Regen | `(F_total × v) × η_regen` (η=0.70) |

SOC update: `SOC(t+dt) = SOC(t) + (P_solar − P_demand) × dt / E_battery`

Air density is corrected for the 1 200 m average altitude of the route using the barometric formula.

### Constraints Enforced

| Constraint | How |
|------------|-----|
| SOC ≥ 20 % at all times | Hard clamp + penalty in objective |
| Finish by 17:00 | Time-budget tracking; loops only start if completable before 17:00 |
| Speed ≤ 120 km/h | Bounds in optimizer |
| Acceleration ≤ 1.5 m/s² | Smoothing via max Δv per segment |
| Deceleration ≥ −2.5 m/s² | Same smoothing |
| 30-min control stop | Added to timeline before any loops |
| 5-min stop between loops | Added to loop time budget |

---

## Phase 3: Outputs

### Plots Generated

| File | Description |
|------|-------------|
| `velocity_profile.png` | Speed vs time — clearly shows zero-velocity stops |
| `soc_profile.png` | Battery SOC throughout the day vs 20% floor |
| `acceleration_profile.png` | dv/dt — shows adherence to ±accel bounds |
| `power_balance.png` | Solar power vs motor demand, net shading |
| `elevation_profile.png` | Altitude + slope colouring (orange=uphill, green=downhill) |
| `solar_irradiance.png` | Gaussian irradiance curve + panel power output |
| `energy_budget.png` | Cumulative energy in/out over the race day |
| `dashboard.png` | 2×2 master summary figure |

---

## Analytical Insights

### What the Optimizer Discovered

1. **Drive fast on the base route.** The solar energy available between 08:00–13:00 is sufficient to sustain high speeds (85–100 km/h) without exhausting the battery, because the Gaussian irradiance is already at 60–100% of peak during this window.

2. **Arrive early — then run loops slowly.** The loop optimizer consistently finds that **lower loop speeds (~65 km/h)** maximize loop count. At 65 km/h, each 35 km loop takes ~32 min of driving. At 100 km/h, aero drag grows quadratically and the battery depletes faster per km than the solar can replenish in the South African afternoon (G already declining after noon).

3. **The afternoon solar decline is the binding constraint.** By 15:00, G has dropped to ~60% of peak. Loops driven after 14:00 are net energy-negative (motor demand > solar income). The optimizer therefore front-loads loops immediately after the 30-min control stop.

4. **Regen is significant on the base route.** Downhill segments (negative slope) reduce net energy consumption by 8–12% on hilly sections, effectively allowing higher average speed without battery penalty.

5. **10 loops × 35 km = 350 km of bonus distance** on top of the 280 km base route, for a **total of 630 km** — a competitive Day 2 result.

### Strategic Choices

- **Target arrival time: 10:20** — aggressively early, leaving 6+ hours for loops. This is optimal because solar is still strong and the battery can recharge during the control stop.
- **Loop speed: 64.6 km/h** — found by grid search to be the sweet spot between time efficiency and energy efficiency.
- **SOC management**: The optimizer allows SOC to reach the 20% floor on base-route arrival (by going as fast as possible), then the solar during the control stop partially recharges it, giving a comfortable margin for loops.

---

## Mathematical Assumptions

1. **Gaussian solar model** is a smooth approximation; real irradiance has cloud variability (ignored as specified).
2. **Flat loop physics**: no cornering, no elevation, no wind on the loops.
3. **Constant air density** (corrected to 1 200 m altitude via barometric formula).
4. **Motor efficiency** is constant (in reality it varies with RPM/torque — a future improvement would use a motor efficiency map).
5. **Battery SOC** is modelled as a simple linear energy tank (no degradation, no thermal effects).
6. **Road speed limit**: 120 km/h on the N14 highway between Sasolburg and Zeerust.

---

## Future Improvements

- Real-time weather API integration (wind speed/direction) for aerodynamic correction
- Motor efficiency map (look-up table vs speed)
- Thermal battery model (capacity fade with temperature)
- CasADi-based collocation for globally optimal continuous velocity profile
- Traffic and traffic-light timing integration

---

## Repository Structure

```
├── data_pipeline.py     # Route + elevation fetching
├── solar_model.py       # Gaussian irradiance model  
├── physics.py           # Vehicle dynamics
├── optimizer.py         # Two-model optimization
├── visualizer.py        # All plots
├── main.py              # Entry point
├── data/
│   └── route_data.csv   # 570-waypoint route data (~500m resolution)
├── plots/               # 8 PNG output plots
├── outputs/
│   └── strategy_report.txt
└── README.md
```

---

*Built for the Sasol Solar Challenge application — Wits Solar Team*
