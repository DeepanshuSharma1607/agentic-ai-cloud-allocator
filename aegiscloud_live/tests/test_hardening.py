"""Pre-deployment hardening: one failure must skip one tick / one row, never stop a service, never drop a scale command silently."""
import asyncio
import re
import time
from pathlib import Path

import httpx
import pytest

import settings as S
from agent import config as cfg
from agent import llm, nodes
from agent.state import new_state

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ 1. the replica image contains everything the replica imports
def test_replica_dockerfile_copies_every_package_the_replica_imports():
    docker = (ROOT / "infra/docker/Dockerfile.replica").read_text()
    copied = set(re.findall(r"^COPY\s+(\S+)", docker, flags=re.M))
    needed = set()
    for f in [ROOT / "infra/replica_app.py", *(ROOT / "traffic/target_app").glob("*.py")]:
        for m in re.finditer(r"^\s*(?:from|import)\s+(obs|ui|settings|seed|agent|prediction)\b", f.read_text(), flags=re.M):
            needed.add(m.group(1))
    for pkg in needed:
        assert any(c.rstrip("/").lstrip("./").startswith(pkg) for c in copied), f"Dockerfile.replica does not COPY {pkg}"


# ------------------------------------------------------------------ 2. collector keeps running after a bad tick
def test_collector_loop_survives_a_failing_tick(monkeypatch):
    from traffic.collector import app as col

    async def go():
        c = col.Collector()
        monkeypatch.setattr(S, "TICK_SECONDS", 0.05)
        calls = {"n": 0}

        async def bad_tick(client):
            calls["n"] += 1
            raise PermissionError("live_metrics.csv is open in Excel")

        async def fake_get(self, url, **kw):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(c, "collect_once", bad_tick)
        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        task = asyncio.create_task(c.run())
        await asyncio.sleep(0.4)
        alive = not task.done()
        task.cancel()
        return alive, calls["n"]

    alive, n = asyncio.run(go())
    assert alive and n >= 3


# ------------------------------------------------------------------ 3. a locked CSV drops one row, it does not crash the agent
def test_append_row_never_raises_on_a_locked_file(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    blocked = tmp_path / "locked.csv"
    blocked.mkdir()                                            # opening a directory for writing raises an OSError, like a locked file
    nodes.append_row(blocked, ["a", "b"], {"a": 1, "b": 2})    # must not raise
    ok = tmp_path / "ok.csv"
    nodes.append_row(ok, ["a", "b"], {"a": 1, "b": 2})
    assert ok.read_text().splitlines()[1] == "1,2"


# ------------------------------------------------------------------ 4. a scale command the gateway never confirmed is not recorded as applied
def test_failed_scale_keeps_the_old_replica_count(monkeypatch):
    nodes.reset_files()
    monkeypatch.setattr(nodes, "set_replicas", lambda n: False)
    st = new_state(30.0, 8, 1, 100)
    st.update(minute=101, mode=cfg.MODE_TIMER, reason="t", traffic_now=200.0, forecast=300.0,
              decision={"action": "scale_up", "replicas": 5, "reason": "need more"})
    out = nodes.apply_and_log(st)
    assert out["applied"] == 1 and out["replicas"] == 1
    monkeypatch.setattr(nodes, "set_replicas", lambda n: None)          # the placeholder (no gateway) still counts as success
    assert nodes.apply_and_log(st)["applied"] == 3                      # the existing guardrail allows at most +2 replicas per tick


def test_real_set_replicas_retries_then_reports_failure(monkeypatch):
    from infra import agent_real as AR
    calls = []

    def post(url, json=None, timeout=None):
        calls.append(timeout)
        raise AR.requests.exceptions.ReadTimeout("slow")
    monkeypatch.setattr(AR.requests, "post", post)
    monkeypatch.setattr(AR.time, "sleep", lambda s: None)
    assert AR.real_set_replicas(3) is False and len(calls) == 3


# ------------------------------------------------------------------ 5/6. LLM rate-limit protection
@pytest.fixture
def online_llm(monkeypatch):
    monkeypatch.setattr(cfg, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(cfg, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(cfg, "LLM_RETRY_WAIT", 0)
    monkeypatch.setattr(cfg, "LLM_MIN_GAP_SECONDS", 20)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    llm._state.update(last_call=0.0, blocked_until=0.0)
    yield
    llm._state.update(last_call=0.0, blocked_until=0.0)


FACTS = {"traffic_now": 300.0, "forecast": 350.0, "replicas": 1, "capacity": 200.0, "min_replicas": 1, "max_replicas": 4}


def test_429_opens_the_breaker_and_the_formula_takes_over(online_llm, monkeypatch):
    calls = []

    class R:
        status_code, text, headers = 429, "Too Many Requests", {"Retry-After": "1"}

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: calls.append(1) or R())
    first = llm.ask_llm("s", "timer", "r", FACTS)
    assert first["error"] is True and "429" in first["reason"]
    n_after_first = len(calls)
    second = llm.ask_llm("s", "unusual", "r", FACTS)                  # breaker open: no HTTP call, plain formula decides
    assert len(calls) == n_after_first
    assert second["replicas"] >= 2 and "plain formula" in second["reason"] and not second.get("error")


def test_minimum_gap_between_online_calls(online_llm, monkeypatch):
    calls = []

    class R:
        status_code, headers = 200, {}
        text = ""
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '{"action":"hold","replicas":1,"reason":"ok","escalate":false}'}]}}]}

    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: calls.append(1) or R())
    assert llm.ask_llm("s", "timer", "r", FACTS)["reason"] == "ok"
    out = llm.ask_llm("s", "unusual", "r", FACTS)                     # 0 s later: skipped, plain formula
    assert len(calls) == 1 and "minimum gap" in out["reason"]


def test_alert_email_still_sent_while_rate_limited(online_llm):
    llm._state["blocked_until"] = time.time() + 60
    mail = llm.write_alert_email("overload", "context")
    assert mail["subject"].startswith("[URGENT]") and "paused" in mail["body"]


# ------------------------------------------------------------------ 10. dashboard does not re-wait on a dead service
def test_dashboard_skips_get_calls_to_a_service_that_just_failed(monkeypatch):
    from frontend import data_access as D
    D._down.clear()
    n = {"c": 0}

    def boom(*a, **k):
        n["c"] += 1
        raise D.requests.exceptions.ConnectTimeout("x")
    monkeypatch.setattr(D.requests, "request", boom)
    assert D.api("GET", "http://127.0.0.1:9/infra/state")[0] is False
    assert D.api("GET", "http://127.0.0.1:9/infra/events")[0] is False
    assert n["c"] == 1                                                 # the second call was skipped
    D.api("POST", "http://127.0.0.1:9/infra/scale")                    # POSTs are never skipped
    assert n["c"] == 2
    D._down.clear()


# ------------------------------------------------------------------ 13. log viewer reads only the files it needs
def test_log_store_read_skips_other_apps_files(tmp_path, monkeypatch):
    from obs import store
    monkeypatch.setattr(S, "LOG_DIR", tmp_path)
    (tmp_path / "a.jsonl").write_text('{"t": 1.0, "app": "a", "level": "INFO", "msg": "x"}\n')
    (tmp_path / "b.jsonl").write_text('{"t": 2.0, "app": "b", "level": "INFO", "msg": "y"}\n')
    opened = []
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: (opened.append(Path(str(p)).name), real_open(p, *a, **k))[1])
    rows = store.read(apps={"b"})
    assert [r["app"] for r in rows] == ["b"] and "a.jsonl" not in opened
