"""
agent_real.py - starts YOUR agent (agent/run.py, unchanged) with two things connected to the real cluster:

  1. nodes.set_replicas(n)  - the placeholder in agent/nodes.py - is replaced by a call to the gateway, which starts / drains
                              real containers or Pods
  2. capacity per replica and the max replica count come from the device profile + calibration (data/infra/runtime.json)
                              instead of "mean traffic / 5"

    python -m infra.agent_real --quiet --no-metrics            # same options as  python -m agent.run
"""
import logging
import sys
import time

import requests

from infra import config as C
from infra import runtime as R

_last_warn = [0.0]


def real_set_replicas(n):
    last_error = None
    for attempt in range(3):                                      # a stalled gateway used to drop the command silently: retry with a longer timeout
        try:
            r = requests.post(f"{C.URL_GATEWAY}/infra/scale", json={"n": int(n), "source": "agent"}, timeout=6)
            r.raise_for_status()                                  # a 404 / 500 used to look like success
            answer = r.json()
            if answer.get("clamped") and time.time() - _last_warn[0] > 30:
                logging.getLogger("agent").warning("scale to %s was clamped to %s by the device limit", n, answer.get("desired"))
                _last_warn[0] = time.time()
            return True
        except Exception as e:                                    # the agent must never crash because the cluster is slow
            last_error = e
            time.sleep(0.5 * (attempt + 1))
    if time.time() - _last_warn[0] > 30:
        print(f"WARNING: could not reach the gateway to scale to {n} after 3 tries: {last_error}")
        logging.getLogger("agent").warning("could not reach the gateway to scale to %s after 3 tries: %s", n, last_error)
        _last_warn[0] = time.time()
    return False


def _warn_if_capacity_is_stale(rt):
    """A calibration was measured but runtime.json was never re-applied: the agent would size replicas with the old estimate."""
    try:
        cal = C.read_json(C.CALIBRATION_JSON)
        if not cal or rt.get("capacity_source") == "calibrated" or not rt.get("capacity_per_tick"):
            return
        from infra import device as D
        measured = float(cal["rps_per_replica"]) * float(rt["tick_seconds"]) * D.load_device().target_util
        used = float(rt["capacity_per_tick"])
        if abs(used - measured) / max(used, 1.0) > 0.25:
            msg = (f"the agent is using an ESTIMATED capacity of {used:.0f}/tick per replica, but a calibration measured about "
                   f"{measured:.0f}/tick. Open Device & Timer and press Apply so the agent uses the measured number.")
            print("WARNING:", msg)
            logging.getLogger("agent").warning(msg)
    except Exception:
        pass                                                      # a warning must never stop the agent


def main():
    from agent import config as cfg
    rt = R.load()
    if rt.get("capacity_per_tick"):
        cfg.CAPACITY_PER_REPLICA = float(rt["capacity_per_tick"])
    if rt.get("max_replicas"):
        cfg.MAX_REPLICAS = int(rt["max_replicas"])
    cfg.MIN_REPLICAS = int(rt.get("min_replicas") or 1)
    print(f"[real replicas] backend {rt['backend']} | tick {rt['tick_seconds']} s | capacity {cfg.CAPACITY_PER_REPLICA}/tick per replica "
          f"({rt.get('capacity_source')}) | max replicas {cfg.MAX_REPLICAS}")
    _warn_if_capacity_is_stale(rt)
    from agent import nodes
    nodes.set_replicas = real_set_replicas
    from agent import run
    return run.main()


if __name__ == "__main__":
    sys.exit(main())
