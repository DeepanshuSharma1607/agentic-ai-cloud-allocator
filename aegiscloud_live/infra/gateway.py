"""
gateway.py - the front door of the real replicas (FastAPI, port 8001 = the old target app's port).

  GET  /work       the load sender's requests arrive here; the gateway forwards each one to the least busy READY replica
  GET  /snapshot   the same JSON the collector already reads from the old target app (requests, ok, errors, p50/p95/p99,
                   achieved_rps, app_cpu_pct, host_cpu_pct, app_mem_mb). Latency is measured HERE, end to end, so it is
                   correct across all replicas. app_cpu_pct / app_mem_mb are the real mean per replica.
                   Every call also appends one row to data/infra/cluster_ticks.csv (desired / ready / latency per tick).
  GET  /health

  control API used by the agent wrapper and the dashboard:
  POST /infra/scale {"n": 4}        GET /infra/state         GET /infra/events        GET /infra/resources
  GET|POST /infra/device            POST /infra/reload       POST /infra/calibrate    GET /infra/calibrate/status
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

import httpx
import numpy as np
import psutil
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from infra import config as C
from infra import device as D
from infra import runtime as R
from infra.backends import get_backend
from infra.manager import ClusterManager
from obs import log as obslog
from obs.middleware import QUIET_DEFAULT, RequestLogMiddleware
from ui.counter import mount as mount_counter

glog = obslog.setup("gateway")                  # shared logging: console + data/logs/gateway.jsonl


class Window:
    def __init__(self):
        self.started = time.perf_counter()
        self.arrivals = self.ok = self.errors = self.no_replica = 0
        self.lat: list[float] = []


@asynccontextmanager
async def lifespan(app):
    rt = R.load()
    dev = D.load_device()
    burn = rt.get("effective_burn_ms") or D.effective_burn_ms(dev, float(rt["tick_seconds"]))
    backend = get_backend(rt.get("backend", "docker"))
    app.state.mgr = ClusterManager(backend, dev, burn, min_replicas=int(rt.get("min_replicas") or 1),
                                  log=lambda m: glog.warning("cluster: %s", m))
    app.state.mgr.start()
    app.state.win = Window()
    app.state.tick = 0
    app.state.last_usage = {"mean_cpu_pct": 0.0, "mean_mem_mb": 0.0}
    app.state.carry = {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}
    app.state.client = httpx.AsyncClient(limits=httpx.Limits(max_connections=2000, max_keepalive_connections=400), timeout=10.0)
    app.state.cal = {"running": False, "message": "idle", "result": None}
    psutil.cpu_percent(interval=None)
    yield
    await app.state.client.aclose()
    app.state.mgr.shutdown()


app = FastAPI(title="AegisCloud gateway", lifespan=lifespan)
app.add_middleware(RequestLogMiddleware, name="gateway", hot=("/work",), quiet=QUIET_DEFAULT + ("/infra/scale",))   # replica changes are logged by the cluster manager
mount_counter(app, extra=lambda: {"replicas": app.state.mgr.counts()})   # APP 1: big-screen counter page at GET /


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/work")
async def work():
    st = app.state
    win, mgr = st.win, st.mgr
    win.arrivals += 1
    t0 = time.perf_counter()
    choice = mgr.pick()
    if choice is None:                                   # no Ready replica: this is a REAL failure (e.g. all still starting)
        win.errors += 1
        win.no_replica += 1
        return JSONResponse({"ok": False, "error": "no ready replica"}, status_code=503)
    name, url = choice
    try:
        r = await st.client.get(f"{url}/work")
        good = r.status_code == 200
    except Exception as e:
        good = False
        obslog.warn_every("gw-replica", 10, glog, "replica call failed (%s): %s: %s", name, type(e).__name__, e)
    finally:
        mgr.release(name)
    if good:
        win.ok += 1
        win.lat.append((time.perf_counter() - t0) * 1000.0)
        return {"ok": True}
    win.errors += 1
    return JSONResponse({"ok": False, "error": "replica refused or failed"}, status_code=503)


@app.get("/snapshot")
async def snapshot():
    st = app.state
    win, now = st.win, time.perf_counter()
    elapsed = max(now - win.started, 1e-6)
    lat = np.asarray(win.lat) if win.lat else None
    usage = st.mgr.usage()
    if usage:
        st.last_usage = usage
    u = st.last_usage
    c = st.mgr.counts()
    out = {"window_seconds": round(elapsed, 3), "requests": win.arrivals, "ok": win.ok, "errors": win.errors,
           "p50_ms": None if lat is None else float(np.percentile(lat, 50)),
           "p95_ms": None if lat is None else float(np.percentile(lat, 95)),
           "p99_ms": None if lat is None else float(np.percentile(lat, 99)),
           "achieved_rps": win.ok / elapsed,
           "app_cpu_pct": float(u["mean_cpu_pct"]), "host_cpu_pct": psutil.cpu_percent(interval=None),
           "app_mem_mb": float(u["mean_mem_mb"]), "queue_waiting": sum(st.mgr.inflight.values())}
    st.tick += 1
    C.append_csv(C.CLUSTER_TICKS_CSV, C.TICK_COLS, {
        "ts": round(time.time(), 2), "tick": st.tick, **c, "requests": win.arrivals, "ok": win.ok, "errors": win.errors,
        "p50_ms": "" if lat is None else round(out["p50_ms"], 1), "p95_ms": "" if lat is None else round(out["p95_ms"], 1),
        "p99_ms": "" if lat is None else round(out["p99_ms"], 1),
        "mean_cpu_pct": round(u["mean_cpu_pct"], 1), "mean_mem_mb": round(u["mean_mem_mb"], 1),
        "total_cpu_cores": round(usage["total_cpu_cores"], 2) if usage else "", "total_mem_mb": round(usage["total_mem_mb"], 1) if usage else "",
        "host_cpu_pct": round(out["host_cpu_pct"], 1), "inflight": out["queue_waiting"], "no_replica_errors": win.no_replica})
    st.win = Window()
    return out


class Tune(BaseModel):
    service_ms: float | None = None
    concurrency: int | None = None
    max_queue: int | None = None
    cpu_burn_ms: float | None = None


@app.post("/tune")
async def tune(t: Tune):
    """Forwarded to every ready replica (they are separate processes). New replicas start with the saved device settings."""
    body = {k: v for k, v in t.model_dump().items() if v is not None}
    done = 0
    for name, url in app.state.mgr.routable():
        try:
            await app.state.client.post(f"{url}/tune", json=body, timeout=3)
            done += 1
        except Exception:
            pass
    return {"forwarded_to": done, **body}


# ================================================================== control API
class Scale(BaseModel):
    n: int
    source: str = "agent"


@app.post("/infra/scale")
async def infra_scale(s: Scale):
    return app.state.mgr.set_desired(s.n, s.source)


@app.get("/infra/state")
async def infra_state():
    return app.state.mgr.snapshot()


def _tail(path, n):
    import json

    import pandas as pd
    try:
        df = pd.read_csv(path, on_bad_lines="skip").tail(n)
    except Exception:
        return []
    return json.loads(df.to_json(orient="records"))          # NaN becomes null (plain to_dict would send NaN, which is not valid JSON)


@app.get("/infra/events")
async def infra_events(tail: int = 50):
    return _tail(C.EVENTS_CSV, min(max(tail, 1), 500))


@app.get("/infra/resources")
async def infra_resources(tail: int = 300):
    return _tail(C.RESOURCES_CSV, min(max(tail, 1), 5000))


@app.get("/infra/device")
async def infra_device():
    dev = app.state.mgr.dev
    return {"device": dev.to_dict(), "limits": dev.limits(), "warnings": dev.warnings(), "burn_ms": app.state.mgr.burn_ms}


class Reload(BaseModel):
    burn_ms: float | None = None


@app.post("/infra/reload")
async def infra_reload(body: Reload | None = None):
    """Re-read data/infra/device_profile.json + runtime.json, remove all replicas and let the manager start new ones with the new limits."""
    dev = D.load_device()
    rt = R.load()
    burn = (body.burn_ms if body and body.burn_ms else None) or rt.get("effective_burn_ms") or D.effective_burn_ms(dev, float(rt["tick_seconds"]))
    await asyncio.to_thread(app.state.mgr.reset_replicas, dev, burn)
    return {"ok": True, "limits": dev.limits(), "burn_ms": burn}


@app.post("/infra/calibrate")
async def infra_calibrate():
    st = app.state
    if st.cal["running"]:
        return JSONResponse({"detail": "calibration already running"}, status_code=409)
    from infra import calibrate

    async def job():
        st.cal.update(running=True, message="starting", result=None)
        try:
            st.cal["result"] = await calibrate.run(st.mgr, lambda m: st.cal.__setitem__("message", m))
            st.cal["message"] = "done"
        except Exception as e:
            st.cal["message"] = f"failed: {type(e).__name__}: {e}"
        finally:
            st.cal["running"] = False

    asyncio.create_task(job())
    return {"started": True}


@app.get("/infra/calibrate/status")
async def infra_calibrate_status():
    return app.state.cal
