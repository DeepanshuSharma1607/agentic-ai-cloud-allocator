"""
server.py - the prediction service (FastAPI, port 8004).

  POST /tick     the collector sends every new metrics row here; we preprocess, run the LSTM, save to predictions.csv
  GET  /latest   the newest forecast row (the agent and the dashboard read this)
  GET  /status   ready?, history length, loaded models, input-drift warning
  POST /reload   re-read the models folder, seed and live CSV (after you copy a new .pt file in)

Run:  uvicorn prediction.server:app --port 8004
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

import settings as S
from prediction.engine import Engine
from prediction.predictor import Predictor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("prediction")


class Tick(BaseModel):
    model_config = ConfigDict(extra="allow")          # the collector also sends tick, wallclock, ok, errors ...
    minute: float
    requests: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    achieved_rps: float
    app_cpu_pct: float
    host_cpu_pct: float
    app_mem_mb: float


def build_engine():
    predictor = Predictor(S.MODELS_DIR)
    if not predictor.ready:
        log.warning("no .pt checkpoint found in %s - copy lstm_requests_forecaster.pt there (or run tools/make_demo_assets.py)", S.MODELS_DIR)
    return Engine(predictor)


@asynccontextmanager
async def lifespan(app):
    app.state.engine = build_engine()
    yield


app = FastAPI(title="AegisCloud prediction service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/status")
def status():
    return app.state.engine.status()


@app.post("/tick")
def tick(row: Tick):
    eng = app.state.engine
    try:
        pred = eng.ingest(row.model_dump())
    except Exception as e:
        eng.errors += 1
        log.exception("tick failed")
        raise HTTPException(status_code=422, detail=str(e))
    return {"predicted": pred is not None, "prediction": pred}


@app.get("/latest")
def latest():
    eng = app.state.engine
    return {"ready": eng.status()["ready"], "prediction": eng.last}


@app.post("/reload")
def reload():
    app.state.engine = build_engine()
    return app.state.engine.status()
