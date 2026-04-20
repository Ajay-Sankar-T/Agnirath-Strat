# 🧮 Loop Strategy Math Lab – Agnirath Strat

This module is a self‑contained **analytical playground** for Agnirath’s loop strategy. It combines symbolic proofs, simple power models, and visualisations to answer two key questions:

1. *Is it better to go faster downhill and slower uphill on a symmetric hill?*  
2. *Given time and battery constraints, what constant loop speed maximises the number of 30 km loops we can run?*  

***

## 1. Sympy proof – “fast‑down, slow‑up” is better

The first part uses **Sympy** to compare two strategies on a symmetric hill:  

- Total length: 5 km downhill + 5 km uphill.  
- Mechanical power model:  

\[
P_{\text{mech}}(v,\theta) = k v^3 + P_{\text{base}} + m g v \sin\theta
\]

- Battery power:
  - Motoring (uphill): \(P_{\text{batt}} = P_{\text{mech}}/\eta_m\)  
  - Regen (downhill): \(P_{\text{batt}} = \eta_r P_{\text{mech}}\)

Two strategies:

- **Strategy A (constant speed)**  
  - Downhill: \(v_1 = v_0\) on \(-\alpha\)  
  - Uphill:   \(v_2 = v_0\) on \(+\beta\)

- **Strategy B (redistribute speed)**  
  - Downhill faster: \(v_1 = v_0 + \Delta v\)  
  - Uphill slower:  \(v_2 = v_0 - \Delta v\)  

The code:

- Forms closed‑form expressions for total battery energy \(E_A\) and \(E_B\) across both segments.  
- Computes the difference \(E_B - E_A\).  
- Performs a **series expansion in \(\Delta v\)** around 0 and extracts the linear and quadratic coefficients.  

The outcome (from `E_diff_series`) shows that, under the assumptions that:

- Downhill is firmly in regen (negative mechanical power),  
- Uphill is firmly motoring (positive mechanical power),  

the **linear term vanishes** and the **quadratic term** is negative for physically realistic parameters. That proves, to second order, that **pushing a bit faster downhill and slower uphill always reduces net battery energy** for the same reference speed \(v_0\).  

This is the analytical justification for “use gravity where it’s free, nurse the battery on the climb”.

***

## 2. Constant‑speed loop optimiser

The second block implements a very compact optimisation for loops:

- Remaining race time: `T_h = 1.5` h  
- Loop length: `L_km = 30` km  
- Current battery energy: `E_current_kWh = 1.5`  
- Minimum allowed energy at end: `E_min_kWh = 0.2`  
- Average solar power: `P_solar_kW = 0.25`  

### Power and energy model

Mechanical power (kW):

\[
P_{\text{mech}}(v) = k v^3 + P_{\text{losses}}
\]

Electrical battery power (kW):

\[
P_{\text{batt}}(v) = \frac{P_{\text{mech}}(v)}{\eta} - P_{\text{solar}}
\]

Loop time and energy:

\[
t_{\text{lap}}(v) = \frac{L}{v}, \quad
E_{\text{loop}}(v) = P_{\text{batt}}(v)\, t_{\text{lap}}(v)
\]

With:

- `k = 3e-6` (tunes aero scaling),  
- `P_losses_kW = 0.05`, `eta = 0.95`.  

### Search strategy

For each integer number of loops \(N\):

1. **Time constraint**

\[
N \cdot t_{\text{lap}}(v) \le T_h \quad \Rightarrow \quad
v \ge v_{\min,\text{time}} = \frac{N L}{T_h}
\]

2. **Regulation constraint**: `v >= v_reg_min_kmh = 60`.  

3. On a fine speed grid `[60, 120]` km/h:
   - restrict to speeds ≥ `max(v_min_time, 60)`,  
   - compute `E_loop(v)` and `total_E = N * E_loop(v)`, `total_time = N * t_lap(v)`,  
   - keep speeds where both time and energy budgets are satisfied.  

4. For that \(N\), choose the feasible speed with the **minimum total energy**.  
5. Over all \(N\), pick the triple \((N^*, v^*, E^*)\) with:
   - primary objective: **maximise N**,  
   - tie‑breaker: **minimise total energy**.  

The code prints:

- Maximum feasible loops `best_N`.  
- Recommended constant speed `best_v`.  
- Total time used vs 1.5 h limit.  
- Total battery energy drawn vs usable budget.  
- Diagnostic table for sample speeds (60–120 km/h) showing \(P_{\text{mech}}, P_{\text{batt}}, E_{\text{loop}}\) and separate time‑limited and energy‑limited loop counts.  

This is a tiny, easily explainable version of your full loop‑segment optimiser.

***

## 3. Visualisations – power and loops vs speed

The final block builds smooth trends over speed (60–120 km/h):

- `mech_power_kW(v)` – mechanical power.  
- `net_batt_power_kW(v)` – battery power after solar.  
- `energy_per_loop_kWh(v)` – energy required per 30 km loop.  
- `N_time(v)` – loops limited only by time.  
- `N_energy(v)` – loops limited only by energy.  
- `N_max(v) = floor(min(N_time, N_energy))` – max integer loops possible at that constant speed.  

It outputs three PNGs:

1. **`power_vs_speed.png`**  
   - Plots mechanical and battery power vs speed.  
   - Shows how quickly demand rises with speed and where solar significantly offsets the battery draw.  

2. **`loop_energy_vs_speed.png`**  
   - Battery energy per loop vs speed.  
   - Used to argue for “sweet‑spot” cruise speed where loops are least expensive in kWh.  

3. **`max_loops_vs_speed.png`**  
   - Step plot of maximum integer loops achievable vs constant speed.  
   - Visualises the tension between finishing more loops (time‑limited) and not killing the battery (energy‑limited).  

These figures are perfect for presentations: one slide for the math intuition, one for the optimiser result, one for the “number of loops vs speed” curve.

***

## How to use this module

From your project environment:

```bash
pip install sympy numpy matplotlib
python loop_math_lab.py  # or run the notebook cell-by-cell
```

- The Sympy section runs first and prints the series expansion and coefficients, showing the sign of the quadratic term.  
- The loop optimiser then prints the recommended `N` and `v*` plus diagnostic table.  
- The plotting section saves the trend figures to PNG in the working directory.  
