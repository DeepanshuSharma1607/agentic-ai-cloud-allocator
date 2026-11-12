"""
target_app/app.py - the small app that RECEIVES the traffic (FastAPI, port 8001).

It stands in for "your real app". Every request to /work takes about SERVICE_MS milliseconds, burns a little real
CPU, and waits in a queue when more than CONCURRENCY requests arrive together, so latency grows when the load
grows - just like a real service. It also measures itself:

  GET /snapshot   returns the metrics of the window since the last snapshot and starts a new window:
                  requests (arrivals), ok, errors, p50/p95/p99 latency, achieved_rps, app CPU %, host CPU %, memory MB
  POST /tune      change service time / concurrency / queue limit while running (experiments)

The collector calls /snapshot every tick (5 s). To monitor your OWN app instead, make it expose the same JSON.
"""
import asyncio
import math
import random
import time
from contextlib import asynccontextmanager

import numpy as np
import psutil
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import settings as S
from obs import log as obslog
from obs.middleware import RequestLogMiddleware
from ui.counter import mount as mount_counter

obslog.setup("target_app")                      # shared logging: console + data/logs/target_app.jsonl


class Window:
    def __init__(self):
        self.started = time.perf_counter()
        self.arrivals = 0
        self.ok = 0
        self.errors = 0
        self.lat = []


def _burn(ms):
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        pass


@asynccontextmanager
async def lifespan(app):
    app.state.cfg = {"service_ms": S.TARGET_SERVICE_MS, "concurrency": S.TARGET_CONCURRENCY,
                     "max_queue": S.TARGET_MAX_QUEUE, "cpu_burn_ms": S.TARGET_CPU_BURN_MS}
    app.state.sem = asyncio.Semaphore(app.state.cfg["concurrency"])
    app.state.waiting = 0
    app.state.win = Window()
    app.state.proc = psutil.Process()
    # Training data had app memory of ~103 MB with almost no variation, and the LSTM standardises it with a tiny sd.
    # A bare FastAPI process uses ~60 MB, which would look like an extreme outlier to the model. So the demo app
    # holds some ballast to behave like a typical app of that size.
    pad_mb = max(0.0, S.TARGET_MEM_MB - app.state.proc.memory_info().rss / 1e6)
    app.state.ballast = bytearray(b"\x01") * int(pad_mb * 1e6)
    app.state.proc.cpu_percent(interval=None)       # prime the counters: the first real sample is then meaningful
    psutil.cpu_percent(interval=None)
    yield


app = FastAPI(title="AegisCloud demo target app", lifespan=lifespan)
app.add_middleware(RequestLogMiddleware, name="target_app", hot=("/work",))
mount_counter(app)                              # APP 1: big-screen counter page at GET /


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/work")
async def work():
    st, win = app.state, app.state.win
    win.arrivals += 1
    t0 = time.perf_counter()
    if st.waiting >= st.cfg["max_queue"]:
        win.errors += 1
        return JSONResponse({"ok": False, "error": "queue full"}, status_code=503)
    st.waiting += 1
    sem = st.sem                                     # keep the same semaphore for acquire AND release, even if /tune swaps it
    async with sem:
        st.waiting -= 1
        sigma = 0.35
        service = random.lognormvariate(math.log(st.cfg["service_ms"] / 1000.0) - sigma ** 2 / 2, sigma)
        _burn(st.cfg["cpu_burn_ms"])
        await asyncio.sleep(service)
    win.ok += 1
    win.lat.append((time.perf_counter() - t0) * 1000.0)
    return {"ok": True}


@app.get("/snapshot")
async def snapshot():
    st = app.state
    win, now = st.win, time.perf_counter()
    elapsed = max(now - win.started, 1e-6)
    lat = np.asarray(win.lat) if win.lat else None
    out = {
        "window_seconds": round(elapsed, 3),
        "requests": win.arrivals, "ok": win.ok, "errors": win.errors,
        "p50_ms": None if lat is None else float(np.percentile(lat, 50)),
        "p95_ms": None if lat is None else float(np.percentile(lat, 95)),
        "p99_ms": None if lat is None else float(np.percentile(lat, 99)),
        "achieved_rps": win.ok / elapsed,
        "app_cpu_pct": st.proc.cpu_percent(interval=None),
        "host_cpu_pct": psutil.cpu_percent(interval=None),
        "app_mem_mb": st.proc.memory_info().rss / 1e6,
        "queue_waiting": st.waiting,
    }
    st.win = Window()
    return out


class Tune(BaseModel):
    service_ms: float | None = None
    concurrency: int | None = None
    max_queue: int | None = None
    cpu_burn_ms: float | None = None


@app.post("/tune")
async def tune(t: Tune):
    cfg = app.state.cfg
    if t.service_ms is not None:
        cfg["service_ms"] = max(1.0, t.service_ms)
    if t.max_queue is not None:
        cfg["max_queue"] = max(1, t.max_queue)
    if t.cpu_burn_ms is not None:
        cfg["cpu_burn_ms"] = max(0.0, min(t.cpu_burn_ms, 50.0))
    if t.concurrency is not None:
        cfg["concurrency"] = max(1, t.concurrency)
        app.state.sem = asyncio.Semaphore(cfg["concurrency"])
    return cfg
