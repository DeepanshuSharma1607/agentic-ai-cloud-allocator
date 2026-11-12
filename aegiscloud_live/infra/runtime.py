"""
runtime.py - the small file every part reads to agree on the "live" settings.

data/infra/runtime.json holds: tick_seconds (real seconds per simulated minute), backend, effective_burn_ms (how heavy one
request is), capacity_per_tick (requests one replica handles per tick), max_replicas. The supervisor (run_live.py) writes it,
the dashboard and the agent wrapper read it. If the file does not exist, the old defaults from settings.py are used.
"""
import settings as S
from infra import config as C

DEFAULTS = {"tick_seconds": None, "backend": "docker", "effective_burn_ms": 20.0, "capacity_per_tick": None,
            "capacity_source": "none", "max_replicas": None, "min_replicas": 1}


def load():
    data = dict(DEFAULTS)
    data.update(C.read_json(C.RUNTIME_JSON, {}) or {})
    if not data.get("tick_seconds"):
        data["tick_seconds"] = S.TICK_SECONDS
    return data


def save(**changes):
    data = load()
    data.update({k: v for k, v in changes.items() if v is not None})
    C.write_json(C.RUNTIME_JSON, data)
    return data


def tick_seconds():
    return float(load()["tick_seconds"])


def apply_settings(dev, tick_seconds, backend):
    """Work out and store everything the other parts must agree on, from the device profile + tick length.
    Returns the runtime dict. Used by run_live.py at start and when the dashboard presses Apply."""
    from infra import device as D
    cal = C.read_json(C.CALIBRATION_JSON)
    burn = D.effective_burn_ms(dev, tick_seconds)
    cap, source = D.capacity_per_tick(dev, tick_seconds, burn, cal)
    lim = dev.limits()
    return save(tick_seconds=float(tick_seconds), backend=backend, effective_burn_ms=round(burn, 2), capacity_per_tick=round(cap, 1),
                capacity_source=source, max_replicas=lim["max_replicas"], min_replicas=1)
