"""
optimizer.py
============
Phase 2 – The Strategist

Two-model optimization approach (both using the full master equation):

Model A — Base Route  (Sasolburg → Zeerust)
    Adaptive greedy + L-BFGS-B refinement.
    Minimises arrival time subject to SOC ≥ 20% at every waypoint.

Model B — Loop Optimizer  (35 km flat loops at Zeerust)
    Grid search over loop speed v ∈ [30, 120] km/h.
    Finds max N complete loops before 17:00, with SOC ≥ 20% throughout.

Key difference from v1: every SOC update now calls physics.soc_update()
which uses the full master equation (V·C·SOH denominator + auxiliary load).
"""

import time as _time
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from constants import (
    RACE_START_S, RACE_END_S,
    CONTROL_STOP_S, LOOP_STOP_S, LOOP_DIST_M,
    V_MAX_MS, V_MIN_DRIVE_MS, A_MAX_MS2, A_MIN_MS2,
    INITIAL_SOC, MIN_SOC,
    BATTERY_CAPACITY_WH,
)
from physics import (
    drivetrain_power_W, soc_update, auxiliary_power_W,
    net_power_W, ms_to_kmh, kmh_to_ms,
)
from solar_model import solar_power_W


# ─────────────────────────────────────────────────────────────────────────────
# Model A: Base-Route Optimizer
# ─────────────────────────────────────────────────────────────────────────────

class BaseRouteOptimizer:
    """
    Simulates Sasolburg → Zeerust with adaptive speed control + scipy refinement.

    Strategy
    --------
    1. Warm-start: adaptive controller picks speed at each waypoint using
       time-budget tracking + slope-based and SOC-based trim.
    2. Refinement: L-BFGS-B minimises arrival time with SOC penalties.
    """

    def __init__(self, route_df: pd.DataFrame,
                 t_depart_s: float = RACE_START_S,
                 target_arrival_s: float = None):
        self.df           = route_df.reset_index(drop=True)
        self.t_depart_s   = t_depart_s
        self.total_dist_m = float(route_df["cumulative_distance_m"].iloc[-1])
        self.target_arr_s = target_arrival_s or (RACE_END_S - 3.5 * 3600)

    def _adaptive_speed(self, idx, t_now, soc, t_remaining, dist_remaining):
        slope = float(self.df["slope_pct"].iloc[idx])

        # Time-budget speed
        v = dist_remaining / max(t_remaining, 1.0)
        v = float(np.clip(v, V_MIN_DRIVE_MS, V_MAX_MS))

        # SOC-aware reduction (triggers earlier than v1 due to auxiliary load)
        if soc < MIN_SOC + 0.12:
            v *= 0.80
        elif soc < MIN_SOC + 0.07:
            v *= 0.65

        # Slope trim
        if slope > 5.0:   v = min(v, kmh_to_ms(60))
        elif slope > 3.0: v = min(v, kmh_to_ms(72))
        elif slope < -3.0: v = min(v * 1.08, V_MAX_MS)  # allow regen benefit

        return float(np.clip(v, V_MIN_DRIVE_MS, V_MAX_MS))

    def simulate(self, v_profile_ms=None):
        """
        Forward simulation. If v_profile_ms given, use it; else use adaptive.

        Returns dict with full time-series arrays.
        """
        n           = len(self.df)
        times       = [self.t_depart_s]
        distances   = [0.0]
        velocities  = []
        socs        = [INITIAL_SOC]
        p_drives    = []
        p_solars    = []
        p_auxs      = []
        accels      = []

        t     = self.t_depart_s
        soc   = INITIAL_SOC
        prev_v = kmh_to_ms(85)

        for i in range(n - 1):
            seg_dist = float(
                self.df["cumulative_distance_m"].iloc[i+1]
              - self.df["cumulative_distance_m"].iloc[i])
            slope = float(self.df["slope_pct"].iloc[i])

            dist_rem = self.total_dist_m - float(self.df["cumulative_distance_m"].iloc[i])
            t_rem    = max(self.target_arr_s - t, 1.0)

            if v_profile_ms is not None:
                v = float(np.clip(v_profile_ms[i], V_MIN_DRIVE_MS, V_MAX_MS))
            else:
                v = self._adaptive_speed(i, t, soc, t_rem, dist_rem)

            # Smooth acceleration
            max_dv = A_MAX_MS2 * (seg_dist / max(prev_v, 1.0))
            v = float(np.clip(v,
                              prev_v + A_MIN_MS2 * 2,
                              prev_v + max_dv))
            v = float(np.clip(v, V_MIN_DRIVE_MS, V_MAX_MS))

            dt    = seg_dist / max(v, 1e-6)
            accel = (v - prev_v) / max(dt, 1e-6)

            P_drive = drivetrain_power_W(v, slope, accel)
            P_solar = solar_power_W(t + dt / 2)         # midpoint solar
            P_aux   = auxiliary_power_W()

            soc = soc_update(soc, P_solar, P_drive, dt)
            soc = max(soc, MIN_SOC)

            t += dt
            velocities.append(v)
            times.append(t)
            distances.append(float(self.df["cumulative_distance_m"].iloc[i+1]))
            socs.append(soc)
            p_drives.append(P_drive)
            p_solars.append(P_solar)
            p_auxs.append(P_aux)
            accels.append(accel)
            prev_v = v

        # Pad first element
        def pad(lst): return [lst[0]] + lst if lst else [0.0]
        velocities = pad(velocities)
        p_drives   = pad(p_drives)
        p_solars   = pad(p_solars)
        p_auxs     = pad(p_auxs)
        accels     = pad(accels)

        return {
            "time_s":          np.array(times),
            "distance_m":      np.array(distances),
            "velocity_ms":     np.array(velocities),
            "soc":             np.array(socs),
            "power_drive_W":   np.array(p_drives),
            "power_solar_W":   np.array(p_solars),
            "power_aux_W":     np.array(p_auxs),
            "acceleration_ms2":np.array(accels),
            "arrival_time_s":  t,
            "arrival_soc":     soc,
        }

    def optimize(self):
        n_segs = len(self.df) - 1

        # Warm start
        warm = self.simulate()
        v0   = warm["velocity_ms"][:n_segs].copy()

        print(f"[Optimizer-A] Warm start: arrival {warm['arrival_time_s']/3600:.2f}h  "
              f"SOC {warm['arrival_soc']*100:.1f}%")

        bounds = [(V_MIN_DRIVE_MS, V_MAX_MS)] * n_segs

        def objective(v_arr):
            res = self.simulate(v_arr)
            # Penalise late arrival and SOC violations
            t_pen   = max(0, res["arrival_time_s"] - self.target_arr_s) * 1e3
            soc_pen = max(0, MIN_SOC - res["arrival_soc"]) * 1e6
            soc_viol = float(np.sum(np.maximum(0, MIN_SOC - res["soc"]))) * 1e4
            return res["arrival_time_s"] + t_pen + soc_pen + soc_viol

        print("[Optimizer-A] Running L-BFGS-B …")
        t0     = _time.time()
        result = minimize(
            objective, v0, method="L-BFGS-B", bounds=bounds,
            options={"maxiter": 300, "ftol": 1e-7, "gtol": 1e-6, "disp": False}
        )
        print(f"[Optimizer-A] Done in {_time.time()-t0:.1f}s  "
              f"success={result.success}")

        opt = self.simulate(result.x)
        print(f"[Optimizer-A] Optimised arrival: {opt['arrival_time_s']/3600:.2f}h  "
              f"SOC {opt['arrival_soc']*100:.1f}%")
        return opt


