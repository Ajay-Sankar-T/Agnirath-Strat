
## Project Overview

This repository is a six-part, end-to-end toolkit for understanding, modeling, and controlling a solar-electric race car. It spans from first-principles physics and solar modeling through telemetry analysis, control experiments, high-end visualizations, and final race strategy. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/f4219e90-c3ae-4c68-be67-7d394240510c/visualizer.py)

At the top level you’ll find:

- `Final-Challenge/`
- `Foundation-Visuals/`
- `Staying_in_Control/`
- `Taming_the_Telemetry/`
- `The_Strategist’s_Crucible/`
- Root `README.md` (this file)

Each folder focuses on a specific phase of the problem.

## Folder Map

| Folder                    | Theme                               | Role in the pipeline |
|---------------------------|-------------------------------------|----------------------|
| `Foundation-Visuals`      | Physics & solar foundations         | Build physical intuition and visuals for the master equation and solar model |
| `Taming_the_Telemetry`    | Telemetry cleaning & parameter ID   | Extract real-world \(C_dA\) and \(C_{rr}\) from coasting data |
| `Staying_in_Control`      | PID & control experiments           | Implement reusable PID and test it on vehicle speed and CartPole |
| `The_Strategist’s_Crucible` | Strategy math & loops              | Turn physics + telemetry into loop strategy and race metrics |
| `Final-Challenge`         | Integrated dashboard & analysis     | Full visual narrative of a race day using all inputs |
| Root `README.md`          | Orientation & navigation            | This master guide |

Below, each folder is described in more detail.

## Foundation-Visuals

**Goal:** Establish the physical and solar foundations and build the visual language you use later. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/71d64d8a-8d8f-4f56-ad31-cfc784d60bb4/solar_model.py)

Typical contents:

- Core physics helpers for:
  - Aerodynamic drag \(F_{\text{aero}} \propto v^2\).
  - Rolling resistance \(F_{\text{roll}} \approx C_{rr} m g\).
  - Grade force \(F_{\text{grade}} = m g \sin\theta\). [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/958739dd-dd30-46ad-a66c-ca56144a1c13/route_data.csv)
- `solar_model.py` implementing:
  - Gaussian GHI profile over the race day.
  - Split into DNI and DHI.
  - Approximate incidence angle and panel power:  
    \[
    P_{\text{solar}} = (\text{DNI}\cdot\cos\theta + \text{DHI}) A_{\text{panel}} \eta_{\text{panel}}
    \]  [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/71d64d8a-8d8f-4f56-ad31-cfc784d60bb4/solar_model.py)

Outputs:

- Foundational plots (e.g., solar irradiance vs time, panel power curves) that feed into later dashboards. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/f4219e90-c3ae-4c68-be67-7d394240510c/visualizer.py)

## Taming_the_Telemetry

**Goal:** Clean and “tame” raw telemetry to recover the car’s true drag and rolling resistance from coasting runs. This is where real data calibrates your physics. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/5504f262-3dd6-4353-9ef0-11f66bf1e996/strategy_report.txt)

Key script (example): `telemetry_fit.py`

Highlights:

- Loads `telemetry_A.csv`, parses timestamps, and filters:
  - Non-positive velocities.
  - NaNs.
  - Large gradients \(|\text{Gradient\_deg}| \ge 2\) to approximate flat road.
- Smooths velocity with a rolling window and computes acceleration from finite differences.
- Keeps only deceleration during coasting and removes acceleration outliers.
- Fits the model
  \[
  a = -\left(k_1 v^2 + k_2\right)
  \]
  using least squares, then recovers:
  \[
  C_d A = \frac{2 m k_1}{\rho}, \qquad C_{rr} = \frac{k_2}{g}
  \]
- Produces scatter + line plots comparing measured vs fitted coasting curves. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/958739dd-dd30-46ad-a66c-ca56144a1c13/route_data.csv)

Outputs:

- Numerical \(C_dA\) and \(C_{rr}\) estimates.
- Visual evidence that the fit is physically reasonable.

## Staying_in_Control

**Goal:** Explore feedback control concepts using a reusable PID controller and two very different plants: a simple velocity model and Gymnasium’s CartPole. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/f4219e90-c3ae-4c68-be67-7d394240510c/visualizer.py)

Core pieces:

- `PIDController` class:
  - P, I, D terms with fixed `dt`.
  - Output saturation and simple anti-windup.
- Vehicle velocity demo:
  - Track a target speed with the PID controller.
  - Simple first-order vehicle model in closed loop.
