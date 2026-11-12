"""
process_backend.py - replicas are plain local processes: `python -m uvicorn infra.replica_app:app`.

Honest limits: there is NO CPU / memory isolation, the limits in the spec are not enforced (one replica may use a full core).
It is the fallback when Docker is not installed, the backend used by the automatic tests, and a possible backend for a very
small EC2 machine. CPU and memory numbers are still real (psutil, per process).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid

import httpx
import psutil

import settings as S
from infra.backends.base import Backend, Pod, Stat


def free_port() -> int:
    with socket.socket() as s:
        s.bind((S.HOST, 0))
        return s.getsockname()[1]


def replica_env(spec: dict) -> dict:
    """The environment variables that configure one replica (same names as settings.py reads)."""
    env = {"AEGIS_CPU_BURN_MS": str(spec.get("burn_ms", S.TARGET_CPU_BURN_MS)),
           "AEGIS_SERVICE_MS": str(spec.get("service_ms", S.TARGET_SERVICE_MS)),
           "AEGIS_CONCURRENCY": str(spec.get("concurrency", S.TARGET_CONCURRENCY)),
           "AEGIS_MAX_QUEUE": str(spec.get("max_queue", S.TARGET_MAX_QUEUE)),
           "AEGIS_TARGET_MEM_MB": str(spec.get("ballast_mb", S.TARGET_MEM_MB))}
    return env


class ProcessBackend(Backend):
    name = "process"
    per_pod_routing = True
    isolated = False

    def __init__(self):
        self.procs: dict[str, dict] = {}

    def observe(self) -> list[Pod]:
        pods = []
        for name, rec in list(self.procs.items()):
            proc, pod = rec["proc"], rec["pod"]
            if proc.poll() is not None:
                pod.state = "failed"
            elif pod.state == "starting":
                try:
                    if httpx.get(f"{pod.url}/health", timeout=0.4).status_code == 200:
                        pod.state, pod.ready_at = "ready", time.time()
                except Exception:
                    pass
            pods.append(pod)
        return pods

    def create(self, count, spec):
        names = []
        for _ in range(count):
            name = f"replica-{uuid.uuid4().hex[:6]}"
            port = free_port()
            env = dict(os.environ, **replica_env(spec), PYTHONPATH=str(S.ROOT), PYTHONUNBUFFERED="1")
            proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "infra.replica_app:app", "--host", S.HOST, "--port", str(port),
                                     "--log-level", "warning"], cwd=S.ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pod = Pod(name=name, url=f"http://{S.HOST}:{port}", cpu_limit_cores=None, mem_limit_mb=None)
            try:
                ps = psutil.Process(proc.pid)
                ps.cpu_percent(interval=None)                  # prime the counter, the next call returns a real number
            except psutil.Error:
                ps = None
            self.procs[name] = {"proc": proc, "pod": pod, "ps": ps}
            names.append(name)
        return names

    def remove(self, name):
        rec = self.procs.pop(name, None)
        if not rec:
            return
        proc = rec["proc"]
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()

    def stats(self):
        out = {}
        for name, rec in list(self.procs.items()):
            ps = rec["ps"]
            if ps is None or rec["pod"].state not in ("ready", "starting"):
                continue
            try:
                out[name] = Stat(cpu_pct=ps.cpu_percent(interval=None), mem_mb=ps.memory_info().rss / 1e6)
            except psutil.Error:
                continue
        return out

    def cleanup(self):
        for name in list(self.procs):
            self.remove(name)