# ─────────────────────────────────────────────────────────────────────────────
# Model B: Loop Optimizer
# ─────────────────────────────────────────────────────────────────────────────

class LoopOptimizer:
    """
    Maximises the number of complete 35 km loops at Zeerust.

    Physics: flat (slope=0), constant speed, full master equation SOC.
    Decision variable: loop speed v [m/s].
    """

    def __init__(self, t_arrival_s: float, soc_arrival: float):
        self.t_arrival  = t_arrival_s
        self.soc_start  = soc_arrival
        self.t_loops_start = t_arrival_s + CONTROL_STOP_S  # after 30-min stop

    def _soc_after_control_stop(self):
        """Battery charges from solar during the 30-min mandatory stop."""
        DT    = 30
        soc   = self.soc_start
        t     = self.t_arrival
        t_end = self.t_loops_start
        while t < t_end:
            dt   = min(DT, t_end - t)
            Ps   = solar_power_W(t + dt/2)
            soc  = soc_update(soc, Ps, 0.0, dt)   # P_drive=0; aux still drawn
            t   += dt
        return soc

    def _simulate_loop(self, v_ms: float, soc_in: float,
                       t_start: float) -> tuple[float, float]:
        """
        Simulate one 35 km loop at constant speed v_ms.

        Returns (soc_out, t_end_of_driving)
        """
        DT           = 60.0       # 60-second integration steps
        dist_done    = 0.0
        soc          = soc_in
        t            = t_start
        P_drive      = drivetrain_power_W(v_ms, 0.0, 0.0)

        while dist_done < LOOP_DIST_M:
            step_dist = min(v_ms * DT, LOOP_DIST_M - dist_done)
            step_t    = step_dist / v_ms
            P_sol     = solar_power_W(t + step_t / 2)
            soc       = soc_update(soc, P_sol, P_drive, step_t)
            t        += step_t
            dist_done += step_dist

        return soc, t   # t is the moment we return to base

    def max_loops(self, v_ms: float):
        """
        Simulate as many loops as possible at speed v_ms.
        Returns (n_loops, soc_at_end, t_at_end, detail_records).
        """
        soc    = self._soc_after_control_stop()
        t      = self.t_loops_start
        n      = 0
        detail = []   # (t_start, t_end, soc_end)

        while True:
            t_drive_end = t + LOOP_DIST_M / v_ms

            # Must finish the loop before 17:00
            if t_drive_end > RACE_END_S:
                break

            soc_after, t_after = self._simulate_loop(v_ms, soc, t)

            # SOC must not go below floor at any point (conservative: check end)
            if soc_after < MIN_SOC:
                break

            detail.append((t, t_after, soc_after))
            n   += 1
            soc  = soc_after
            t    = t_after + LOOP_STOP_S    # mandatory inter-loop stop

            if t >= RACE_END_S:
                break

        return n, soc, t, detail

    def optimize(self) -> dict:
        soc_after_stop = self._soc_after_control_stop()
        print(f"\n[Optimizer-B] SOC after control stop: {soc_after_stop*100:.1f}%")
        print(f"[Optimizer-B] Loop budget: "
              f"{(RACE_END_S - self.t_loops_start)/3600:.2f} h")

        best_n, best_v, best_detail = 0, kmh_to_ms(70), []
        best_soc = soc_after_stop

        for v in np.linspace(V_MIN_DRIVE_MS, V_MAX_MS, 600):
            n, soc_end, t_end, detail = self.max_loops(v)
            if n > best_n or (n == best_n and soc_end > best_soc):
                best_n, best_v, best_detail = n, v, detail
                best_soc = soc_end

        # Build second-by-second timeline for plotting
        timeline = self._build_timeline(best_v, best_detail)

        print(f"[Optimizer-B] Optimal speed: {ms_to_kmh(best_v):.1f} km/h")
        print(f"[Optimizer-B] Loops done   : {best_n}")
        print(f"[Optimizer-B] Final SOC    : {best_soc*100:.1f}%")

        return {
            "v_loop_ms":    best_v,
            "v_loop_kmh":   ms_to_kmh(best_v),
            "n_loops":      best_n,
            "loop_dist_m":  best_n * LOOP_DIST_M,
            "final_soc":    best_soc,
            "soc_after_control_stop": soc_after_stop,
            "detail":       best_detail,
            "timeline":     timeline,
        }

    def _build_timeline(self, v_ms: float, detail: list) -> list:
        """
        Records: (time_s, velocity_ms, soc, cumulative_loop_dist_m)
        at 30-second resolution for every loop in detail.
        """
        if not detail:
            return []

        DT      = 30.0
        records = []
        P_drive = drivetrain_power_W(v_ms, 0.0, 0.0)
        total_d = 0.0

        # SOC at start of loops = after control stop
        soc = self._soc_after_control_stop()

        for loop_idx, (t_start, t_end_drive, _) in enumerate(detail):
            t           = t_start
            dist_in_loop = 0.0

            # Driving phase
            while dist_in_loop < LOOP_DIST_M:
                step_d = min(v_ms * DT, LOOP_DIST_M - dist_in_loop)
                step_t = step_d / v_ms
                P_sol  = solar_power_W(t + step_t / 2)
                soc    = soc_update(soc, P_sol, P_drive, step_t)
                records.append((t, v_ms, soc, total_d + dist_in_loop))
                t           += step_t
                dist_in_loop += step_d

            total_d += LOOP_DIST_M

            # Inter-loop stop (except after last loop)
            if loop_idx < len(detail) - 1:
                t_stop_end = t + LOOP_STOP_S
                records.append((t, 0.0, soc, total_d))
                while t < t_stop_end:
                    dt_s  = min(DT, t_stop_end - t)
                    P_sol = solar_power_W(t + dt_s / 2)
                    soc   = soc_update(soc, P_sol, 0.0, dt_s)
                    t    += dt_s
                records.append((t, 0.0, soc, total_d))

        return records


if __name__ == "__main__":
    # Quick sanity test
    from data_pipeline import make_synthetic_route
    df  = make_synthetic_route(n_pts=80)
    opt = BaseRouteOptimizer(df, target_arrival_s=13*3600)
    sim = opt.optimize()
    lb  = LoopOptimizer(sim["arrival_time_s"], sim["arrival_soc"])
    res = lb.optimize()
    print(f"\nTotal distance: "
          f"{df['cumulative_distance_m'].iloc[-1]/1000:.0f} + "
          f"{res['n_loops']*35:.0f} km loops")
