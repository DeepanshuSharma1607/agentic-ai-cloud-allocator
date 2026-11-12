"""
middleware.py - writes web-request logs for a FastAPI part, without flooding the log.

ROLE
    The gateway, sender, collector, prediction service and demo target app are all small web servers. Adding this
    middleware (one line in each) makes every request visible in the logs - which was the missing piece before.

HOW IT WORKS
    Three kinds of request are treated differently:
      HOT     (busy, e.g. /work: thousands per tick)  -> ONE summary line every few seconds:
                  "/work: 412 arrived, 380 finished, 3 failed, 32 still waiting (5.0s window ...) [200x377, 503x3], avg 31 ms"
                  ("still waiting" = arrived but not answered yet: it is how a backlog becomes visible)
      QUIET   (polled all the time, e.g. /health, /snapshot) -> only at DEBUG level, so they do not drown real events
      OTHER   (rare, important: POST /infra/scale, /start, /stop ...) -> one line each: "POST /infra/scale -> 200 (12 ms)"
    Any 4xx/5xx answer is a WARNING. An exception inside the app is logged with its full traceback, then re-raised.
    Every response gets an  x-request-id  header so one request can be followed across parts.

REMEMBER
    - It is a pure ASGI middleware: no body is read, so it adds almost no delay even at thousands of requests.
    - The summary is flushed when the next request arrives after the window (no background thread).

TEST    python -m pytest tests/test_obs.py -q
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import Counter

QUIET_DEFAULT = ("/health", "/snapshot", "/status", "/latest", "/favicon.ico", "/infra/state", "/infra/events",
                 "/infra/resources", "/infra/calibrate/status", "/infra/device", "/api/logs", "/api/apps")


class RequestLogMiddleware:
    def __init__(self, app, name: str, hot: tuple = ("/work",), quiet: tuple = QUIET_DEFAULT, window_s: float = 5.0):
        self.app, self.hot, self.quiet, self.window_s = app, tuple(hot), tuple(quiet), float(window_s)
        self.log = logging.getLogger(name)
        self.arrived_total = self.finished_total = 0           # lifetime counts of the busy paths: their difference = still waiting
        self._reset()

    def _reset(self):
        self.t0 = time.time()
        self.n = self.fail = 0
        self.arrived = 0
        self.total_ms = self.max_ms = 0.0
        self.codes: Counter = Counter()
        self.path = ""

    def _flush(self, now: float):
        if self.n:
            secs = max(now - self.t0, 0.001)
            codes = ", ".join(f"{c}x{k}" for c, k in sorted(self.codes.items()))
            waiting = max(0, self.arrived_total - self.finished_total)
            self.log.log(logging.WARNING if (self.fail or waiting > 100) else logging.INFO,
                         "%s: %d arrived, %d finished, %d failed, %d still waiting (%.1fs window, %.0f finishing/s) [%s], avg %.0f ms, max %.0f ms",
                         self.path, self.arrived, self.n, self.fail, waiting, secs, self.n / secs, codes, self.total_ms / self.n, self.max_ms)
        self._reset()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, method, rid = scope["path"], scope["method"], uuid.uuid4().hex[:8]
        t0, status = time.perf_counter(), 500
        if path in self.hot:
            self.arrived += 1
            self.arrived_total += 1

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            self.log.exception("%s %s crashed [%s]", method, path, rid)
            raise
        finally:
            self._record(method, path, status, (time.perf_counter() - t0) * 1000.0, rid)

    def _record(self, method: str, path: str, status: int, ms: float, rid: str):
        now = time.time()
        if now - self.t0 >= self.window_s:
            self._flush(now)
        failed = status >= 400
        if path in self.hot:
            self.path = path
            self.finished_total += 1
            self.n += 1
            self.fail += failed
            self.codes[status] += 1
            self.total_ms += ms
            self.max_ms = max(self.max_ms, ms)
        elif path in self.quiet and not failed:
            self.log.debug("%s %s -> %d (%.0f ms) [%s]", method, path, status, ms, rid)
        else:
            self.log.log(logging.WARNING if failed else logging.INFO, "%s %s -> %d (%.0f ms) [%s]", method, path, status, ms, rid)
