"""
docker_backend.py - every replica is a real Docker container with a CPU and a memory limit.

  create   `docker run` with nano_cpus (CPU share) and mem_limit, port published on 127.0.0.1 with a random host port
  observe  state of our containers (label aegiscloud=replica); a container is READY when its /health answers
  stats    real numbers from the Docker engine, read in parallel (one call per container)
  remove   stop + delete

Needs: Docker running, and `pip install docker`. The image is built from infra/docker/Dockerfile.replica on first use.
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx

import settings as S
from infra import config as C
from infra.backends.base import Backend, Pod, Stat
from infra.backends.process_backend import replica_env


def _parse_ts(text: str) -> float:
    try:
        text = text.rstrip("Z")
        head, _, frac = text.partition(".")
        return datetime.fromisoformat(f"{head}.{frac[:6]}" if frac else head).replace(tzinfo=None).timestamp()
    except Exception:
        return time.time()


class DockerBackend(Backend):
    name = "docker"
    per_pod_routing = True
    isolated = True

    def __init__(self):
        try:
            import docker
        except ImportError as e:
            raise RuntimeError("The 'docker' Python package is missing: pip install docker") from e
        self._docker = docker
        try:
            self.client = docker.from_env()
        except Exception as e:
            raise RuntimeError(f"Cannot create a Docker client: {e}") from e
        self.pods: dict[str, Pod] = {}
        self._prev: dict[str, tuple[float, float]] = {}      # name -> (cpu_total_ns, wall time) of the last sample
        self._pool = ThreadPoolExecutor(max_workers=8)

    # ------------------------------------------------------------------ setup
    def prepare(self, spec, build=True):
        try:
            self.client.ping()
        except Exception as e:
            raise RuntimeError("Docker is not running (or not reachable). Start Docker Desktop, or use --backend process.") from e
        try:
            self.client.images.get(C.IMAGE_NAME)
        except self._docker.errors.ImageNotFound:
            if not build:
                raise RuntimeError(f"Docker image {C.IMAGE_NAME} not found. Run run_live.py once (it builds the image).")
            print(f"Building the replica image {C.IMAGE_NAME} (first time only, about a minute) ...")
            self.client.images.build(path=str(S.ROOT), dockerfile="infra/docker/Dockerfile.replica", tag=C.IMAGE_NAME, rm=True)

    def _list(self):
        return self.client.containers.list(all=True, filters={"label": f"{C.LABEL}=replica"})

    # ------------------------------------------------------------------ observe / create / remove
    def observe(self):
        seen = set()
        for c in self._list():
            seen.add(c.name)
            pod = self.pods.get(c.name)
            if pod is None:
                pod = Pod(name=c.name, created_at=_parse_ts(c.attrs.get("Created", "")))
                self.pods[c.name] = pod
            spec = c.attrs.get("HostConfig", {})
            pod.cpu_limit_cores = (spec.get("NanoCpus") or 0) / 1e9 or None
            pod.mem_limit_mb = (spec.get("Memory") or 0) / 1e6 or None
            if pod.url is None:
                ports = (c.attrs.get("NetworkSettings", {}).get("Ports") or {}).get(f"{C.REPLICA_PORT}/tcp") or []
                if ports:
                    pod.url = f"http://{S.HOST}:{ports[0]['HostPort']}"
            if c.status in ("exited", "dead"):
                pod.state = "failed"
            elif c.status == "running" and pod.state == "starting" and pod.url:
                try:
                    if httpx.get(f"{pod.url}/health", timeout=0.4).status_code == 200:
                        pod.state, pod.ready_at = "ready", time.time()
                except Exception:
                    pass
        for name in list(self.pods):
            if name not in seen:
                self.pods.pop(name, None)
                self._prev.pop(name, None)
        return list(self.pods.values())

    def create(self, count, spec):
        names = []
        for _ in range(count):
            name = f"aegis-replica-{uuid.uuid4().hex[:6]}"
            c = self.client.containers.run(
                C.IMAGE_NAME, detach=True, name=name, labels={C.LABEL: "replica"},
                ports={f"{C.REPLICA_PORT}/tcp": (S.HOST, None)},
                nano_cpus=int(spec["cpu_cores"] * 1e9), mem_limit=f"{int(spec['mem_mb'])}m", memswap_limit=f"{int(spec['mem_mb'])}m",
                environment=replica_env(spec), restart_policy={"Name": "no"})
            self.pods[name] = Pod(name=name, cpu_limit_cores=spec["cpu_cores"], mem_limit_mb=spec["mem_mb"])
            for _ in range(20):                                   # the host port is known a moment after start
                c.reload()
                ports = (c.attrs.get("NetworkSettings", {}).get("Ports") or {}).get(f"{C.REPLICA_PORT}/tcp") or []
                if ports:
                    self.pods[name].url = f"http://{S.HOST}:{ports[0]['HostPort']}"
                    break
                time.sleep(0.1)
            names.append(name)
        return names

    def remove(self, name):
        try:
            c = self.client.containers.get(name)
            try:
                c.stop(timeout=3)
            except Exception:
                pass
            c.remove(force=True)
        except self._docker.errors.NotFound:
            pass
        self.pods.pop(name, None)
        self._prev.pop(name, None)

    # ------------------------------------------------------------------ stats
    def _one(self, name):
        try:
            raw = self.client.containers.get(name).stats(stream=False, one_shot=True)
        except Exception:
            return name, None
        now = time.time()
        total = (raw.get("cpu_stats", {}).get("cpu_usage", {}) or {}).get("total_usage")
        mem = raw.get("memory_stats", {}) or {}
        used = mem.get("usage")
        if total is None or used is None:
            return name, None
        st = mem.get("stats", {}) or {}
        used -= st.get("inactive_file", st.get("total_inactive_file", 0))     # page cache is not the app's memory
        prev = self._prev.get(name)
        self._prev[name] = (float(total), now)
        if prev is None or now - prev[1] < 0.2:
            return name, None                                                 # no delta yet: say nothing rather than guess
        cpu = (float(total) - prev[0]) / 1e9 / (now - prev[1]) * 100.0
        return name, Stat(cpu_pct=max(cpu, 0.0), mem_mb=max(used, 0) / 1e6, mem_limit_mb=(mem.get("limit") or 0) / 1e6 or None)

    def stats(self):
        names = [p.name for p in self.pods.values() if p.state in ("ready", "starting")]
        return {n: s for n, s in self._pool.map(self._one, names) if s is not None}

    def cleanup(self):
        for c in self._list():
            try:
                c.remove(force=True)
            except Exception:
                pass
        self.pods.clear()
