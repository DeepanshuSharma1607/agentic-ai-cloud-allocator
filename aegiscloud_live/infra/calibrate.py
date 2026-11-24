"""
calibrate.py - measure how many requests per second ONE real replica can take.

It starts one extra replica (separate from the pool), sends it a ladder of constant request rates for a few seconds each, and
keeps the highest rate where p95 latency stays under the SLO and fewer than 1% of requests fail. The result is saved in
data/infra/calibration.json together with the settings it was measured with. The agent's "capacity per replica" then comes from
this measurement instead of a guess.

Stop the traffic sender first: calibration needs the CPU to itself.
"""
from __future__ import annotations

import asyncio
import time

import httpx
import numpy as np

from infra import config as C
from infra import device as D

STEP_SECONDS = 6.0
READY_TIMEOUT = 60.0
LADDER = (0.3, 0.5, 0.7, 0.85, 1.0, 1.2, 1.5)      # fractions of the estimated capacity
EXTRA = (1.9, 2.5, 3.2, 4.0, 5.0)                  # only used while every step above still passes (the estimate was too low)


async def _step(client, url, rps, seconds):
    lat, errors, sent = [], 0, 0
    tasks = []

    async def one():
        nonlocal errors
        t0 = time.perf_counter()
        try:
            r = await client.get(f"{url}/work")
            if r.status_code == 200:
                lat.append((time.perf_counter() - t0) * 1000.0)
            else:
                errors += 1
        except Exception:
            errors += 1

    start = time.perf_counter()
    while (now := time.perf_counter() - start) < seconds:
        due = int(now * rps) + 1
        while sent < due:
            tasks.append(asyncio.create_task(one()))
            sent += 1
        await asyncio.sleep(0.01)
    await asyncio.gather(*tasks, return_exceptions=True)
    arr = np.asarray(lat) if lat else None
    return {"rps": round(rps, 2), "sent": sent, "errors": errors, "p50_ms": None if arr is None else float(np.percentile(arr, 50)),
            "p95_ms": None if arr is None else float(np.percentile(arr, 95))}


async def run(mgr, say=print) -> dict:
    dev, burn, backend = mgr.dev, mgr.burn_ms, mgr.backend
    if not backend.per_pod_routing:
        raise RuntimeError("calibration needs a backend with direct replica URLs (docker or process); for Kubernetes calibrate with the docker backend first")
    est = D.estimate_rps_per_replica(dev, burn)
    say("starting one test replica ...")
    def make():
        with mgr._io:                                    # blocks only reconcile (a background thread), never the gateway's request path
            n = backend.create(1, mgr.spec())[0]
            with mgr.lock:                               # hidden from the manager so it is not drained as "extra" (microseconds)
                mgr.exclude.add(n)
            return n
    name = await asyncio.to_thread(make)
    try:
        url, end = None, time.time() + READY_TIMEOUT
        while time.time() < end:
            pod = next((p for p in await asyncio.to_thread(backend.observe) if p.name == name), None)
            if pod and pod.state == "ready":
                url = pod.url
                break
            await asyncio.sleep(0.3)
        if not url:
            raise RuntimeError("the test replica did not become ready")
        steps, best = [], 0.0
        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=1000), timeout=10.0) as client:
            await _step(client, url, max(est * 0.2, 1.0), 2.0)                    # warm-up, result ignored
            for frac in LADDER + EXTRA:
                if frac in EXTRA and not (steps and steps[-1]["ok"]):
                    break
                rps = est * frac
                say(f"load step {len(steps) + 1}: {rps:.1f} requests/s")
                res = await _step(client, url, rps, STEP_SECONDS)
                res["ok"] = bool(res["p95_ms"] is not None and res["p95_ms"] <= dev.slo_p95_ms and res["errors"] <= 0.01 * max(res["sent"], 1))
                steps.append(res)
                if res["ok"]:
                    best = rps
                elif frac > 1.0:
                    break
        out = {"rps_per_replica": round(best, 2), "estimated_rps": round(est, 2), "slo_p95_ms": dev.slo_p95_ms, "burn_ms": burn,
               "cpu_per_replica": dev.cpu_per_replica, "mem_per_replica_mb": dev.mem_per_replica_mb, "backend": backend.name,
               "isolated": backend.isolated, "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": steps}
        if best <= 0:
            raise RuntimeError("no load step met the latency goal; check the SLO / app weight")
        C.write_json(C.CALIBRATION_JSON, out)
        return out
    finally:
        await asyncio.to_thread(backend.remove, name)
        mgr.exclude.discard(name)
