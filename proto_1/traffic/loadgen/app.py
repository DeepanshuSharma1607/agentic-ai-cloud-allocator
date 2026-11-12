"""
loadgen/app.py - control API of the request sender (FastAPI, port 8002). The dashboard and cli.py talk to this.

  GET    /status
  POST   /start          {"mode": "fixed", "n": 300}               set the base plan
  POST   /stop           {"cancel_schedule": true}
  POST   /schedule       {"plan": {...}, "in_seconds": 120, "duration_s": 300}      or "start_at": "2026-10-30T14:30:00"
  DELETE /schedule/{id}
"""
import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import settings as S
from traffic.loadgen.engine import LoadEngine


class Plan(BaseModel):
    mode: Literal["idle", "fixed", "random", "pattern", "replay"] = "fixed"
    n: int = Field(100, ge=0)
    lo: int = Field(50, ge=0)
    hi: int = Field(200, ge=0)
    smooth: float = Field(0.0, ge=0, le=0.95)
    scale: float = Field(1.0, gt=0, le=20)
    noise: float = Field(0.25, ge=0, le=2)
    burst_prob: float = Field(0.01, ge=0, le=1)
    burst_mult: float = Field(3.0, ge=1, le=20)
    start: int = Field(0, ge=0)


class StopBody(BaseModel):
    cancel_schedule: bool = True


class ScheduleBody(BaseModel):
    plan: Plan
    duration_s: float = Field(gt=0, le=86400)
    in_seconds: float | None = Field(None, ge=0)
    start_at: str | None = None


@asynccontextmanager
async def lifespan(app):
    app.state.engine = LoadEngine()
    task = asyncio.create_task(app.state.engine.run())
    yield
    task.cancel()


app = FastAPI(title="AegisCloud request sender", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/status")
def status():
    return app.state.engine.status()


@app.post("/start")
def start(plan: Plan):
    app.state.engine.set_base(plan.model_dump())
    return app.state.engine.status()


@app.post("/stop")
def stop(body: StopBody = StopBody()):
    app.state.engine.stop(body.cancel_schedule)
    return app.state.engine.status()


@app.post("/schedule")
def schedule(body: ScheduleBody):
    if body.start_at:
        try:
            start_ts = datetime.fromisoformat(body.start_at).timestamp()
        except ValueError:
            raise HTTPException(422, "start_at must look like 2026-10-30T14:30:00")
        if start_ts < time.time() - 1:
            raise HTTPException(422, "start_at is in the past")
    else:
        start_ts = time.time() + (body.in_seconds or 0.0)
    seg = app.state.engine.add_segment(body.plan.model_dump(), body.duration_s, start_ts)
    return {"id": seg["id"], "starts_in_s": round(start_ts - time.time(), 1)}


@app.delete("/schedule/{seg_id}")
def cancel(seg_id: int):
    if not app.state.engine.cancel_segment(seg_id):
        raise HTTPException(404, "no such scheduled segment")
    return {"cancelled": seg_id}
