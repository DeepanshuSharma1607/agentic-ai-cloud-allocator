"""
run_experiment.py - compare scaling policies on the SAME spike, with REAL replicas. The output is what the paper needs.

    python run_live.py --no-agent --no-frontend            # terminal 1: system without the agent (for the baselines)
    python -m infra.experiments.run_experiment --policy static --static-n 3 --reps 3
    python -m infra.experiments.run_experiment --policy reactive --reps 3
    python -m infra.experiments.run_experiment --policy hpa --reps 3
    # terminal 1: Ctrl+C, then  python run_live.py --no-frontend   (WITH the agent = the AegisCloud policy)
    python -m infra.experiments.run_experiment --policy aegis --reps 3
    python -m infra.experiments.plot                       # figures + table in data/experiments/

Scenario (one repetition): quiet traffic -> a sudden spike -> quiet again. The quiet level and the spike level default to a share of
the machine's real capacity (so the spike is meaningful on any device) and can be set with --base / --spike (requests per tick).

Policies
  static    a fixed number of replicas (--static-n)
  reactive  looks only at the traffic that just arrived: replicas = ceil(traffic x (1+margin) / capacity), scale down after 10 calm ticks
  hpa       the Kubernetes HorizontalPodAutoscaler rule, run by this script: desired = ceil(ready x CPU% / target%), checked every
            15 real seconds, scale-down stabilised for 300 real seconds (the K8s defaults); it needs real CPU numbers
  aegis     your LSTM + LangGraph agent, which must be running (this script only sends traffic and measures)

Measured for each run (from data/infra/cluster_ticks.csv, i.e. real requests on real replicas):
  slo_miss_ticks      ticks with p95 above the goal or more than 1% failed requests
  failed_requests     total failed (503 / timeout / no ready replica)
  replica_seconds     the cost: sum of ready replicas x seconds
  mean_startup_s      real seconds from "start replica" to Ready
  overload_ticks      ticks where traffic exceeded ready replicas x calibrated capacity
"""
from __future__ import annotations

import argparse
import math
import time

import pandas as pd
import requests

import settings as S
from infra import config as C
from infra import device as DV
from infra import runtime as R

EXP_DIR = S.DATA_DIR / "experiments"


# ------------------------------------------------------------------ policies: f(history rows, state) -> desired replicas or None (= keep)
class Static:
    def __init__(self, n):
        self.n = n

    def decide(self, rows, state, ctx):
        return self.n


class Reactive:
    def __init__(self, margin=0.10, down_wait=10):
        self.margin, self.down_wait, self.calm = margin, down_wait, 0

    def decide(self, rows, state, ctx):
        if rows.empty:
            return None
        need = math.ceil(float(rows["requests"].iloc[-1]) * (1 + self.margin) / ctx["capacity"])
        cur = state["desired"]
        if need > cur:
            self.calm = 0
            return need
        self.calm = self.calm + 1 if need < cur else 0
        return need if self.calm >= self.down_wait else None


class Hpa:
    def __init__(self, target=0.6, period=15.0, down_window=300.0, tolerance=0.1):
        self.target, self.period, self.down_window, self.tol = target, period, down_window, tolerance
        self.last_check, self.history = 0.0, []

    def decide(self, rows, state, ctx):
        now = time.time()
        if now - self.last_check < self.period:
            return None
        self.last_check = now
        used = [p for p in state["pods"] if p["state"] == "ready" and p.get("cpu_pct") is not None]
        if not used:
            return None
        limit = ctx["cpu_limit"] * 100
        util = sum(p["cpu_pct"] for p in used) / len(used) / limit
        ratio = util / self.target
        cur = max(state["ready"], 1)
        want = cur if abs(ratio - 1) <= self.tol else math.ceil(cur * ratio)
        want = min(want, max(cur * 2, cur + 4))
        self.history.append((now, want))
        self.history = [(t, w) for t, w in self.history if now - t <= self.down_window]
        return max(w for _, w in self.history) if want < state["desired"] else want       # scale down only to the max of the last window


class Aegis:
    """The agent runs by itself; nothing to decide here."""

    def decide(self, rows, state, ctx):
        return None


def make_policy(name, args):
    return {"static": lambda: Static(args.static_n), "reactive": Reactive, "hpa": Hpa, "aegis": Aegis}[name]()


# ------------------------------------------------------------------ helpers
def api(method, url, **kw):
    r = requests.request(method, url, timeout=kw.pop("timeout", 10), **kw)
    r.raise_for_status()
    return r.json()


def state():
    return api("GET", f"{C.URL_GATEWAY}/infra/state")


def set_traffic(n):
    api("POST", f"{S.URL_LOADGEN}/start", json={"mode": "fixed", "n": int(n)})


def tick_rows(since_ts):
    try:
        df = pd.read_csv(C.CLUSTER_TICKS_CSV, on_bad_lines="skip")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()
    return df[df["ts"] >= since_ts].reset_index(drop=True)


