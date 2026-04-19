"""
optimizer.py
============
Phase 2 – The Strategist

Two-model optimization approach:
  Model A: Base-route optimizer  (Sasolburg → Zeerust)
           Uses real elevation profile; finds optimal speed at each waypoint.
  Model B: Loop optimizer
           Straight-line 35 km loop; finds optimal constant speed and
           number of full loops achievable before 17:00.

Both models share the same physics and solar model.

Algorithm
---------
Model A uses a dynamic-programming / greedy approach over the route CSV:
  At each waypoint we compute the energy-optimal speed given:
    - Remaining time budget
    - Current SOC
    - Slope at this segment
  A scipy minimize call refines the velocity profile so that Zeerust
  arrival is as early as possible while staying within SOC ≥ 20 %.

Model B uses a closed-form analysis:
  For a given loop speed v, the time per loop is:
    t_loop = 35 000 / v  +  5 * 60   (driving + mandatory stop)
  We find the max N s.t.  t_control + N * t_loop ≤ t_remaining_at_arrival
  and SOC after N loops ≥ 20 %.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
import time as _time

from physics import (
    power_demand_W, soc_update, kmh_to_ms, ms_to_kmh,
    BATTERY_CAPACITY_WH,
    INITIAL_SOC, MIN_SOC,
    V_MAX_MS, A_MAX_MS2, A_MIN_MS2, VEHICLE_MASS_KG,
    MOTOR_EFFICIENCY
)
from solar_model import solar_power_W, RACE_START_S, RACE_END_S

# ─────────────────────────────────────────────────────────────────────────────
# Race constants
# ─────────────────────────────────────────────────────────────────────────────
RACE_END_S        = 17 * 3600           # 17:00
CONTROL_STOP_S    = 30 * 60            # 30 minutes mandatory
LOOP_STOP_S       = 5  * 60            # 5  minutes between loops
LOOP_DIST_M       = 35_000             # 35 km loop
V_MIN_DRIVE_MS    = kmh_to_ms(30)      # we never crawl below 30 km/h on loops
MAX_LEGAL_MS      = kmh_to_ms(120)     # 120 km/h speed limit


# ─────────────────────────────────────────────────────────────────────────────
# Model A:  Base-route simulation
# ─────────────────────────────────────────────────────────────────────────────

class BaseRouteOptimizer:
    """
    Simulates the drive from Sasolburg to Zeerust using the route CSV.

    Strategy: segment-by-segment adaptive speed control.
      1. Divide available time by remaining distance → target average speed.
      2. On each segment: clip to [V_min, V_max], apply slope-dependent trim.
      3. Track SOC; reduce speed if SOC approaches floor.
    """

    def __init__(self, route_df: pd.DataFrame,
                 t_depart_s: float = RACE_START_S,
                 target_arrival_s: float = None):
        self.df            = route_df.reset_index(drop=True)
        self.t_depart_s    = t_depart_s
        self.total_dist_m  = route_df["cumulative_distance_m"].iloc[-1]
        # Default: arrive at Zeerust with 3 h margin for loops
        self.target_arr_s  = target_arrival_s or (RACE_END_S - 3 * 3600)

    def _segment_speed(self, idx: int, t_now: float, soc: float,
                       t_remaining: float, dist_remaining: float) -> float:
        """
        Choose speed for segment idx given current state.
        """
        slope = float(self.df["slope_pct"].iloc[idx])

        # Target speed to finish in time
        v_target = dist_remaining / max(t_remaining, 1.0)
        v_target = float(np.clip(v_target, V_MIN_DRIVE_MS, MAX_LEGAL_MS))

        # SOC-aware reduction: slow down if we're draining too fast
        if soc < MIN_SOC + 0.10:          # within 10% of floor → reduce
            v_target *= 0.85
        elif soc < MIN_SOC + 0.05:
            v_target *= 0.70

        # Uphill: reduce speed to save energy
        if slope > 3.0:
            v_target = min(v_target, kmh_to_ms(70))
        elif slope > 6.0:
            v_target = min(v_target, kmh_to_ms(55))

        # Downhill: allow regen harvesting up to legal limit
        if slope < -3.0:
            v_target = min(v_target * 1.1, MAX_LEGAL_MS)

        return float(np.clip(v_target, V_MIN_DRIVE_MS, MAX_LEGAL_MS))

    def simulate(self, v_profile_ms=None):
        """
        Run a forward simulation of the base route.

        Parameters
        ----------
        v_profile_ms : array-like, optional
            Pre-specified speed at each waypoint (for optimized runs).
            If None, uses adaptive strategy.

        Returns
        -------
        dict with keys:
            'time_s'         : array of wall-clock times
            'distance_m'     : array of cumulative distance
            'velocity_ms'    : array of velocities
            'soc'            : array of SOC
            'power_demand_W' : array of motor power
            'solar_W'        : array of solar power
            'arrival_time_s' : when Zeerust is reached
            'arrival_soc'    : SOC on arrival
        """
        n = len(self.df)

        times       = [self.t_depart_s]
        distances   = [0.0]
        velocities  = []
        socs        = [INITIAL_SOC]
        p_demands   = []
        p_solars    = []

        t    = self.t_depart_s
        soc  = INITIAL_SOC
        prev_v = kmh_to_ms(90)  # initial guess speed

        for i in range(n - 1):
            seg_dist = float(self.df["cumulative_distance_m"].iloc[i+1]
                           - self.df["cumulative_distance_m"].iloc[i])
            slope    = float(self.df["slope_pct"].iloc[i])

            dist_remaining = self.total_dist_m - float(
                self.df["cumulative_distance_m"].iloc[i])
            t_remaining    = max(self.target_arr_s - t, 1.0)

            if v_profile_ms is not None:
                v = float(np.clip(v_profile_ms[i], V_MIN_DRIVE_MS, MAX_LEGAL_MS))
            else:
                v = self._segment_speed(i, t, soc, t_remaining, dist_remaining)

            # Smooth acceleration (cap jerk)
            max_dv = A_MAX_MS2 * (seg_dist / max(prev_v, 1.0))
            v      = float(np.clip(v, prev_v - abs(A_MIN_MS2) * 2,
                                      prev_v + max_dv))
            v      = float(np.clip(v, V_MIN_DRIVE_MS, MAX_LEGAL_MS))

            dt   = seg_dist / max(v, 1e-6)
            accel = (v - prev_v) / max(dt, 1e-6)

            P_demand = power_demand_W(v, slope, accel)
            P_solar  = solar_power_W(t + dt / 2)      # mid-segment solar

            soc = soc_update(soc, P_solar, P_demand, dt)
            soc = max(soc, MIN_SOC)                    # hard floor

            t += dt
            velocities.append(v)
            times.append(t)
            distances.append(float(self.df["cumulative_distance_m"].iloc[i+1]))
            socs.append(soc)
            p_demands.append(P_demand)
            p_solars.append(P_solar)

        # Pad first element
        velocities.insert(0, velocities[0] if velocities else kmh_to_ms(90))
        p_demands.insert(0, p_demands[0] if p_demands else 0.0)
        p_solars.insert(0,  p_solars[0]  if p_solars  else 0.0)

        return {
            "time_s":          np.array(times),
            "distance_m":      np.array(distances),
            "velocity_ms":     np.array(velocities),
            "soc":             np.array(socs),
            "power_demand_W":  np.array(p_demands),
            "solar_W":         np.array(p_solars),
            "arrival_time_s":  t,
            "arrival_soc":     soc,
        }

    def optimize(self):
        """
        Scipy-based refinement of the velocity profile.
        Minimizes (arrival_time) subject to SOC ≥ 20% at all points.
        Uses the adaptive simulation as a warm start.

        Returns the optimized simulation dict.
        """
        n_segs = len(self.df) - 1

        # Warm-start with adaptive simulation
        warm    = self.simulate()
        v0      = warm["velocity_ms"][:n_segs].copy()

        print(f"[Optimizer-A] Warm start arrival: "
              f"{warm['arrival_time_s']/3600:.2f} h  |  "
              f"SOC: {warm['arrival_soc']*100:.1f}%")

        # Bounds: each segment speed in [30, 120] km/h
        bounds = [(V_MIN_DRIVE_MS, MAX_LEGAL_MS)] * n_segs

        def objective(v_arr):
            res = self.simulate(v_arr)
            # Primary: minimize arrival time
            # Penalty: SOC violations
            penalty = 1e6 * max(0, MIN_SOC - res["arrival_soc"])
            soc_violations = np.sum(np.maximum(0, MIN_SOC - res["soc"]))
            return res["arrival_time_s"] + penalty + 1e4 * soc_violations

        print("[Optimizer-A] Running scipy minimize (L-BFGS-B) …")
        t0 = _time.time()
        result = minimize(
            objective, v0,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 200, "ftol": 1e-6, "gtol": 1e-5, "disp": False}
        )
        elapsed = _time.time() - t0
        print(f"[Optimizer-A] Done in {elapsed:.1f}s  |  "
              f"fun={result.fun:.2f}  |  success={result.success}")

        opt_sim = self.simulate(result.x)
        print(f"[Optimizer-A] Optimized arrival: "
              f"{opt_sim['arrival_time_s']/3600:.2f} h  |  "
              f"SOC: {opt_sim['arrival_soc']*100:.1f}%")
        return opt_sim


# ─────────────────────────────────────────────────────────────────────────────
# Model B:  Loop optimizer
# ─────────────────────────────────────────────────────────────────────────────

class LoopOptimizer:
    """
    Optimizes the distance-maximisation phase at Zeerust.

    Physics: straight-line 35 km loop (flat, no elevation change).
    Decision variable: loop speed v [m/s].
    Derived: number of complete loops N.

    Time budget per loop:
      t_loop = 35 000 / v  +  5 * 60   (last loop has no trailing stop)

    SOC budget:
      Each loop consumes  ΔE_loop = P_demand(v) * 35000/v  −  E_solar_loop
    """

    def __init__(self, t_arrival_s: float, soc_arrival: float):
        self.t_arrival  = t_arrival_s
        self.soc_start  = soc_arrival
        self.t_control  = t_arrival_s + CONTROL_STOP_S   # after 30 min stop
        self.t_budget   = RACE_END_S - self.t_control     # seconds for loops

    def _loop_time_s(self, v_ms: float) -> float:
        """Total clock time for ONE loop (driving + mandatory stop)."""
        return LOOP_DIST_M / v_ms + LOOP_STOP_S

    def _loop_energy_J(self, v_ms: float, t_start_s: float) -> float:
        """
        Net energy consumed by the battery for one 35 km loop.
        Solar energy is integrated over the driving period.
        """
        drive_time = LOOP_DIST_M / v_ms
        P_demand   = power_demand_W(v_ms, 0.0, 0.0)   # flat loop

        # Integrate solar over the drive (simple midpoint)
        t_mid      = t_start_s + drive_time / 2
        P_solar    = solar_power_W(t_mid)

        net_W      = P_demand - P_solar                # net draw from battery
        return net_W * drive_time                      # J  (positive = consuming)

    def max_loops(self, v_ms: float) -> tuple[int, list]:
        """
        Given loop speed v, return (N_loops, soc_history).
        """
        soc      = self.soc_start
        t        = self.t_control
        n        = 0
        soc_hist = [soc]

        while True:
            t_drive    = LOOP_DIST_M / v_ms
            t_loop_end = t + t_drive              # time when loop returns to base

            # Check time constraint (must finish loop before 17:00)
            if t_loop_end > RACE_END_S:
                break

            # Energy consumed this loop
            dE = self._loop_energy_J(v_ms, t)
            new_soc = soc - dE / (3600 * BATTERY_CAPACITY_WH)

            # Check SOC constraint (must always remain ≥ 20%)
            if new_soc < MIN_SOC:
                break

            # Commit the loop
            soc  = new_soc
            t    = t_loop_end + LOOP_STOP_S       # add mandatory stop
            n   += 1
            soc_hist.append(soc)

            if t >= RACE_END_S:
                break

        return n, soc_hist, t

    def optimize(self) -> dict:
        """
        Find the optimal loop speed v* that maximises N_loops.
        Uses a scalar search over [30, 120] km/h.
        """
        print(f"\n[Optimizer-B] Loop budget: {self.t_budget/3600:.2f} h  |  "
              f"Start SOC: {self.soc_start*100:.1f}%")

        best_n      = 0
        best_v      = kmh_to_ms(80)
        best_detail = None

        v_candidates = np.linspace(V_MIN_DRIVE_MS, MAX_LEGAL_MS, 500)
        for v in v_candidates:
            n, soc_hist, t_end = self.max_loops(v)
            if n > best_n or (n == best_n and best_detail is None):
                best_n      = n
                best_v      = v
                best_detail = (soc_hist, t_end)

        soc_hist, t_end_loops = best_detail if best_detail else ([self.soc_start], self.t_control)

        print(f"[Optimizer-B] Optimal loop speed: {ms_to_kmh(best_v):.1f} km/h")
        print(f"[Optimizer-B] Loops completed   : {best_n}")
        print(f"[Optimizer-B] Final SOC          : {soc_hist[-1]*100:.1f}%")
        print(f"[Optimizer-B] End-of-loops time  : {t_end_loops/3600:.2f} h")

        # Build detailed loop timeline for plotting
        loop_timeline = self._build_loop_timeline(best_v, best_n)

        return {
            "v_loop_ms":    best_v,
            "v_loop_kmh":   ms_to_kmh(best_v),
            "n_loops":      best_n,
            "loop_dist_m":  best_n * LOOP_DIST_M,
            "final_soc":    soc_hist[-1] if soc_hist else self.soc_start,
            "soc_history":  soc_hist,
            "t_end_loops":  t_end_loops,
            "timeline":     loop_timeline,
        }

    def _build_loop_timeline(self, v_ms: float, n_loops: int) -> list:
        """
        Build a second-by-second timeline of loop driving for plotting.
        Returns list of (time_s, velocity_ms, soc, distance_m).
        """
        DT        = 30.0   # 30-second resolution
        records   = []
        soc       = self.soc_start
        t         = self.t_control
        total_d   = 0.0

        for loop_i in range(n_loops):
            t_loop_start = t
            t_drive      = LOOP_DIST_M / v_ms

            # Driving phase
            t_seg = t
            dist_in_loop = 0.0
            while dist_in_loop < LOOP_DIST_M:
                step_d  = min(v_ms * DT, LOOP_DIST_M - dist_in_loop)
                step_t  = step_d / v_ms
                P_d     = power_demand_W(v_ms, 0.0, 0.0)
                P_s     = solar_power_W(t_seg + step_t / 2)
                soc     = soc_update(soc, P_s, P_d, step_t)
                records.append((t_seg, v_ms, soc, total_d + dist_in_loop))
                t_seg       += step_t
                dist_in_loop += step_d

            total_d += LOOP_DIST_M
            t        = t_seg

            # Mandatory stop
            if loop_i < n_loops - 1:
                records.append((t, 0.0, soc, total_d))
                t += LOOP_STOP_S
                records.append((t, 0.0, soc, total_d))

        return records


if __name__ == "__main__":
    # Quick test with a synthetic flat route
    n_pts = 50
    cum_d = np.linspace(0, 285_000, n_pts)
    df_test = pd.DataFrame({
        "cumulative_distance_m": cum_d,
        "slope_pct":             np.zeros(n_pts),
        "latitude":              np.linspace(-26.82, -25.55, n_pts),
        "longitude":             np.linspace(27.83,  26.08,  n_pts),
        "altitude_m":            1200 + np.zeros(n_pts),
        "bearing_deg":           np.zeros(n_pts),
    })
    opt_a = BaseRouteOptimizer(df_test, target_arrival_s=13*3600)
    sim   = opt_a.optimize()
    print(f"\nArrival: {sim['arrival_time_s']/3600:.2f} h  "
          f"SOC: {sim['arrival_soc']*100:.1f}%")

    opt_b = LoopOptimizer(sim["arrival_time_s"], sim["arrival_soc"])
    res_b = opt_b.optimize()
    print(f"Loops: {res_b['n_loops']}  |  "
          f"Extra dist: {res_b['loop_dist_m']/1000:.0f} km")
