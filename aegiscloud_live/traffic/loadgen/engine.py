"""
engine.py - the request SENDER. Every tick it asks the plan how many requests to send, spreads them evenly over the
tick and fires them at the target app (always the app from settings.py: the sender cannot be pointed elsewhere).

Two layers of plans:
  base plan      what runs "all the time" (set with /start, stop with /stop)
  schedule       timed segments that temporarily override the base plan, e.g. "in 2 minutes send 400 per tick for 5 minutes"
"""
from __future__ import annotations

import asyncio
import csv
import logging
import time
from datetime import datetime

import httpx

from obs.rates import RateWindow

import settings as S
from traffic.loadgen.plans import Planner

log = logging.getLogger("loadgen")
REQUEST_TIMEOUT = 5.0                                  # a request slower than this counts as failed (a "timeout")


class TickCounter:
    def __init__(self, planned, label, mode, minute):
        self.planned, self.label, self.mode, self.minute = planned, label, mode, minute
        self.sent = self.ok = self.failed = 0

    def as_dict(self):
        return {"planned": self.planned, "sent": self.sent, "ok": self.ok, "failed": self.failed,
                "label": self.label, "mode": self.mode}


class LoadEngine:
    def __init__(self):
        self.planner = Planner()
        self.base = {"mode": "idle"}
        self.base_version = 0
        self.segments: list[dict] = []
        self.finished: list[dict] = []
        self.next_id = 1
        self.totals = {"planned": 0, "sent": 0, "ok": 0, "failed": 0}   # sent/ok/failed are updated the moment each request starts or finishes
        self.rates = {k: RateWindow() for k in ("sent", "ok", "failed")}  # per-second view of the same events (for the pages)
        self.lat: list = []                                              # seconds taken by the most recent finished requests
        self.last = TickCounter(0, "idle", "idle", None)
        self.minute = None
        self._tasks: set = set()
        self.running = True
        if S.LOADGEN_AUTOSTART == "pattern":
            self.set_base({"mode": "pattern", "scale": 1.0, "noise": 0.25, "burst_prob": 0.01, "burst_mult": 3.0})

    # ------------------------------------------------------------------ control
    def set_base(self, plan: dict):
        self.base = dict(plan)
        self.base_version += 1
        self.planner.reset("base")
        self._event("start" if plan.get("mode") != "idle" else "stop", plan)

    def stop(self, cancel_schedule=True):
        self.set_base({"mode": "idle"})
        if cancel_schedule:
            for s in self.segments:
                s["status"] = "cancelled"
            self.finished += self.segments
            self.segments = []

    def add_segment(self, plan: dict, duration_s: float, start_ts: float):
        seg = {"id": self.next_id, "plan": dict(plan), "start": start_ts, "end": start_ts + duration_s, "status": "scheduled"}
        self.next_id += 1
        self.segments.append(seg)
        self._event("schedule", {"id": seg["id"], "plan": plan, "start": datetime.fromtimestamp(start_ts).isoformat(timespec="seconds"),
                                 "duration_s": duration_s})
        return seg

    def cancel_segment(self, seg_id: int):
        for s in self.segments:
            if s["id"] == seg_id:
                s["status"] = "cancelled"
                self.segments.remove(s)
                self.finished.append(s)
                self.planner.reset(f"seg{seg_id}")
                self._event("cancel", {"id": seg_id})
                return True
        return False

    def active(self, now: float):
        """(label, plan, key) of what to send right now: the newest running segment, else the base plan."""
        for s in list(self.segments):
            if now >= s["end"]:
                s["status"] = "done"
                self.segments.remove(s)
                self.finished.append(s)
                self.planner.reset(f"seg{s['id']}")
        self.finished = self.finished[-30:]
        running = [s for s in self.segments if s["start"] <= now < s["end"]]
        if running:
            s = max(running, key=lambda x: x["start"])
            s["status"] = "running"
            return f"schedule#{s['id']}:{s['plan'].get('mode')}", s["plan"], f"seg{s['id']}"
        return f"base:{self.base.get('mode')}", self.base, "base"

    def status(self):
        now = time.time()
        label, _, _ = self.active(now)
        segs = [{"id": s["id"], "status": s["status"], "plan": s["plan"],
                 "starts_in_s": round(max(s["start"] - now, 0), 1), "remaining_s": round(max(s["end"] - now, 0), 1),
                 "start_at": datetime.fromtimestamp(s["start"]).isoformat(timespec="seconds"),
                 "duration_s": round(s["end"] - s["start"], 1)} for s in self.segments]
        return {"running": self.running, "base_plan": self.base, "active_label": label, "segments": segs,
                "recent_segments": [{"id": s["id"], "status": s["status"], "plan": s["plan"]} for s in self.finished[-5:]],
                "totals": self.totals, "last_tick": self.last.as_dict(), "minute": self.minute,
                "in_flight": max(0, self.totals["sent"] - self.totals["ok"] - self.totals["failed"]),
                "rates": {"window_s": 10, "sent_per_s": self.rates["sent"].rate(10), "ok_per_s": self.rates["ok"].rate(10),
                          "failed_per_s": self.rates["failed"].rate(10), "avg_ms": self._avg_ms()},
                "max_per_tick": S.MAX_REQUESTS_PER_TICK, "tick_seconds": S.TICK_SECONDS, "target": S.URL_TARGET}

    def _avg_ms(self) -> float:
        recent = self.lat[-100:]
        return round(1000 * sum(recent) / len(recent), 1) if recent else 0.0

    # ------------------------------------------------------------------ logging
    @staticmethod
    def _append(path, cols, row):
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            try:
                new = not path.exists() or path.stat().st_size == 0
                with open(path, "a", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=cols)
                    if new:
                        w.writeheader()
                    w.writerow(row)
                return
            except OSError as e:                                       # locked file: never stop the sender because of a log row
                if attempt == 2:
                    log.warning("could not write one row to %s (%s): dropped, sender keeps running", path.name, e)
                    return
                time.sleep(0.3)

    def _event(self, kind, detail):
        self._append(S.LOADGEN_DIR / "events.csv", ["wallclock", "event", "detail"],
                     {"wallclock": datetime.now().isoformat(timespec="seconds"), "event": kind, "detail": str(detail)})

    def _log_tick(self, c: TickCounter):
        waiting = max(0, self.totals["sent"] - self.totals["ok"] - self.totals["failed"])
        log.info("tick (minute %s): planned %s, started %s, answered ok %s, failed %s; %s requests still waiting overall [%s]",
                 c.minute, c.planned, c.sent, c.ok, c.failed, waiting, c.label)
        self.totals["planned"] += c.planned
        self._append(S.LOADGEN_DIR / "load_ticks.csv", ["wallclock", "minute", "label", "mode", "planned", "sent", "ok", "failed"],
                     {"wallclock": datetime.now().isoformat(timespec="seconds"), "minute": c.minute, "label": c.label,
                      "mode": c.mode, "planned": c.planned, "sent": c.sent, "ok": c.ok, "failed": c.failed})

    # ------------------------------------------------------------------ sending
    async def _send(self, client, c: TickCounter):
        c.sent += 1
        self.totals["sent"] += 1
        self.rates["sent"].add()
        t0 = time.perf_counter()
        try:
            r = await client.get(f"{S.URL_TARGET}/work")
            good = r.status_code == 200
        except Exception:
            good = False
        self.lat.append(time.perf_counter() - t0)
        del self.lat[:-300]
        key = "ok" if good else "failed"
        setattr(c, key, getattr(c, key) + 1)                 # the tick's own counter (kept for the CSV row)
        self.totals[key] += 1                                # the running total: late answers are no longer lost
        self.rates[key].add()

    async def _spread(self, client, n, c: TickCounter):
        loop = asyncio.get_running_loop()
        start, span = loop.time(), S.TICK_SECONDS * 0.95
        for off in sorted(self.planner.rng.random() * span for _ in range(n)):
            delay = start + off - loop.time()
            if delay > 0.002:
                await asyncio.sleep(delay)
            t = asyncio.create_task(self._send(client, c))
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

    async def _current_minute(self, client):
        try:
            r = await client.get(f"{S.URL_COLLECTOR}/status", timeout=0.5)
            return int(r.json()["next_minute"])
        except Exception:
            return (self.minute + 1) if self.minute is not None else 0

    async def run(self):
        limits = httpx.Limits(max_connections=1500, max_keepalive_connections=300)
        loop = asyncio.get_running_loop()
        async with httpx.AsyncClient(limits=limits, timeout=REQUEST_TIMEOUT) as client:
            next_t = loop.time()
            while True:
                await asyncio.sleep(max(0.0, next_t - loop.time()))
                next_t += S.TICK_SECONDS
                if next_t < loop.time():
                    next_t = loop.time() + S.TICK_SECONDS
                self._log_tick(self.last) if self.last.minute is not None else None
                self.minute = await self._current_minute(client)
                label, plan, key = self.active(time.time())
                try:
                    n = self.planner.count(plan, self.minute, key) if self.running else 0
                except Exception as e:
                    log.warning("plan error (%s) - sending nothing this tick", e)
                    n = 0
                self.last = TickCounter(n, label, plan.get("mode", "idle"), self.minute)
                if n:
                    t = asyncio.create_task(self._spread(client, n, self.last))
                    self._tasks.add(t)
                    t.add_done_callback(self._tasks.discard)
