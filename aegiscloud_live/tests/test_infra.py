"""Tests for the real-replica part (infra/). No Docker or Kubernetes needed: fake backends and one run with real local processes."""
import time
from unittest import mock

import pytest

from infra import device as DV
from infra import runtime as R
from infra.backends.base import Backend, Pod, Stat
from infra.manager import ClusterManager


# ------------------------------------------------------------------ device
def test_limits_follow_the_machine():
    dev = DV.Device.from_dict({"cores": 8, "ram_mb": 16384, "reserve_cores": 3, "reserve_ram_mb": 8000, "cpu_per_replica": 0.5, "mem_per_replica_mb": 192})
    lim = dev.limits()
    assert lim["by_cpu"] == 10 and lim["by_ram"] == 43 and lim["max_replicas"] == 10 and lim["binding"] == "CPU"
    small = DV.Device.from_dict({"cores": 2, "ram_mb": 2048, "reserve_cores": 1, "reserve_ram_mb": 1400, "cpu_per_replica": 0.5, "mem_per_replica_mb": 192})
    assert small.limits()["max_replicas"] == 2 and small.limits()["binding"] == "CPU"


def test_at_least_one_replica_and_warning_when_nothing_fits():
    dev = DV.Device.from_dict({"cores": 1, "ram_mb": 1024, "reserve_cores": 1, "reserve_ram_mb": 1000})
    assert dev.limits()["max_replicas"] == 1 and not dev.limits()["fits"] and dev.warnings()


def test_from_dict_clamps_nonsense():
    dev = DV.Device.from_dict({"cores": -5, "ram_mb": "abc", "cpu_per_replica": 99, "reserve_cores": 500, "unknown": 1})
    assert dev.cores >= 0.5 and dev.cpu_per_replica <= 8 and dev.reserve_cores <= dev.cores


def test_auto_fit_makes_the_machine_just_carry_the_peak():
    dev = DV.Device.from_dict({"cores": 8, "ram_mb": 16384, "reserve_cores": 3, "reserve_ram_mb": 8000})
    burn = DV.fit_burn_ms(dev, 5.0, peak_per_tick=1000)
    cap, _ = DV.capacity_per_tick(dev, 5.0, burn)
    assert cap * dev.limits()["max_replicas"] == pytest.approx(1000 * dev.headroom, rel=0.05)


def test_longer_tick_means_a_lighter_request_is_enough_to_need_the_same_replicas():
    dev = DV.Device()
    assert DV.fit_burn_ms(dev, 60.0, 1000) > DV.fit_burn_ms(dev, 5.0, 1000)


def test_calibration_is_used_only_if_it_matches_the_settings():
    dev = DV.Device()
    burn = 20.0
    cal = {"rps_per_replica": 30.0, "cpu_per_replica": dev.cpu_per_replica, "mem_per_replica_mb": dev.mem_per_replica_mb, "burn_ms": burn}
    cap, src = DV.capacity_per_tick(dev, 5.0, burn, cal)
    assert src == "calibrated" and cap == pytest.approx(30 * 5 * dev.target_util)
    assert DV.capacity_per_tick(dev, 5.0, 40.0, cal)[1] == "estimated"


# ------------------------------------------------------------------ manager with a fake backend
class FakeBackend(Backend):
    name = "fake"

    def __init__(self, startup=0.0):
        self.pods, self.startup, self.n = {}, startup, 0

    def observe(self):
        for p in self.pods.values():
            if p.state == "starting" and time.time() - p.created_at >= self.startup:
                p.state, p.ready_at = "ready", time.time()
        return list(self.pods.values())

    def create(self, count, spec):
        names = []
        for _ in range(count):
            self.n += 1
            self.pods[f"r{self.n}"] = Pod(name=f"r{self.n}", url=f"http://x/{self.n}")
            names.append(f"r{self.n}")
        return names

    def remove(self, name):
        self.pods.pop(name, None)

    def stats(self):
        return {n: Stat(cpu_pct=50.0, mem_mb=100.0) for n, p in self.pods.items() if p.state == "ready"}


