"""
engine.py - keeps the rolling history, calls the predictor on every new tick and saves each forecast to CSV.

History = the last rows of the seed file (so the first day of "yesterday" features exists) followed by every live
row. Rows must be consecutive minutes; if a row is missing the engine reloads the live CSV, which is the
authoritative record written by the collector.
"""
from __future__ import annotations

import csv
import logging
import math
import threading
from datetime import datetime

import pandas as pd

import seed as seed_mod
import settings as S
from prediction.predictor import Predictor

log = logging.getLogger("engine")

PRED_COLS = (["minute", "wallclock", "requests_now"]
             + [c for h in S.HORIZONS for c in (f"forecast_h{h}", f"forecast_for_h{h}")]
             + ["history_source", "drift_z", "drift_metric"])
MAX_HISTORY = S.DAY + S.W + 600


class Engine:
    def __init__(self, predictor: Predictor):
        self.predictor = predictor
        self.lock = threading.RLock()
        self.hist = pd.DataFrame(columns=["minute"] + S.METRIC_COLS)
        self.live_start_minute = None
        self.n_live = 0
        self.last = None                      # last prediction row (dict)
        self.errors = 0
        self.bootstrap()

    # ------------------------------------------------------------------ loading
    def _read_live(self):
        if not S.LIVE_CSV.exists() or S.LIVE_CSV.stat().st_size == 0:
            return pd.DataFrame(columns=["minute"] + S.METRIC_COLS)
        df = pd.read_csv(S.LIVE_CSV, on_bad_lines="skip")
        df = df.dropna(subset=["minute"] + S.METRIC_COLS)
        df = df.drop_duplicates("minute", keep="last").sort_values("minute")
        return df[["minute"] + S.METRIC_COLS].astype(float).reset_index(drop=True)

    def bootstrap(self):
        with self.lock:
            live = self._read_live()
            seed_rows = seed_mod.seed_tail(MAX_HISTORY)
            parts = []
            if seed_rows is not None and len(seed_rows):
                if len(live) == 0 or live["minute"].iloc[0] == seed_rows["minute"].iloc[-1] + 1:
                    parts.append(seed_rows)
                else:
                    log.warning("seed does not continue into the live file; using live rows only (warm-up needed)")
            parts.append(live)
            self.hist = pd.concat(parts, ignore_index=True).iloc[-MAX_HISTORY:].reset_index(drop=True)
            self.n_live = len(live)
            self.live_start_minute = float(live["minute"].iloc[0]) if len(live) else None

    # ------------------------------------------------------------------ status
    def status(self):
        with self.lock:
            need = self.predictor.rows_needed()
            n = len(self.hist)
            drift = self.predictor.drift(self.hist) if n >= S.W else (0.0, "")
            return {
                "models_loaded": self.predictor.describe(),
                "horizons": self.predictor.horizons,
                "ready": bool(self.predictor.ready and n >= need),
                "history_rows": n, "rows_needed": need, "live_rows": self.n_live,
                "history_source": self._source(),
                "last_minute": int(self.hist["minute"].iloc[-1]) if n else None,
                "drift_z": round(drift[0], 2), "drift_metric": drift[1],
                "tick_errors": self.errors,
            }

    def _source(self):
        """'live' once the whole day of history behind the forecast is real live data, else 'seed' (seed-assisted)."""
        need = self.predictor.rows_needed()
        if self.live_start_minute is None or len(self.hist) < need:
            return "seed"
        return "live" if self.hist["minute"].iloc[-need] >= self.live_start_minute else "seed"

    # ------------------------------------------------------------------ one tick
    def ingest(self, row: dict):
        """Add one live row, forecast, save. Returns the prediction row, or None (duplicate / not enough history)."""
        minute = float(row["minute"])
        values = {c: float(row[c]) for c in S.METRIC_COLS}
        if any(not math.isfinite(v) for v in values.values()):
            raise ValueError("non-finite metric value")
        with self.lock:
            last = float(self.hist["minute"].iloc[-1]) if len(self.hist) else None
            if last is not None and minute <= last:
                return None                                           # duplicate / old row
            if last is not None and minute != last + 1:
                log.warning("gap in minutes (%s -> %s): reloading from the live CSV", last, minute)
                self.bootstrap()
                last = float(self.hist["minute"].iloc[-1]) if len(self.hist) else None
                if last is not None and minute <= last:
                    return self._predict_last()
            new = pd.DataFrame([{"minute": minute, **values}])
            self.hist = pd.concat([self.hist, new], ignore_index=True).iloc[-MAX_HISTORY:].reset_index(drop=True)
            self.n_live += 1
            if self.live_start_minute is None:
                self.live_start_minute = minute
            return self._predict_last()

    def _predict_last(self):
        if len(self.hist) < self.predictor.rows_needed():
            return None
        f = self.predictor.forecast(self.hist)
        if not f:
            return None
        minute = int(self.hist["minute"].iloc[-1])
        z, zm = self.predictor.drift(self.hist)
        row = {"minute": minute, "wallclock": datetime.now().isoformat(timespec="seconds"),
               "requests_now": round(float(self.hist["requests"].iloc[-1]), 1),
               "history_source": self._source(), "drift_z": round(z, 2), "drift_metric": zm}
        for h in S.HORIZONS:
            row[f"forecast_h{h}"] = round(f[h], 1) if h in f else ""
            row[f"forecast_for_h{h}"] = minute + h if h in f else ""
        self._append(row)
        self.last = row
        return row

    @staticmethod
    def _append(row):
        S.PRED_CSV.parent.mkdir(parents=True, exist_ok=True)
        new_file = not S.PRED_CSV.exists() or S.PRED_CSV.stat().st_size == 0
        with open(S.PRED_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=PRED_COLS)
            if new_file:
                w.writeheader()
            w.writerow(row)
