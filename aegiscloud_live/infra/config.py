"""
config.py - paths, ports and small helpers shared by everything in infra/.

No logic except tiny file helpers. Paths follow settings.py, so the tests (which set AEGIS_DATA_DIR) stay isolated.
"""
import csv
import json
import os
import threading
from pathlib import Path

import settings as S

INFRA_DIR = S.DATA_DIR / "infra"
DEVICE_JSON = INFRA_DIR / "device_profile.json"        # what the user typed on the "Device & Timer" tab
RUNTIME_JSON = INFRA_DIR / "runtime.json"              # values every part must agree on (tick length, capacity, backend)
CALIBRATION_JSON = INFRA_DIR / "calibration.json"      # measured capacity of one real replica
RESOURCES_CSV = INFRA_DIR / "resources.csv"            # per-replica CPU / memory samples (real, from the backend)
EVENTS_CSV = INFRA_DIR / "replica_events.csv"          # every create / ready / drain / remove, with startup seconds
CLUSTER_TICKS_CSV = INFRA_DIR / "cluster_ticks.csv"    # one row per collector tick: desired / ready / starting, real latency

PORT_SUPERVISOR = int(os.getenv("AEGIS_PORT_SUPERVISOR", "8005"))
URL_SUPERVISOR = f"http://{S.HOST}:{PORT_SUPERVISOR}"
URL_GATEWAY = S.URL_TARGET                             # the gateway takes the place of the demo target app (same port)

IMAGE_NAME = "aegiscloud-replica:latest"
REPLICA_PORT = 8001                                    # port the app listens on INSIDE a container / Pod
LABEL = "aegiscloud"                                   # label on every container / Pod we create, so we only ever touch our own

_lock = threading.Lock()


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return default


def write_json(path: Path, data):
    """Atomic write: a reader never sees half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def append_csv(path: Path, cols, row: dict):
    path = Path(path)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists() or path.stat().st_size == 0
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)


RESOURCE_COLS = ["ts", "replica", "state", "cpu_pct", "mem_mb", "mem_limit_mb", "cpu_limit_cores"]
EVENT_COLS = ["ts", "event", "replica", "startup_s", "desired", "ready", "detail"]
TICK_COLS = ["ts", "tick", "desired", "ready", "starting", "draining", "requests", "ok", "errors", "p50_ms", "p95_ms", "p99_ms",
             "mean_cpu_pct", "mean_mem_mb", "total_cpu_cores", "total_mem_mb", "host_cpu_pct", "inflight", "no_replica_errors"]
