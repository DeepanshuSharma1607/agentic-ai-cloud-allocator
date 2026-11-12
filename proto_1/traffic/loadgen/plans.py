"""
plans.py - pure logic: how many requests to send in the next tick for a given plan. No network, easy to test.

A plan is a dict:
  {"mode": "idle"}
  {"mode": "fixed",   "n": 300}                                   exactly n requests every tick
  {"mode": "random",  "lo": 50, "hi": 400, "smooth": 0.5}         random count each tick (smooth 0..0.95 = less jumpy)
  {"mode": "pattern", "scale": 1.0, "noise": 0.25,                the typical daily curve of your training data x noise,
                      "burst_prob": 0.01, "burst_mult": 3.0}      plus occasional bursts. Closest to what the model was trained on
  {"mode": "replay",  "start": 0, "scale": 1.0}                   replays the real `requests` column of the seed, row by row

One tick = 5 real seconds = 1 simulated minute, so "n per tick" means n/5 requests per second.
"""
from __future__ import annotations

import math
import random

import seed as seed_mod
import settings as S

MODES = ("idle", "fixed", "random", "pattern", "replay")


class Planner:
    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.profile = seed_mod.daily_profile()
        self.stats = seed_mod.seed_stats()
        seed_df = seed_mod.load_seed()
        self.replay_values = None if seed_df is None else seed_df["requests"].to_numpy()
        self.state: dict = {}

    def reset(self, key):
        self.state.pop(key, None)

    def count(self, plan: dict, minute: float, key: str = "base") -> int:
        mode = plan.get("mode", "idle")
        st = self.state.setdefault(key, {"prev": None, "burst": 0, "idx": int(plan.get("start", 0))})
        if mode == "idle":
            n = 0.0
        elif mode == "fixed":
            n = float(plan.get("n", 0))
        elif mode == "random":
            lo, hi = sorted((int(plan.get("lo", 0)), int(plan.get("hi", 0))))
            raw = self.rng.randint(lo, hi)
            s = min(max(float(plan.get("smooth", 0.0)), 0.0), 0.95)
            n = raw if st["prev"] is None else st["prev"] * s + raw * (1 - s)
        elif mode == "pattern":
            base = self.profile[int(minute) % S.DAY] * self.stats["mean"] * float(plan.get("scale", 1.0))
            n = base * self.rng.lognormvariate(0.0, float(plan.get("noise", 0.25)))
            if st["burst"] > 0:
                st["burst"] -= 1
                n *= float(plan.get("burst_mult", 3.0))
            elif self.rng.random() < float(plan.get("burst_prob", 0.01)):
                st["burst"] = self.rng.randint(3, 8)
                n *= float(plan.get("burst_mult", 3.0))
        elif mode == "replay":
            if self.replay_values is None:
                raise ValueError("replay needs data/seed/metrics_combined.csv")
            n = float(self.replay_values[st["idx"] % len(self.replay_values)]) * float(plan.get("scale", 1.0))
            st["idx"] += 1
        else:
            raise ValueError(f"unknown mode {mode!r}")
        st["prev"] = n
        if not math.isfinite(n):
            n = 0.0
        return int(min(max(round(n), 0), S.MAX_REQUESTS_PER_TICK))