def make_manager(startup=0.0, **dev):
    d = DV.Device.from_dict({"cores": 6, "ram_mb": 8192, "reserve_cores": 1, "reserve_ram_mb": 2000, "cpu_per_replica": 1.0, **dev})
    return ClusterManager(FakeBackend(startup), d, burn_ms=5.0, log=lambda *_: None)


def test_scale_up_creates_replicas_and_measures_startup():
    m = make_manager(startup=0.2)
    m.reconcile()
    assert m.set_desired(3)["desired"] == 3
    m.reconcile(); m.reconcile()                         # first call starts the missing replicas, second one sees them
    assert m.counts()["starting"] == 3 and m.counts()["ready"] == 0 and m.routable() == []        # not usable until Ready
    time.sleep(0.3)
    m.reconcile()
    assert m.counts()["ready"] == 3 and len(m.routable()) == 3
    assert m.snapshot()["startup"]["n"] == 3 and m.snapshot()["startup"]["last"] >= 0.2


def test_request_above_the_device_limit_is_clamped_and_logged():
    m = make_manager()                                  # 6 cores - 1 reserve = 5 replicas at 1 core
    res = m.set_desired(50)
    assert res["clamped"] and res["desired"] == 5 == res["max_replicas"]
    assert any(e["event"] == "clamped" for e in m.events)


def test_scale_down_drains_then_removes():
    m = make_manager()
    m.set_desired(4)
    m.reconcile(); m.reconcile()
    busy = [m.pick()[0] for _ in range(4)]               # one request in flight on every replica
    m.set_desired(2)
    m.reconcile()
    assert m.counts()["draining"] == 2 and len(m.backend.pods) == 4        # not removed while a request is running
    assert all(n not in m.draining for n, _ in m.routable())        # a draining replica gets no new requests
    for name in busy:
        m.release(name)
    m.reconcile(); m.reconcile()
    assert len(m.backend.pods) == 2 and m.counts()["ready"] == 2


def test_pick_prefers_the_least_busy_replica():
    m = make_manager()
    m.set_desired(2)
    m.reconcile(); m.reconcile()
    first = m.pick()[0]
    second = m.pick()[0]
    assert first != second


def test_failed_replica_is_replaced():
    m = make_manager()
    m.set_desired(2)
    m.reconcile(); m.reconcile()
    m.backend.pods["r1"].state = "failed"
    m.reconcile(); m.reconcile()
    assert m.counts()["ready"] == 2 and "r1" not in m.backend.pods


def test_usage_is_real_means_or_none():
    m = make_manager()
    assert m.usage() is None                             # nothing measured: no invented numbers
    m.set_desired(2)
    m.reconcile(); m.reconcile()
    m.latest = {n: (s, time.time()) for n, s in m.backend.stats().items()}
    u = m.usage()
    assert u["mean_cpu_pct"] == 50.0 and u["total_cpu_cores"] == 1.0


def test_reset_removes_everything_and_keeps_desired_inside_new_limit():
    m = make_manager()
    m.set_desired(5)
    m.reconcile(); m.reconcile()
    m.reset_replicas(DV.Device.from_dict({"cores": 3, "ram_mb": 8192, "reserve_cores": 1, "reserve_ram_mb": 1000, "cpu_per_replica": 1.0}))
    assert m.backend.pods == {} and m.desired == 2


# ------------------------------------------------------------------ docker / k8s backends (mocked clients)
def test_docker_backend_passes_real_limits():
    from infra.backends import docker_backend as DB
    fake_client = mock.MagicMock()
    fake_client.containers.run.return_value.attrs = {"NetworkSettings": {"Ports": {"8001/tcp": [{"HostPort": "49155"}]}}}
    with mock.patch.dict("sys.modules", {"docker": mock.MagicMock(from_env=lambda: fake_client)}):
        be = DB.DockerBackend()
    be.create(1, {"cpu_cores": 0.5, "mem_mb": 192, "burn_ms": 12.0})
    kw = fake_client.containers.run.call_args.kwargs
    assert kw["nano_cpus"] == 500_000_000 and kw["mem_limit"] == "192m" and kw["memswap_limit"] == "192m"
    assert kw["environment"]["AEGIS_CPU_BURN_MS"] == "12.0" and kw["labels"] == {"aegiscloud": "replica"}
    assert list(be.pods.values())[0].url == "http://127.0.0.1:49155"


