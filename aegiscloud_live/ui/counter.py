"""
counter.py - APP 1 logic: the live request counter that powers the big-screen page (ui/counter.html).

ROLE
    The "screen above the shop door". The gateway (run_live.py) or the demo target app (run_all.py) is the front door that
    every request passes through. This file counts what passes, and serves a page that shows it large and live:
        http://localhost:8001            the page
        http://localhost:8001/counter/data   the same numbers as JSON (the page asks for them every second)

HOW IT WORKS
    - CounterMiddleware wraps the web app. For each request to /work it does  start()  when it arrives and  finish(status)
      when the answer leaves. That gives: requests being handled RIGHT NOW (in flight), total received, total failed.
    - Arrivals are also counted per second, so the page can show "requests per second" and a 30-second sparkline.
    - mount(app) adds the middleware and the two routes. The gateway also passes `extra` so the page can show replicas.

REMEMBER
    - Numbers are per request to /work: arrived (start), answered OK / failed (finish), time it took, and the busiest second seen.
    - It only READS traffic. It never changes, delays or blocks a request, and the counter resets when the app restarts.
    - It is separate from the collector's /snapshot window, so opening the page never disturbs your measurements.
    - "Being handled right now" is small at low traffic (a request takes ~40 ms), so the page also shows requests per second.

TEST    python -m pytest tests/test_part2.py -q
"""
from __future__ import annotations

import time
from collections import deque
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from obs.rates import RateWindow

HISTORY_S = 30                      # seconds shown in the sparkline
RATE_WINDOW_S = 5                   # "requests per second" = average of the last 5 complete seconds


class RequestCounter:
    def __init__(self):
        self.total = self.failed = self.ok = self.inflight = 0
        self.buckets: deque = deque()                 # [second, arrivals in that second]
        self.fail_times: deque = deque()              # when recent failures happened
        self.ok_rate = RateWindow()                   # answered OK, per second
        self.durations: deque = deque()               # (finish time, milliseconds) of recent requests

    def start(self):
        self.total += 1
        self.inflight += 1
        sec = int(time.time())
        if self.buckets and self.buckets[-1][0] == sec:
            self.buckets[-1][1] += 1
        else:
            self.buckets.append([sec, 1])
            while len(self.buckets) > 120:
                self.buckets.popleft()

    def finish(self, status: int, ms: float = 0.0):
        self.inflight = max(0, self.inflight - 1)
        now = time.time()
        self.durations.append((now, ms))
        while self.durations and now - self.durations[0][0] > RATE_WINDOW_S * 2:
            self.durations.popleft()
        if status < 400:
            self.ok += 1
            self.ok_rate.add()
        if status >= 400:
            self.failed += 1
            self.fail_times.append(time.time())
            while len(self.fail_times) > 1000:
                self.fail_times.popleft()

    def per_second(self, seconds: int = HISTORY_S) -> list[int]:
        """Arrivals in each of the last `seconds` COMPLETE seconds, oldest first (0 where nothing arrived)."""
        last = int(time.time()) - 1
        have = {sec: n for sec, n in self.buckets}
        return [have.get(s, 0) for s in range(last - seconds + 1, last + 1)]

    def data(self) -> dict:
        hist = self.per_second()
        recent = hist[-RATE_WINDOW_S:]
        now = time.time()
        recent_ms = [ms for t, ms in self.durations if now - t <= RATE_WINDOW_S * 2]
        peak = max([n for _, n in self.buckets] or [0])
        return {"inflight": self.inflight, "waiting": self.inflight, "rps": round(sum(recent) / len(recent), 1), "history": hist,
                "ok_per_s": self.ok_rate.rate(RATE_WINDOW_S * 2), "avg_ms": round(sum(recent_ms) / len(recent_ms), 1) if recent_ms else 0.0,
                "peak_rps": peak, "total": self.total, "ok": self.ok, "failed": self.failed,
                "failing_now": sum(1 for t in self.fail_times if now - t <= RATE_WINDOW_S), "time": round(now, 2)}


class CounterMiddleware:
    """Pure ASGI middleware: counts requests to the given paths without touching them."""

    def __init__(self, app, counter: RequestCounter, paths: tuple = ("/work",)):
        self.app, self.counter, self.paths = app, counter, tuple(paths)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] not in self.paths:
            return await self.app(scope, receive, send)
        status = 500
        t0 = time.perf_counter()
        self.counter.start()

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            self.counter.finish(status, (time.perf_counter() - t0) * 1000.0)


def mount(app, extra=None, paths: tuple = ("/work",)) -> RequestCounter:
    """Add the counter to a FastAPI app: GET / (the page) and GET /counter/data (the numbers). `extra()` may add more fields."""
    counter = RequestCounter()
    app.add_middleware(CounterMiddleware, counter=counter, paths=paths)
    # read-only sharing: the sender page may READ these numbers (GET only) so both pages can show the same picture
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=[])
    page = Path(__file__).with_name("counter.html")

    @app.get("/", response_class=HTMLResponse)
    def counter_page():
        return page.read_text(encoding="utf-8")

    @app.get("/counter/data")
    def counter_data():
        out = counter.data()
        if extra:
            try:
                out.update(extra())
            except Exception:                         # e.g. the cluster manager is still starting: show the counter anyway
                pass
        return out

    return counter
