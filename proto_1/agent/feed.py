"""
feed.py - where the agent gets its input. It replaces the old dataset replay.

LiveFeed asks the prediction service (GET /latest) for the newest tick: the traffic that just arrived and the
LSTM forecasts for +10 and +20 simulated minutes. It also sizes the replicas from the seed data (your training
data), exactly like the old Feed did: capacity per replica = mean traffic / AVG_REPLICAS.
"""
from __future__ import annotations

import math
import time

import requests

import seed as seed_mod
import settings as S
from agent import config as cfg


class LiveFeed:
    def __init__(self, base_url: str = S.URL_PREDICTION):
        self.url = base_url
        stats = seed_mod.seed_stats()
        self.capacity = cfg.CAPACITY_PER_REPLICA or max(1.0, stats["mean"] / cfg.AVG_REPLICAS)
        self.max_replicas = cfg.MAX_REPLICAS or max(10, math.ceil(stats["max"] * 1.5 / self.capacity))

    # ------------------------------------------------------------------ waiting for the prediction service
    def status(self):
        try:
            return requests.get(f"{self.url}/status", timeout=3).json()
        except Exception:
            return None

    def wait_until_ready(self, say=print):
        """Block until the prediction service is up, has a model and enough history for the first forecast."""
        last_msg = 0.0
        while True:
            st = self.status()
            if st and st.get("ready"):
                return st
            if time.time() - last_msg >= cfg.STATUS_EVERY:
                if st is None:
                    say(f"waiting for the prediction service at {self.url} ...")
                elif not st.get("horizons"):
                    say("prediction service is up but has no model: copy lstm_requests_forecaster.pt to prediction/models/")
                else:
                    say(f"warming up: history {st['history_rows']} / {st['rows_needed']} rows")
                last_msg = time.time()
            time.sleep(cfg.POLL_SECONDS)

    # ------------------------------------------------------------------ one tick
    def next_tick(self, after_minute, should_stop=lambda: False):
        """Wait for a forecast row with minute > after_minute and return it as the dict the graph expects."""
        while not should_stop():
            try:
                p = requests.get(f"{self.url}/latest", timeout=3).json().get("prediction")
            except Exception:
                p = None
            if p and int(p["minute"]) > after_minute:
                key = f"forecast_h{cfg.FORECAST_HORIZON}"
                if p.get(key) not in (None, ""):
                    h20 = p.get("forecast_h20")
                    return {
                        "minute": int(p["minute"]), "traffic_now": float(p["requests_now"]),
                        "forecast": float(p[key]), "forecast_for": int(p[f"forecast_for_h{cfg.FORECAST_HORIZON}"]),
                        "forecast_h20": None if h20 in (None, "") else float(h20),
                        "drift_z": p.get("drift_z"), "history_source": p.get("history_source"),
                    }
            time.sleep(cfg.POLL_SECONDS)
        return None
