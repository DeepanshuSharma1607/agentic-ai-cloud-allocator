"""
device.py - "what machine is this running on" and everything that follows from it.

The user types the machine (CPU cores, RAM) on the dashboard. From that we compute, with plain arithmetic:

  max replicas      = how many replicas fit after keeping some CPU / RAM for the other AegisCloud services
                      (prediction, agent, dashboard, gateway ...) and the operating system
  CPU / RAM share   = what one replica is allowed to use (a real Docker / Kubernetes limit)
  app weight        = CPU milliseconds one request costs (a property of the demo app). "Auto-fit" chooses it so that the
                      whole device can just carry the training data's peak with some headroom.

Nothing here talks to Docker or Kubernetes; it is only numbers, so it is easy to test.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields

import psutil

import seed as seed_mod
from infra import config as C

REQUEST_OVERHEAD_MS = 1.5      # FastAPI + HTTP cost per request on top of the "burn" (first guess; calibration measures the truth)


@dataclass
class Device:
    name: str = "This PC"
    cores: float = 8.0                 # logical CPUs of the machine (or of the Docker VM, if that is smaller)
    ram_mb: int = 16384                # RAM available to Docker (Docker Desktop on Windows gives its VM only part of it)
    reserve_cores: float = 3.0         # kept for gateway, prediction, agent, dashboard, load sender, OS
    reserve_ram_mb: int = 8000
    cpu_per_replica: float = 0.5       # CPU limit of one replica, in cores (a replica is one single-threaded process: use <= 1)
    mem_per_replica_mb: int = 192      # memory limit of one replica (the demo app holds ~103 MB)
    hard_max: int = 20                 # never more than this, whatever the machine says
    auto_fit: bool = True              # choose the app weight from the machine and the tick length
    burn_ms: float = 20.0              # app weight when auto_fit is off: CPU ms per request
    headroom: float = 1.4              # auto-fit: whole-device capacity = headroom x training peak
    target_util: float = 0.85          # a replica counts as "full" at this share of its measured maximum
    slo_p95_ms: float = 500.0          # latency goal: p95 below this is "within SLO"

    # ------------------------------------------------------------------ derived numbers
    def limits(self) -> dict:
        usable_cores = max(0.0, self.cores - self.reserve_cores)
        usable_ram = max(0.0, self.ram_mb - self.reserve_ram_mb)
        by_cpu = int(math.floor(usable_cores / max(self.cpu_per_replica, 0.05) + 1e-9))
        by_ram = int(usable_ram // max(self.mem_per_replica_mb, 16))
        caps = {"CPU": by_cpu, "RAM": by_ram, "hard limit": self.hard_max}
        binding = min(caps, key=caps.get)
        max_rep = max(1, min(caps.values()))
        return {"max_replicas": max_rep, "by_cpu": by_cpu, "by_ram": by_ram, "binding": binding,
                "usable_cores": usable_cores, "usable_ram_mb": usable_ram,
                "alloc_cores_at_max": max_rep * self.cpu_per_replica, "alloc_ram_at_max_mb": max_rep * self.mem_per_replica_mb,
                "fits": by_cpu >= 1 and by_ram >= 1}

    def warnings(self) -> list:
        out = []
        lim = self.limits()
        if not lim["fits"]:
            out.append("Not even one replica fits after the reserve. Lower the reserve or the per-replica share (the system will still run 1 replica).")
        if self.cpu_per_replica > 1.0:
            out.append("A replica is a single-threaded process; a CPU share above 1 core does not make it faster.")
        if self.mem_per_replica_mb < 160:
            out.append("The demo app holds about 103 MB plus Python: below ~160 MB a replica may be killed for running out of memory.")
        if self.cores - self.reserve_cores < self.cpu_per_replica:
            out.append("The CPU reserve leaves less than one replica's share.")
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Device":
        data = data or {}
        kinds = {f.name: f.type for f in fields(cls)}
        clean = {}
        for k, v in data.items():
            if k not in kinds:
                continue
            t = kinds[k]
            try:
                if t in ("float", float):
                    clean[k] = float(v)
                elif t in ("int", int):
                    clean[k] = int(v)
                elif t in ("bool", bool):
                    clean[k] = bool(v)
                else:
                    clean[k] = str(v)
            except (TypeError, ValueError):
                continue
        d = cls(**clean)
        d.cores = max(0.5, d.cores)
        d.ram_mb = max(256, d.ram_mb)
        d.reserve_cores = min(max(0.0, d.reserve_cores), d.cores)
        d.reserve_ram_mb = min(max(0, d.reserve_ram_mb), d.ram_mb)
        d.cpu_per_replica = min(max(0.05, d.cpu_per_replica), 8.0)
        d.mem_per_replica_mb = max(64, d.mem_per_replica_mb)
        d.hard_max = min(max(1, d.hard_max), 100)
        d.burn_ms = min(max(0.5, d.burn_ms), 5000.0)
        d.headroom = min(max(0.5, d.headroom), 10.0)
        d.target_util = min(max(0.3, d.target_util), 1.0)
        d.slo_p95_ms = max(10.0, d.slo_p95_ms)
        return d


# ---------------------------------------------------------------------- presets and detection
def detect() -> Device:
    """The machine this code runs on (logical CPUs and total RAM). The user can still edit every number."""
    cores = float(psutil.cpu_count(logical=True) or 4)
    ram = int(psutil.virtual_memory().total / 1e6)
    return Device.from_dict({"name": "This machine (detected)", "cores": cores, "ram_mb": ram,
                             "reserve_cores": max(1.0, round(cores * 0.35, 1)), "reserve_ram_mb": int(ram * 0.5)})


PRESETS = {
    "This machine (detected)": None,
    "Laptop 8 threads / 16 GB (Docker Desktop)": {"cores": 8, "ram_mb": 16384, "reserve_cores": 3, "reserve_ram_mb": 8000},
    "Laptop 4 threads / 8 GB": {"cores": 4, "ram_mb": 8192, "reserve_cores": 2, "reserve_ram_mb": 5000},
    "EC2 2 vCPU / 2 GB (needs the 'process' backend)": {"cores": 2, "ram_mb": 2048, "reserve_cores": 1, "reserve_ram_mb": 1400},
    "EC2 2 vCPU / 4 GB": {"cores": 2, "ram_mb": 4096, "reserve_cores": 1, "reserve_ram_mb": 2000},
    "EC2 4 vCPU / 8 GB": {"cores": 4, "ram_mb": 8192, "reserve_cores": 1.5, "reserve_ram_mb": 3000},
}


def preset(name: str) -> Device:
    if PRESETS.get(name) is None:
        return detect()
    return Device.from_dict({"name": name, **PRESETS[name]})


# ---------------------------------------------------------------------- app weight and capacity
def training_peak_per_tick() -> float:
    return float(seed_mod.seed_stats()["max"])


def fit_burn_ms(dev: Device, tick_seconds: float, peak_per_tick: float | None = None) -> float:
    """CPU ms per request so that  max_replicas x per-replica rate x target_util = headroom x peak rps."""
    peak = peak_per_tick if peak_per_tick is not None else training_peak_per_tick()
    peak_rps = max(peak / max(tick_seconds, 0.1), 0.1)
    share = min(dev.cpu_per_replica, 1.0)
    burn_s = dev.limits()["max_replicas"] * share * dev.target_util / (dev.headroom * peak_rps) - REQUEST_OVERHEAD_MS / 1000.0
    return float(min(max(burn_s * 1000.0, 1.0), 2000.0))


def effective_burn_ms(dev: Device, tick_seconds: float) -> float:
    return fit_burn_ms(dev, tick_seconds) if dev.auto_fit else dev.burn_ms


def estimate_rps_per_replica(dev: Device, burn_ms: float) -> float:
    """Max requests per second of one replica, from its CPU share. Only an estimate: calibration measures the real number."""
    return min(dev.cpu_per_replica, 1.0) / ((burn_ms + REQUEST_OVERHEAD_MS) / 1000.0)


def calibration_matches(cal: dict | None, dev: Device, burn_ms: float) -> bool:
    if not cal or not cal.get("rps_per_replica"):
        return False
    return (abs(cal.get("cpu_per_replica", -1) - dev.cpu_per_replica) < 1e-6 and cal.get("mem_per_replica_mb") == dev.mem_per_replica_mb
            and abs(cal.get("burn_ms", -1) - burn_ms) < 0.05 * max(burn_ms, 1.0))


def capacity_per_tick(dev: Device, tick_seconds: float, burn_ms: float, cal: dict | None = None):
    """(requests per tick one replica can take at target utilisation, 'calibrated' | 'estimated')."""
    if calibration_matches(cal, dev, burn_ms):
        return cal["rps_per_replica"] * tick_seconds * dev.target_util, "calibrated"
    return estimate_rps_per_replica(dev, burn_ms) * tick_seconds * dev.target_util, "estimated"


def load_device() -> Device:
    data = C.read_json(C.DEVICE_JSON)
    return Device.from_dict(data) if data else detect()


def save_device(dev: Device):
    C.write_json(C.DEVICE_JSON, dev.to_dict())