def summarize(df, ctx, policy, rep, scenario, events):
    if df.empty:
        return {}
    tick_len = ctx["tick_seconds"]
    err_rate = df["errors"] / df["requests"].clip(lower=1)
    miss = (df["p95_ms"].fillna(1e9) > ctx["slo_ms"]) | (err_rate > 0.01)
    miss &= df["requests"] > 0
    over = df["requests"] > df["ready"] * ctx["capacity"]
    ev = events[events["event"] == "ready"]["startup_s"].dropna() if not events.empty else pd.Series(dtype=float)
    return {"policy": policy, "rep": rep, "ticks": len(df), "slo_miss_ticks": int(miss.sum()), "slo_miss_pct": round(100 * miss.mean(), 1),
            "failed_requests": int(df["errors"].sum()), "total_requests": int(df["requests"].sum()),
            "failed_pct": round(100 * df["errors"].sum() / max(df["requests"].sum(), 1), 2),
            "replica_seconds": round(float((df["ready"] * tick_len).sum()), 1), "max_replicas_used": int(df["ready"].max()),
            "replica_changes": int((df["desired"].diff().fillna(0) != 0).sum()),
            "mean_startup_s": round(float(ev.mean()), 2) if len(ev) else None, "overload_ticks": int(over.sum()),
            "p95_peak_ms": round(float(df["p95_ms"].max()), 1) if df["p95_ms"].notna().any() else None, **scenario}


def main():
    p = argparse.ArgumentParser(description="Run one scaling policy against a spike, with real replicas")
    p.add_argument("--policy", choices=["static", "reactive", "hpa", "aegis"], required=True)
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--static-n", type=int, default=3)
    p.add_argument("--base", type=int, default=None, help="quiet traffic, requests per tick (default: 25%% of the machine's capacity)")
    p.add_argument("--spike", type=int, default=None, help="spike traffic, requests per tick (default: 80%% of the machine's capacity)")
    p.add_argument("--warmup-ticks", type=int, default=20)
    p.add_argument("--spike-ticks", type=int, default=30)
    p.add_argument("--cooldown-ticks", type=int, default=30)
    a = p.parse_args()

    rt = R.load()
    dev = DV.load_device()
    cap = float(rt["capacity_per_tick"])
    tick = float(rt["tick_seconds"])
    total = cap * dev.limits()["max_replicas"]
    base = a.base or int(0.25 * total)
    spike = a.spike or int(0.8 * total)
    ctx = {"capacity": cap, "tick_seconds": tick, "slo_ms": dev.slo_p95_ms, "cpu_limit": dev.cpu_per_replica}
    scenario = {"base": base, "spike": spike, "tick_seconds": tick, "capacity_per_tick": cap, "capacity_source": rt.get("capacity_source"),
                "max_replicas": dev.limits()["max_replicas"], "backend": rt["backend"]}
    print(f"policy {a.policy} | base {base}/tick -> spike {spike}/tick | capacity {cap:.0f}/tick per replica ({rt.get('capacity_source')}) | tick {tick:g} s")
    if rt.get("capacity_source") != "calibrated":
        print("NOTE: capacity is an estimate. For the paper run the calibration first (dashboard, Device & Timer).")
    EXP_DIR.mkdir(parents=True, exist_ok=True)

    for rep in range(1, a.reps + 1):
        print(f"\n--- repetition {rep}/{a.reps} ---")
        policy = make_policy(a.policy, a)
        set_traffic(base)
        if a.policy != "aegis":
            api("POST", f"{C.URL_GATEWAY}/infra/scale", json={"n": 1, "source": "experiment"})
        time.sleep(3 * tick)                                           # settle at the quiet level
        t_start = time.time()
        schedule = [(a.warmup_ticks, base), (a.spike_ticks, spike), (a.cooldown_ticks, base)]
        for ticks, level in schedule:
            set_traffic(level)
            end = time.time() + ticks * tick
            while time.time() < end:
                st = state()
                rows = tick_rows(t_start)
                want = policy.decide(rows, st, ctx)
                if want is not None and want != st["desired"]:
                    api("POST", f"{C.URL_GATEWAY}/infra/scale", json={"n": int(want), "source": a.policy})
                time.sleep(min(1.0, tick))
            print(f"  level {level}/tick done, replicas ready {state()['ready']}")
        df = tick_rows(t_start)
        ev = pd.read_csv(C.EVENTS_CSV, on_bad_lines="skip")
        ev = ev[ev["ts"] >= t_start]
        run_dir = EXP_DIR / f"{a.policy}_rep{rep}"
        run_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(run_dir / "ticks.csv", index=False)
        ev.to_csv(run_dir / "events.csv", index=False)
        row = summarize(df, ctx, a.policy, rep, scenario, ev)
        res = EXP_DIR / "results.csv"
        pd.DataFrame([row]).to_csv(res, mode="a", header=not res.exists(), index=False)
        print("  " + ", ".join(f"{k}={row[k]}" for k in ("slo_miss_ticks", "failed_pct", "replica_seconds", "mean_startup_s", "overload_ticks")))
    set_traffic(base)
    print(f"\nResults appended to {EXP_DIR / 'results.csv'}")


if __name__ == "__main__":
    main()