def test_docker_cpu_percent_comes_from_real_counters():
    from infra.backends import docker_backend as DB
    fake_client = mock.MagicMock()
    with mock.patch.dict("sys.modules", {"docker": mock.MagicMock(from_env=lambda: fake_client)}):
        be = DB.DockerBackend()
    be.pods["c1"] = Pod(name="c1", state="ready")
    seq = iter([{"cpu_stats": {"cpu_usage": {"total_usage": 1_000_000_000}}, "memory_stats": {"usage": 150_000_000, "stats": {"inactive_file": 46_000_000}}},
                {"cpu_stats": {"cpu_usage": {"total_usage": 1_500_000_000}}, "memory_stats": {"usage": 150_000_000, "stats": {"inactive_file": 46_000_000}}}])
    fake_client.containers.get.return_value.stats.side_effect = lambda **k: next(seq)
    assert be.stats() == {}                              # first sample: no delta yet, so no number
    time.sleep(1.0)
    st = be.stats()["c1"]
    assert 30 < st.cpu_pct < 60 and st.mem_mb == pytest.approx(104.0)          # 0.5 s of CPU in ~1 s = ~50 %, cache subtracted


def test_k8s_unit_parsing():
    from infra.backends.k8s_backend import parse_cpu, parse_mem_mb
    assert parse_cpu("250m") == 0.25 and parse_cpu("1") == 1.0 and parse_cpu("500000000n") == pytest.approx(0.5)
    assert parse_mem_mb("128Mi") == pytest.approx(134.217728) and parse_mem_mb("104856Ki") == pytest.approx(107.4, rel=0.01)


# ------------------------------------------------------------------ the agent wrapper
def test_agent_wrapper_replaces_set_replicas_and_never_crashes(monkeypatch):
    import infra.agent_real as AR
    calls = []
    monkeypatch.setattr(AR.requests, "post", lambda url, json=None, timeout=None: calls.append((url, json)))
    AR.real_set_replicas(4)
    assert calls[0][1] == {"n": 4, "source": "agent"} and calls[0][0].endswith("/infra/scale")

    def boom(*a, **k):
        raise ConnectionError("down")
    monkeypatch.setattr(AR.requests, "post", boom)
    AR.real_set_replicas(2)                              # must only warn


def test_runtime_defaults_to_the_old_tick():
    import settings as S
    assert R.load()["tick_seconds"] == S.TICK_SECONDS


def test_apply_settings_stores_what_every_part_must_agree_on():
    dev = DV.Device.from_dict({"cores": 8, "ram_mb": 16384, "reserve_cores": 3, "reserve_ram_mb": 8000})
    rt = R.apply_settings(dev, 10.0, "process")
    assert rt["tick_seconds"] == 10.0 and rt["max_replicas"] == dev.limits()["max_replicas"] and rt["capacity_per_tick"] > 0
    assert R.tick_seconds() == 10.0


# ------------------------------------------------------------------ real local processes, end to end
def test_process_backend_starts_real_replicas_that_answer_requests():
    import httpx
    from infra.backends.process_backend import ProcessBackend
    be = ProcessBackend()
    m = ClusterManager(be, DV.Device.from_dict({"cores": 4, "ram_mb": 8192, "reserve_cores": 1, "reserve_ram_mb": 1000}), burn_ms=1.0, log=lambda *_: None)
    try:
        m.set_desired(2)
        deadline = time.time() + 40
        while time.time() < deadline and m.counts()["ready"] < 2:
            m.reconcile()
            time.sleep(0.3)
        assert m.counts()["ready"] == 2
        for name, url in m.routable():
            assert httpx.get(f"{url}/work", timeout=5).status_code == 200
        assert all(e["startup_s"] not in ("", None) for e in m.events if e["event"] == "ready")
    finally:
        m.shutdown()
