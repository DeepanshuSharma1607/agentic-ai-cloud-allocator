"""
collector/app.py - the metrics collector (FastAPI, port 8003).

Every TICK_SECONDS it:
  1. asks the target app for its metrics window (GET /snapshot),
  2. asks the load generator what it was planning (for the dashboard only),
  3. writes ONE row to data/live/live_metrics.csv  (same columns as your metrics_combined.csv + a few extras),
  4. sends that row to the prediction service (POST /tick), which saves the forecast.

Minute numbers continue from the seed file (or from the live file after a restart), so the model's
time-of-day features stay correct. A latency percentile is carried forward when a window had no completed request.

  GET /status   POST /pause   POST /resume   GET /latest
"""
import asyncio
import csv
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI

import seed as seed_mod
import settings as S

log = logging.getLogger("collector")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
PCT = ["p50_ms", "p95_ms", "p99_ms"]


class Collector:
    def __init__(self):
        self.minute = seed_mod.next_minute()
        self.tick = self._count_rows()
        self.paused = False
        self.errors = 0
        self.rows = 0
        self.last_row = None
        self.carry = {c: 0.0 for c in PCT}
        self.prediction_ok = None

    @staticmethod
    def _count_rows():
        if not S.LIVE_CSV.exists():
            return 0
        with open(S.LIVE_CSV, "rb") as f:
            return max(sum(1 for _ in f) - 1, 0)

    async def collect_once(self, client: httpx.AsyncClient):
        try:
            snap = (await client.get(f"{S.URL_TARGET}/snapshot")).json()
        except Exception as e:
            self.errors += 1
            log.warning("target app unreachable: %s", e)
            return None
        mode, planned = "", ""
        try:
            ls = (await client.get(f"{S.URL_LOADGEN}/status", timeout=0.7)).json()
            mode, planned = ls.get("active_label", ""), ls.get("last_tick", {}).get("planned", "")
        except Exception:
            pass
        for c in PCT:
            if snap.get(c) is None:
                snap[c] = self.carry[c]
            else:
                self.carry[c] = snap[c]
        row = {"tick": self.tick, "minute": self.minute, "wallclock": datetime.now().isoformat(timespec="seconds"),
               "load_mode": mode, "planned": planned, "ok": snap["ok"], "errors": snap["errors"]}
        for c in S.METRIC_COLS:
            row[c] = round(float(snap[c]), 2)
        self._append(row)
        self.tick += 1
        self.minute += 1
        self.rows += 1
        self.last_row = row
        try:
            r = await client.post(f"{S.URL_PREDICTION}/tick", json=row, timeout=10)
            self.prediction_ok = r.status_code == 200
            if not self.prediction_ok:
                log.warning("prediction service answered %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            self.prediction_ok = False
            log.warning("prediction service unreachable (row is saved, it will catch up): %s", e)
        return row

    @staticmethod
    def _append(row):
        S.LIVE_CSV.parent.mkdir(parents=True, exist_ok=True)
        new_file = not S.LIVE_CSV.exists() or S.LIVE_CSV.stat().st_size == 0
        with open(S.LIVE_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=S.LIVE_COLS)
            if new_file:
                w.writeheader()
            w.writerow(row)

    async def run(self):
        loop = asyncio.get_running_loop()
        async with httpx.AsyncClient(timeout=5) as client:
            try:
                await client.get(f"{S.URL_TARGET}/snapshot")          # discard the half-filled first window
            except Exception:
                pass
            next_t = loop.time() + S.TICK_SECONDS
            while True:
                await asyncio.sleep(max(0.0, next_t - loop.time()))
                next_t += S.TICK_SECONDS
                if next_t < loop.time():                              # we fell far behind: do not fire a burst of catch-up ticks
                    next_t = loop.time() + S.TICK_SECONDS
                if not self.paused:
                    await self.collect_once(client)


@asynccontextmanager
async def lifespan(app):
    app.state.c = Collector()
    task = asyncio.create_task(app.state.c.run())
    yield
    task.cancel()


app = FastAPI(title="AegisCloud collector", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/status")
def status():
    c = app.state.c
    return {"paused": c.paused, "next_minute": c.minute, "rows_written": c.rows, "errors": c.errors,
            "prediction_service_ok": c.prediction_ok, "tick_seconds": S.TICK_SECONDS, "last_row": c.last_row}


@app.get("/latest")
def latest():
    return app.state.c.last_row or {}


@app.post("/pause")
def pause():
    app.state.c.paused = True
    return {"paused": True}


@app.post("/resume")
def resume():
    app.state.c.paused = False
    return {"paused": False}