- CartPole experiments:
  - Use Gymnasium `CartPole-v1` (classic-control) as a testbed. [gymnasium.farama](https://gymnasium.farama.org/environments/classic_control/cart_pole/)
  - Map continuous PID-like control on pole angle to discrete left/right actions.
  - Optionally record videos with `RecordVideo` and `render_mode="rgb_array"`. [gymnasium.farama](https://gymnasium.farama.org/v1.1.0/introduction/record_agent/)

Outputs:

- Time traces of controlled variables (speed, CartPole angle).
- An intuition for gain tuning and the limits of naive PID on nonlinear / discrete systems.

## The_Strategist’s_Crucible

**Goal:** Turn the calibrated model and control intuition into race-level strategy: distances, loops, SOC targets, and sanity checks. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/5504f262-3dd6-4353-9ef0-11f66bf1e996/strategy_report.txt)

Core artifact:

- `strategy_report.txt` (or equivalent notebook / script) summarizing:
  - The “master power balance” equation listing:
    - Battery term \(V_{\text{batt}} C_{\text{rated}} \text{SOH} \, d(\text{SOC})/dt\).
    - Solar input \( \text{DNI} \cos\theta + \text{DHI}\).
    - Aero, rolling, and grade forces.
    - Inverter and auxiliary loads. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/5504f262-3dd6-4353-9ef0-11f66bf1e996/strategy_report.txt)
  - Battery specs and usable energy.
  - Auxiliary loads and energy budget.
  - Race-day outcomes:
    - Route base distance and loops (e.g., 285 km base + 10 × 35 km loops).
    - Total distance covered.
    - Typical loop speed.
    - Final SOC and pass/fail check. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/958739dd-dd30-46ad-a66c-ca56144a1c13/route_data.csv)

Outputs:

- Human-readable strategy summary for a given day’s plan.

## Final-Challenge

**Goal:** Bring everything together into a final integrated analysis and visualization of a full race stage. This is where all earlier work “graduates” into a single story. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/71d64d8a-8d8f-4f56-ad31-cfc784d60bb4/solar_model.py)

Core engine:

- `visualizer.py` (or similar) that produces nine high-quality plots: [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/f4219e90-c3ae-4c68-be67-7d394240510c/visualizer.py)
  1. **Velocity profile** over time.
  2. **SOC profile** with SOC floor marked.
  3. **Acceleration profile** with comfort/limit bands.
  4. **Power balance**: solar in vs drivetrain vs auxiliaries.
  5. **Elevation and slope** vs distance using `route_data.csv`. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/958739dd-dd30-46ad-a66c-ca56144a1c13/route_data.csv)
  6. **Solar irradiance and panel output** (GHI, DNI, DHI, \(\cos\theta\), \(P_{\text{panel}}\)). [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/71d64d8a-8d8f-4f56-ad31-cfc784d60bb4/solar_model.py)
  7. **Cumulative energy budget** (solar vs demand).
  8. **Force decomposition** (aero, rolling, grade) along the route.
  9. **Master dashboard** summarizing everything plus headline stats (total distance, loops, final SOC, arrival time). [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/5504f262-3dd6-4353-9ef0-11f66bf1e996/strategy_report.txt)

Outputs:

- Stand-alone figures and a “dashboard” layout suitable for reports, presentations, or race debriefs.

## Root README.md (You Are Here)

This master README is meant to:

- Explain the **big picture** across all six folders.
- Help new contributors navigate directly to the piece they care about:
  - Physics & intuition → `Foundation-Visuals`
  - Data & calibration → `Taming_the_Telemetry`
  - Control & experimentation → `Staying_in_Control`
  - Strategy math → `The_Strategist’s_Crucible`
  - Final integrated story → `Final-Challenge`

## Suggested First Run Order

If you’re seeing this repo for the first time, a good path is:

1. **Foundation**  
   Skim `Foundation-Visuals` for the solar model and basic force definitions. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/71d64d8a-8d8f-4f56-ad31-cfc784d60bb4/solar_model.py)

2. **Telemetry**  
   Run the scripts in `Taming_the_Telemetry` to fit \(C_dA\) and \(C_{rr}\) from your own telemetry. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/f4219e90-c3ae-4c68-be67-7d394240510c/visualizer.py)

3. **Control**  
   Explore `Staying_in_Control` to see how PID behaves on both a simple car model and CartPole. [gymnasium.farama](https://gymnasium.farama.org/environments/classic_control/cart_pole/)

4. **Strategy**  
   Read `The_Strategist’s_Crucible` outputs (`strategy_report.txt`, notebooks) to see how model + data translate into race decisions. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/5504f262-3dd6-4353-9ef0-11f66bf1e996/strategy_report.txt)

5. **Final Challenge**  
   Generate the plots in `Final-Challenge` and compare them with the strategy assumptions; look for mismatches and edge cases. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/128877345/71d64d8a-8d8f-4f56-ad31-cfc784d60bb4/solar_model.py)

***
