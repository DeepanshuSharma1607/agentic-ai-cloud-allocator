"""
settings.py - the one place for paths, ports and timing shared by all five parts.

Every value can be overridden with an environment variable (AEGIS_...), which the tests use.
No logic here, only constants.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _env(name, default, cast=str):
    raw = os.getenv(name)
    return default if raw in (None, "") else cast(raw)


# ------------------------------------------------------------------ folders and files
DATA_DIR = Path(_env("AEGIS_DATA_DIR", ROOT / "data", Path))
MODELS_DIR = Path(_env("AEGIS_MODELS_DIR", ROOT / "prediction" / "models", Path))

SEED_CSV = DATA_DIR / "seed" / "metrics_combined.csv"          # your training data (history for warm-up)
LIVE_CSV = DATA_DIR / "live" / "live_metrics.csv"              # one row per tick, written by the collector
PRED_CSV = DATA_DIR / "predictions" / "predictions.csv"        # one row per tick, written by the prediction service
AGENT_DIR = DATA_DIR / "agent"                                 # agent_ticks.csv, actions.csv, alerts/
LOADGEN_DIR = DATA_DIR / "loadgen"                             # load_ticks.csv, events.csv
LOG_DIR = DATA_DIR / "logs"

# ------------------------------------------------------------------ time
TICK_SECONDS = _env("AEGIS_TICK_SECONDS", 5.0, float)          # 1 tick = 5 real seconds = 1 simulated minute (as in training)
DAY = 1440                                                     # ticks per simulated day (same as the notebook)
W = 60                                                         # LSTM window (same as the notebook)
HORIZONS = [10, 20]                                            # forecasts in simulated minutes ahead; one checkpoint per horizon

# ------------------------------------------------------------------ the 8 model inputs (order matters; same as the notebook)
METRIC_COLS = ["requests", "p50_ms", "p95_ms", "p99_ms", "achieved_rps", "app_cpu_pct", "host_cpu_pct", "app_mem_mb"]
TARGET_COL = "requests"
LIVE_COLS = ["tick", "minute", "wallclock", "load_mode", "planned", "ok", "errors"] + METRIC_COLS

# ------------------------------------------------------------------ services
HOST = "127.0.0.1"
PORT_TARGET = _env("AEGIS_PORT_TARGET", 8001, int)
PORT_LOADGEN = _env("AEGIS_PORT_LOADGEN", 8002, int)
PORT_COLLECTOR = _env("AEGIS_PORT_COLLECTOR", 8003, int)
PORT_PREDICTION = _env("AEGIS_PORT_PREDICTION", 8004, int)
PORT_FRONTEND = _env("AEGIS_PORT_FRONTEND", 8501, int)

URL_TARGET = f"http://{HOST}:{PORT_TARGET}"
URL_LOADGEN = f"http://{HOST}:{PORT_LOADGEN}"
URL_COLLECTOR = f"http://{HOST}:{PORT_COLLECTOR}"
URL_PREDICTION = f"http://{HOST}:{PORT_PREDICTION}"

# ------------------------------------------------------------------ safety limits for the load generator
MAX_REQUESTS_PER_TICK = _env("AEGIS_MAX_PER_TICK", 3000, int)  # hard cap, whatever the dashboard asks for
LOADGEN_AUTOSTART = _env("AEGIS_LOADGEN_AUTOSTART", "pattern")  # "pattern" = start daily-pattern traffic at launch (the default), "off" = start idle. NOTE: an empty value ("") means "not set", so it gives the default

# ------------------------------------------------------------------ demo target app (the "app" that receives the traffic)
TARGET_SERVICE_MS = _env("AEGIS_SERVICE_MS", 30.0, float)       # average time one request takes
TARGET_CONCURRENCY = _env("AEGIS_CONCURRENCY", 16, int)         # requests served at the same time
TARGET_MAX_QUEUE = _env("AEGIS_MAX_QUEUE", 400, int)            # waiting requests beyond this get HTTP 503
TARGET_CPU_BURN_MS = _env("AEGIS_CPU_BURN_MS", 2.0, float)      # CPU time burned per request (gives app_cpu_pct something real to measure)
TARGET_MEM_MB = _env("AEGIS_TARGET_MEM_MB", 103.0, float)    # the demo app holds about this much memory (training data: ~103 MB, almost constant)
