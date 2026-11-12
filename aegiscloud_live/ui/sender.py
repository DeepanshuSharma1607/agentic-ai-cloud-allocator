"""
sender.py - APP 2 logic: the simple page for the request sender (ui/sender.html) and its one-click demo.

ROLE
    The "crowd of customers". The sender's only job is to send a number of requests to the counter app (port 8001).
    This page lets anyone do that with a number box and Start / Stop - no command line, no technical knowledge.
        http://localhost:8002           the page
        POST /demo, GET /demo/status    the one-click demo (quiet -> spike -> quiet)

HOW IT WORKS
    - The page uses the sender's EXISTING endpoints (/start, /stop, /schedule, /status). Nothing about sending changed.
    - The demo uses the sender's own scheduler: it stops other traffic, then queues three back-to-back segments:
          quiet  (6 ticks)  ->  SPIKE  (18 ticks)  ->  quiet again  (12 ticks)
      The sizes follow the machine: quiet = 30% of one replica's capacity, spike = 1.6x of it (so the agent has a reason
      to add replicas), but never above 150 requests per second and never above the safety limit MAX_REQUESTS_PER_TICK.
      (A bigger spike only floods this PC: the sender, the front door and the replicas share the same CPU.)
      Without calibration it assumes 150/tick.

REMEMBER
    - The demo TAKES OVER: it cancels whatever was being sent. Stop cancels the demo too.
    - Durations are counted in ticks, so they stretch or shrink with the tick length (default 5 s).

TEST    python -m pytest tests/test_part2.py -q
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import settings as S

log = logging.getLogger("loadgen")
DEFAULT_CAPACITY = 150.0
SPIKE_FACTOR = 1.6                  # spike = 1.6x one replica's capacity: enough to make the agent add a replica
MAX_DEMO_PER_SECOND = 150           # ...but never more than a normal PC can send AND receive (see PART_2_1_REPORT.md)


def demo_sizes() -> tuple[int, int]:
    """(quiet, spike) requests per tick, from the calibrated capacity when it exists."""
    cap = None
    try:
        from infra import runtime as R
        cap = R.load().get("capacity_per_tick")
    except Exception:
        pass
    cap = float(cap) if cap else DEFAULT_CAPACITY
    spike = min(round(cap * SPIKE_FACTOR), round(MAX_DEMO_PER_SECOND * S.TICK_SECONDS), S.MAX_REQUESTS_PER_TICK)
    quiet = min(max(10, round(cap * 0.3)), spike)
    return int(quiet), int(spike)


def demo_phases(tick_seconds: float) -> list[tuple[str, int, float]]:
    quiet, spike = demo_sizes()
    return [("Quiet", quiet, 6 * tick_seconds), ("Spike", spike, 18 * tick_seconds), ("Quiet again", quiet, 12 * tick_seconds)]


def demo_status(app) -> dict:
    demo = getattr(app.state, "demo", None)
    if not demo:
        return {"running": False}
    elapsed = time.time() - demo["started"]
    running = elapsed < demo["total_s"] and bool(app.state.engine.segments)
    current = next((p["name"] for p in demo["phases"] if p["start_s"] <= elapsed < p["start_s"] + p["duration_s"]), None)
    return {"running": running, "elapsed_s": round(min(elapsed, demo["total_s"]), 1), "total_s": round(demo["total_s"], 1),
            "current": current if running else None, "phases": demo["phases"]}


def mount(app) -> None:
    """Add GET /, POST /demo and GET /demo/status to the sender's FastAPI app."""
    page = Path(__file__).with_name("sender.html")
    # read-only sharing: the counter page may READ /status (GET only) to show what the sender is doing
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=[])

    @app.get("/", response_class=HTMLResponse)
    def sender_page():
        return page.read_text(encoding="utf-8")

    @app.post("/demo")
    def start_demo(request: Request):
        eng = request.app.state.engine
        eng.stop(cancel_schedule=True)                           # the demo takes over
        t0 = t = time.time()
        phases = []
        for name, n, dur in demo_phases(S.TICK_SECONDS):
            eng.add_segment({"mode": "fixed", "n": n}, dur, t)
            phases.append({"name": name, "n": n, "start_s": round(t - t0, 2), "duration_s": round(dur, 2)})
            t += dur
        request.app.state.demo = {"started": t0, "phases": phases, "total_s": t - t0}
        log.info("demo started: %s", ", ".join(f"{p['name']} {p['n']}/tick for {p['duration_s']:.0f}s" for p in phases))
        return demo_status(request.app)

    @app.get("/demo/status")
    def demo_state(request: Request):
        return demo_status(request.app)
