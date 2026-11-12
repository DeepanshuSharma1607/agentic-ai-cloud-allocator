"""
base.py - what every scaling backend must do. The manager only talks to this interface.

  process   replicas are local Python processes (no isolation, no limits): tests and machines without Docker
  docker    replicas are real containers with a CPU and memory limit
  k8s       replicas are Pods of a Deployment (kubectl / k3d / Docker Desktop Kubernetes)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Pod:
    name: str
    state: str = "starting"            # starting | ready | terminating | failed
    url: str | None = None             # where the gateway sends requests (None = use the backend's service_url)
    created_at: float = field(default_factory=time.time)
    ready_at: float | None = None
    cpu_limit_cores: float | None = None
    mem_limit_mb: float | None = None


@dataclass
class Stat:
    cpu_pct: float                     # % of ONE core (150 = one and a half cores busy), the same unit for every backend
    mem_mb: float
    mem_limit_mb: float | None = None


class Backend:
    name = "base"
    per_pod_routing = True             # True: the gateway balances over pod urls; False: one service_url does the balancing
    service_url: str | None = None
    isolated = False                   # True if CPU / memory limits are really enforced

    def prepare(self, spec: dict):
        """Check that the backend is usable (Docker running, image built ...). Raise RuntimeError with a clear text if not."""

    def observe(self) -> list[Pod]:
        raise NotImplementedError

    def create(self, count: int, spec: dict) -> list[str]:
        """Start `count` new replicas (non-blocking). Returns their names."""
        raise NotImplementedError

    def remove(self, name: str):
        raise NotImplementedError

    def scale_to(self, n: int, spec: dict):
        """Only for backends where per_pod_routing is False (Kubernetes): set the desired count."""
        raise NotImplementedError

    def stats(self) -> dict[str, Stat]:
        return {}

    def cleanup(self):
        """Remove every replica this backend created."""
