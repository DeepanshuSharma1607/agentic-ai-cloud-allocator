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
    try:
        requests.post(f"{C.URL_GATEWAY}/infra/scale", json={"n": int(n), "source": "agent"}, timeout=3)
    except Exception as e:
        if time.time() - _last_warn[0] > 30:                      # the agent must never crash because the cluster is slow
            print(f"WARNING: could not reach the gateway to scale to {n}: {e}")
            logging.getLogger("agent").warning("could not reach the gateway to scale to %s: %s", n, e)
            _last_warn[0] = time.time()


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
    from agent import nodes
    nodes.set_replicas = real_set_replicas
    from agent import run
    return run.main()


if __name__ == "__main__":
    sys.exit(main())
