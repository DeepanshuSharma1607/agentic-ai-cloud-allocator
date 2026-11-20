"""
manager.py - the ClusterManager: keeps the REAL number of replicas equal to the number the agent asked for.

  set_desired(n)   called by the agent (through the gateway). Clamped to the device limit. Returns at once.
  reconcile loop   every 0.5 s: look at what the backend really has, start missing replicas, drain extra ones,
                   notice replicas that became Ready (this is where the real startup time is measured) or failed.
  sampler loop     every SAMPLE_S: read real CPU / memory of each replica from the backend and write resources.csv.

Scale-down is graceful: a replica is first marked "draining" (the gateway stops sending it new requests), and is removed
when its requests are finished (or after DRAIN_TIMEOUT seconds).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

import psutil

from obs import log as obslog

clog = logging.getLogger("cluster")

from infra import config as C
from infra.backends.base import Backend
from infra.device import Device

RECONCILE_S = 0.5
SAMPLE_S = 2.0
START_TIMEOUT_S = 90.0         # a replica that is not Ready after this long is counted as failed and replaced
DRAIN_TIMEOUT_S = 5.0


class ClusterManager:
    def __init__(self, backend: Backend, dev: Device, burn_ms: float, min_replicas: int = 1, log=print):
        self.backend, self.dev, self.burn_ms, self.min_replicas = backend, dev, float(burn_ms), int(min_replicas)
        self.log = log
        self.lock = threading.RLock()                # protects the bookkeeping; held only for microseconds (the gateway needs it for every request)
        self._io = threading.RLock()                 # serialises the SLOW backend work (create / remove containers) between reconcile and reset
        self.desired = self.min_replicas
        self.pods: dict = {}
        self.draining: dict[str, float] = {}
        self.inflight: dict[str, int] = {}
        self.latest: dict = {}                       # replica -> (Stat, time)
        self.events = deque(maxlen=300)
        self.startup_times: list[float] = []
        self._seen: dict[str, str] = {}
        self._rr = 0
        self._k8s_target = None
        self._last_clamp = None
        self.exclude: set[str] = set()               # replicas that belong to a calibration run, not to the pool
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.last_error = ""
        psutil.cpu_percent(interval=None)

    # ------------------------------------------------------------------ spec
    def spec(self) -> dict:
        return {"cpu_cores": self.dev.cpu_per_replica, "mem_mb": self.dev.mem_per_replica_mb, "burn_ms": self.burn_ms,
                "max_replicas": self.dev.limits()["max_replicas"]}

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        self.backend.prepare(self.spec(), build=False) if self.backend.name != "process" else None
        self._stop.clear()
        for target in (self._reconcile_loop, self._sampler_loop):
            t = threading.Thread(target=target, daemon=True, name=target.__name__)
            t.start()
            self._threads.append(t)

    def shutdown(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=3)
        try:
            self.backend.cleanup()
        except Exception as e:
            self.log(f"cleanup problem: {e}")

    # ------------------------------------------------------------------ events
    def _event(self, kind, replica="", startup_s=None, detail=""):
        ready = sum(1 for p in self.pods.values() if p.state == "ready")
        row = {"ts": round(time.time(), 2), "event": kind, "replica": replica,
               "startup_s": "" if startup_s is None else round(startup_s, 2), "desired": self.desired, "ready": ready, "detail": detail}
        self.events.append(row)
        C.append_csv(C.EVENTS_CSV, C.EVENT_COLS, row)
        clog.log(logging.WARNING if kind in ("failed", "clamped") else logging.INFO,
                 "replica event: %s %s (desired %s, ready %s) %s", kind, replica, self.desired, ready, detail)

    # ------------------------------------------------------------------ the agent's entry point
    def set_desired(self, n: int, source: str = "agent") -> dict:
        n = int(n)
        with self.lock:
            limit = self.dev.limits()["max_replicas"]
            target = max(self.min_replicas, min(limit, n))
            clamped = target != n
            if clamped and self._last_clamp != (n, limit):
                self._event("clamped", detail=f"{source} asked {n}, device limit is {limit} ({self.dev.limits()['binding']})")
            self._last_clamp = (n, limit) if clamped else None
            if target != self.desired:
                self._event("desired", detail=f"{self.desired} -> {target} ({source})")
            self.desired = target
            return {"desired": target, "requested": n, "clamped": clamped, "max_replicas": limit}

    # ------------------------------------------------------------------ routing helpers (used by the gateway)
    def routable(self):
        """[(name, url)] of replicas that are Ready and not draining."""
        with self.lock:
            if not self.backend.per_pod_routing:
                ok = any(p.state == "ready" for p in self.pods.values())
                return [("service", self.backend.service_url)] if ok else []
            return [(p.name, p.url) for p in self.pods.values() if p.state == "ready" and p.url and p.name not in self.draining]

    def pick(self):
        """Least busy routable replica (ties go round-robin). None if there is none."""
        r = self.routable()
        if not r:
            return None
        with self.lock:
            low = min(self.inflight.get(n, 0) for n, _ in r)
            best = [x for x in r if self.inflight.get(x[0], 0) == low]
            self._rr += 1
            choice = best[self._rr % len(best)]
            self.inflight[choice[0]] = self.inflight.get(choice[0], 0) + 1
            return choice

    def release(self, name):
        with self.lock:
            self.inflight[name] = max(0, self.inflight.get(name, 0) - 1)

    # ------------------------------------------------------------------ reconcile
    def _reconcile_loop(self):
        while not self._stop.is_set():
            try:
                self.reconcile()
                self.last_error = ""
            except Exception as e:                                   # never let the loop die
                self.last_error = f"{type(e).__name__}: {e}"
                obslog.warn_every("mgr-reconcile", 15, clog, "reconcile loop error: %s", self.last_error)
            self._stop.wait(RECONCILE_S)

    def reconcile(self):
        """Bring the real containers in line with `desired`.
        Bookkeeping happens under self.lock (fast). The SLOW calls (Docker create / stop / remove, which take seconds) are
        collected first and run AFTER the lock is released: before, every scale-up/-down froze request routing for seconds."""
        with self._io:
            now = time.time()
            pods = self.backend.observe()
            kill: list[tuple[str, bool]] = []          # (replica name, True = a finished drain that needs its bookkeeping closed)
            create_n, k8s_target = 0, None
            with self.lock:
                pods = [p for p in pods if p.name not in self.exclude]
                self.pods = {p.name: p for p in pods}
                for p in pods:
                    prev = self._seen.get(p.name)
                    if p.state == "ready" and prev != "ready":
                        startup = (p.ready_at or now) - p.created_at
                        self.startup_times.append(startup)
                        self._event("ready", p.name, startup_s=startup)
                    if p.state == "failed" and prev != "failed":
                        self._event("failed", p.name, detail="process / container exited")
                        if self.backend.per_pod_routing:
                            kill.append((p.name, False))
                    if p.state == "starting" and now - p.created_at > START_TIMEOUT_S and self.backend.per_pod_routing:
                        self._event("failed", p.name, detail=f"not ready after {START_TIMEOUT_S:.0f} s")
                        kill.append((p.name, False))
                        p.state = "failed"
                    if p.state == "terminating" and prev != "terminating":
                        self._event("draining", p.name)
                    self._seen[p.name] = p.state
                for gone in [n for n in self._seen if n not in self.pods]:
                    if self._seen[gone] != "failed":
                        self._event("removed", gone)
                    self._seen.pop(gone, None)
                    self.inflight.pop(gone, None)
                    self.latest.pop(gone, None)

                active = [p for p in self.pods.values() if p.state in ("starting", "ready") and p.name not in self.draining]
                if self.backend.per_pod_routing:
                    if len(active) < self.desired:
                        create_n = self.desired - len(active)
                    elif len(active) > self.desired:
                        active.sort(key=lambda p: (p.state == "ready", self.inflight.get(p.name, 0), -p.created_at))
                        for p in active[:len(active) - self.desired]:
                            self.draining[p.name] = now
                            self._event("draining", p.name)
                    for name, since in list(self.draining.items()):
                        if name not in self.pods:
                            self.draining.pop(name, None)
                        elif self.inflight.get(name, 0) == 0 or now - since > DRAIN_TIMEOUT_S:
                            kill.append((name, True))
                elif self._k8s_target != self.desired:
                    k8s_target = self.desired

            # ---- slow work, lock NOT held: requests keep flowing while Docker works
            for name, drained in kill:
                try:
                    self.backend.remove(name)
                except Exception as e:                                       # the next loop tries again
                    obslog.warn_every(f"mgr-remove-{name}", 15, clog, "could not remove %s: %s", name, e)
                    continue
                if drained:
                    with self.lock:
                        self.draining.pop(name, None)
                        self._event("removed", name)
                        self._seen.pop(name, None)
                        self.pods.pop(name, None)
            if create_n:
                created = self.backend.create(create_n, self.spec())
                with self.lock:
                    for name in created:
                        self._event("create_requested", name)
            if k8s_target is not None:
                self.backend.scale_to(k8s_target, self.spec())
                with self.lock:
                    self._event("scale_requested", detail=f"deployment -> {k8s_target}")
                    self._k8s_target = k8s_target

    # ------------------------------------------------------------------ real resource samples
    def _sampler_loop(self):
        while not self._stop.is_set():
            t0 = time.time()
            try:
                stats = self.backend.stats()
                rows = []
                with self.lock:
                    for name, st in stats.items():
                        pod = self.pods.get(name)
                        if pod is None:
                            continue
                        self.latest[name] = (st, t0)
                        rows.append({
                            "ts": round(t0, 2), "replica": name, "state": pod.state, "cpu_pct": round(st.cpu_pct, 1),
                            "mem_mb": round(st.mem_mb, 1), "mem_limit_mb": round(st.mem_limit_mb or pod.mem_limit_mb or 0, 1),
                            "cpu_limit_cores": pod.cpu_limit_cores or ""})
                for row in rows:                                             # disk writes happen after the lock is released
                    C.append_csv(C.RESOURCES_CSV, C.RESOURCE_COLS, row)
            except Exception as e:
                self.last_error = f"stats: {type(e).__name__}: {e}"
                obslog.warn_every("mgr-stats", 15, clog, "resource sampling error: %s", self.last_error)
            self._stop.wait(max(0.2, SAMPLE_S - (time.time() - t0)))

    # ------------------------------------------------------------------ numbers for the gateway / dashboard
    def usage(self, max_age=30.0):
        """Mean CPU % (of one core) and mean memory (MB) over ready replicas, plus totals. None when nothing was measured."""
        now = time.time()
        with self.lock:
            vals = [self.latest[n][0] for n, p in self.pods.items()
                    if p.state == "ready" and n in self.latest and now - self.latest[n][1] <= max_age]
        if not vals:
            return None
        return {"mean_cpu_pct": sum(v.cpu_pct for v in vals) / len(vals), "mean_mem_mb": sum(v.mem_mb for v in vals) / len(vals),
                "total_cpu_cores": sum(v.cpu_pct for v in vals) / 100.0, "total_mem_mb": sum(v.mem_mb for v in vals), "n": len(vals)}

    def counts(self):
        with self.lock:
            return {"desired": self.desired,
                    "ready": sum(1 for p in self.pods.values() if p.state == "ready" and p.name not in self.draining),
                    "starting": sum(1 for p in self.pods.values() if p.state == "starting"),
                    "draining": len(self.draining) + sum(1 for p in self.pods.values() if p.state == "terminating")}

    def reset_replicas(self, dev: Device | None = None, burn_ms: float | None = None):
        """Used when the device or the app weight changes: remove every replica; the reconcile loop starts new ones."""
        with self._io:
            with self.lock:
                if dev is not None:
                    self.dev = dev
                if burn_ms is not None:
                    self.burn_ms = float(burn_ms)
                names = [p.name for p in self.pods.values()]
            if self.backend.per_pod_routing:
                for name in names:                                           # Docker is slow: do not hold the routing lock meanwhile
                    self.backend.remove(name)
            else:
                self.backend.prepare(self.spec(), build=False)              # Deployment is replaced with the new limits / env
                self.backend.scale_to(0, self.spec())
            with self.lock:
                if not self.backend.per_pod_routing:
                    self._k8s_target = None
                self.pods.clear()
                self.draining.clear()
                self.inflight.clear()
                self._seen.clear()
                self.latest.clear()
                self.desired = max(self.min_replicas, min(self.desired, self.dev.limits()["max_replicas"]))
                self._event("reset", detail=f"new spec: cpu {self.dev.cpu_per_replica} core, mem {self.dev.mem_per_replica_mb} MB, burn {self.burn_ms:.1f} ms")

    def snapshot(self) -> dict:
        now = time.time()
        with self.lock:
            pods = []
            for p in sorted(self.pods.values(), key=lambda x: x.created_at):
                st = self.latest.get(p.name)
                pods.append({"name": p.name, "state": "draining" if p.name in self.draining else p.state, "age_s": round(now - p.created_at, 1),
                             "startup_s": None if not p.ready_at else round(p.ready_at - p.created_at, 2),
                             "cpu_pct": None if not st else round(st[0].cpu_pct, 1), "mem_mb": None if not st else round(st[0].mem_mb, 1),
                             "cpu_limit_cores": p.cpu_limit_cores, "mem_limit_mb": p.mem_limit_mb, "inflight": self.inflight.get(p.name, 0)})
            su = self.startup_times
            return {"backend": self.backend.name, "isolated": self.backend.isolated, **self.counts(),
                    "max_replicas": self.dev.limits()["max_replicas"], "limits": self.dev.limits(), "device": self.dev.to_dict(),
                    "burn_ms": self.burn_ms, "pods": pods, "last_error": self.last_error,
                    "startup": {"n": len(su), "last": su[-1] if su else None, "avg": sum(su) / len(su) if su else None,
                                "max": max(su) if su else None}}
