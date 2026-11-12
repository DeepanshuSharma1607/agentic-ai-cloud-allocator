"""
test_part2.py - checks Part 2: the request counter (APP 1) and the sender page + demo (APP 2).

Run:  python -m pytest tests/test_part2.py -q
The apps are tested through small stand-in web apps (no real ports, no real replicas), so they run in about a second.
"""
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import settings as S
from ui import counter as uic
from ui import sender as uis

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ counter logic
def test_counter_counts_total_inflight_and_failures():
    c = uic.RequestCounter()
    c.start(); c.start(); c.start()
    assert c.inflight == 3 and c.total == 3
    c.finish(200); c.finish(503)
    assert c.inflight == 1 and c.failed == 1
    assert c.data()["failing_now"] == 1


def test_counter_never_goes_below_zero_in_flight():
    c = uic.RequestCounter()
    c.finish(200)
    assert c.inflight == 0


def test_requests_per_second_is_the_average_of_the_last_complete_seconds():
    c = uic.RequestCounter()
    last = int(time.time()) - 1
    for i in range(5):                                   # 10 requests in each of the last 5 complete seconds
        c.buckets.append([last - i, 10])
    d = c.data()
    assert d["rps"] == 10.0 and len(d["history"]) == uic.HISTORY_S and d["history"][-1] == 10


# ------------------------------------------------------------------ counter as a web app
def make_front_door(extra=None):
    app = FastAPI()
    holder = {}

    @app.get("/work")
    def work(fail: int = 0):
        holder["inflight_seen"] = holder["counter"].inflight
        return JSONResponse({"ok": not fail}, status_code=503 if fail else 200)

    @app.get("/health")
    def health():
        return {"ok": True}

    holder["counter"] = uic.mount(app, extra=extra)
    return app, holder


def test_counter_page_and_data_endpoint():
    app, _ = make_front_door()
    c = TestClient(app)
    page = c.get("/")
    assert page.status_code == 200 and "Request counter" in page.text
    d = c.get("/counter/data").json()
    assert {"inflight", "rps", "history", "total", "failed", "failing_now"} <= set(d)


def test_only_work_requests_are_counted_and_failures_are_seen():
    app, _ = make_front_door()
    c = TestClient(app)
    for _ in range(3):
        c.get("/work")
    c.get("/work?fail=1")
    c.get("/health"); c.get("/counter/data")
    d = c.get("/counter/data").json()
    assert d["total"] == 4 and d["failed"] == 1 and d["inflight"] == 0


def test_request_is_counted_as_in_flight_while_it_is_being_handled():
    app, holder = make_front_door()
    TestClient(app).get("/work")
    assert holder["inflight_seen"] == 1


def test_counter_does_not_change_the_answer_of_the_app():
    app, _ = make_front_door()
    r = TestClient(app).get("/work")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_extra_fields_are_added_and_a_failing_extra_does_not_break_the_page():
    app, _ = make_front_door(extra=lambda: {"replicas": {"desired": 2, "ready": 1, "starting": 1, "draining": 0}})
    assert TestClient(app).get("/counter/data").json()["replicas"]["ready"] == 1

    def broken():
        raise RuntimeError("manager not ready")

    app2, _ = make_front_door(extra=broken)
    d = TestClient(app2).get("/counter/data").json()
    assert d["total"] == 0 and "replicas" not in d


# ------------------------------------------------------------------ sender page + demo
class FakeEngine:
    """Stand-in for LoadEngine: records what the demo asks for."""

    def __init__(self):
        self.segments, self.base = [], {"mode": "idle"}
        self.stopped = 0

    def stop(self, cancel_schedule=True):
        self.stopped += 1
        self.segments = []
        self.base = {"mode": "idle"}

    def add_segment(self, plan, duration_s, start_ts):
        seg = {"id": len(self.segments) + 1, "plan": plan, "start": start_ts, "end": start_ts + duration_s}
        self.segments.append(seg)
        return seg


@pytest.fixture()
def sender(monkeypatch):
    monkeypatch.setattr(uis, "demo_sizes", lambda: (30, 250))
    app = FastAPI()
    app.state.engine = FakeEngine()
    uis.mount(app)
    return app, TestClient(app)


def test_sender_page_is_served(sender):
    _, c = sender
    r = c.get("/")
    assert r.status_code == 200 and "Request sender" in r.text and "Run demo" in r.text


def test_demo_queues_quiet_spike_quiet_back_to_back_and_takes_over(sender):
    app, c = sender
    r = c.post("/demo").json()
    eng = app.state.engine
    assert eng.stopped == 1 and eng.base == {"mode": "idle"}
    assert [s["plan"]["n"] for s in eng.segments] == [30, 250, 30]
    assert all(eng.segments[i]["end"] == pytest.approx(eng.segments[i + 1]["start"]) for i in range(2))
    tick = S.TICK_SECONDS
    assert [p["duration_s"] for p in r["phases"]] == pytest.approx([6 * tick, 18 * tick, 12 * tick])
    assert r["running"] is True and r["current"] == "Quiet"


def test_demo_status_follows_the_clock_and_stops_when_cancelled(sender):
    app, c = sender
    c.post("/demo")
    app.state.demo["started"] -= 7 * S.TICK_SECONDS      # pretend 7 ticks have passed -> we are in the spike
    st = c.get("/demo/status").json()
    assert st["running"] is True and st["current"] == "Spike"
    app.state.engine.segments = []                       # what Stop does
    assert c.get("/demo/status").json()["running"] is False


def test_demo_status_before_any_demo(sender):
    _, c = sender
    assert c.get("/demo/status").json() == {"running": False}


def test_demo_sizes_follow_the_calibrated_capacity_and_respect_the_safety_cap(monkeypatch):
    import infra.runtime as R
    monkeypatch.undo()
    monkeypatch.setattr(R, "load", lambda: {"capacity_per_tick": 100})
    assert uis.demo_sizes() == (30, 160)                                       # 30% and 1.6x of one replica
    monkeypatch.setattr(R, "load", lambda: {"capacity_per_tick": 10_000_000})
    quiet, spike = uis.demo_sizes()
    assert spike == round(uis.MAX_DEMO_PER_SECOND * S.TICK_SECONDS) <= S.MAX_REQUESTS_PER_TICK and quiet <= spike   # PC-safe ceiling
    monkeypatch.setattr(R, "load", lambda: {})
    assert uis.demo_sizes() == (45, 240)                                       # not calibrated yet: assumes 150 per tick


# ------------------------------------------------------------------ wiring (the real apps call the new code)
@pytest.mark.parametrize("rel, needle", [("infra/gateway.py", "mount_counter(app"),
                                         ("traffic/target_app/app.py", "mount_counter(app"),
                                         ("traffic/loadgen/app.py", "mount_sender(app")])
def test_real_apps_mount_the_new_pages(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8")


# =================================================================== Part 2.1: the request-flow fix
import asyncio
import json
import re
import shutil
import subprocess

from obs.rates import RateWindow


def test_rate_window_averages_complete_seconds_and_ignores_the_current_one():
    w = RateWindow()
    now = int(time.time())
    for i in range(1, 6):
        w.buckets.append([now - i, 20])
    w.add(500)                                            # current, unfinished second: must not count yet
    assert w.rate(5) == 20.0 and w.per_second(5) == [20] * 5


def test_counter_reports_ok_rate_answer_time_and_busiest_second():
    c = uic.RequestCounter()
    last = int(time.time()) - 1
    c.buckets.append([last, 40]); c.buckets.append([last - 1, 10])
    for ms in (100, 300):
        c.start(); c.finish(200, ms)
    c.start(); c.finish(503, 200)
    d = c.data()
    assert d["ok"] == 2 and d["failed"] == 1 and d["avg_ms"] == 200.0 and d["peak_rps"] == 40 and d["waiting"] == 0
    assert d["ok_per_s"] == 0.0                           # just-finished requests are in the unfinished second: not counted yet
    c.ok_rate.buckets.append([last, 20])
    assert c.data()["ok_per_s"] == 2.0                    # 20 answers in one of the last 10 seconds


def test_counter_data_can_be_read_from_another_page_but_not_written():
    app, _ = make_front_door()
    c = TestClient(app)
    r = c.get("/counter/data", headers={"Origin": "http://localhost:8002"})
    assert r.headers["access-control-allow-origin"] == "*"
    pre = c.options("/work", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 400                         # a POST from another site is refused


def test_sender_status_is_readable_from_the_counter_page(sender):
    _, c = sender
    assert c.get("/demo/status", headers={"Origin": "http://localhost:8001"}).headers["access-control-allow-origin"] == "*"


class FakeResponse:
    def __init__(self, code):
        self.status_code = code


class FakeClient:
    def __init__(self, code=200, delay=0.0):
        self.code, self.delay = code, delay

    async def get(self, url):
        await asyncio.sleep(self.delay)
        if self.code == "boom":
            raise RuntimeError("connection reset")
        return FakeResponse(self.code)


@pytest.fixture()
def engine(monkeypatch):
    monkeypatch.setattr(S, "LOADGEN_AUTOSTART", "off")
    from traffic.loadgen.engine import LoadEngine, TickCounter
    return LoadEngine(), TickCounter


def test_late_answers_are_counted_in_the_totals_when_they_arrive(engine):
    eng, Tick = engine
    c = Tick(10, "base:fixed", "fixed", 1)

    async def scenario():
        slow = [asyncio.create_task(eng._send(FakeClient(200, delay=0.2), c)) for _ in range(6)]
        fast = [asyncio.create_task(eng._send(FakeClient("boom"), c)) for _ in range(2)]
        await asyncio.gather(*fast)
        mid = eng.status()                                  # the slow ones are still on their way
        await asyncio.gather(*slow)
        return mid, eng.status()

    mid, end = asyncio.run(scenario())
    assert mid["totals"]["sent"] == 8 and mid["in_flight"] == 6 and mid["totals"]["failed"] == 2
    assert end["in_flight"] == 0 and end["totals"]["ok"] == 6 and end["totals"]["failed"] == 2     # nothing is lost
    assert c.ok == 6 and c.failed == 2
    assert end["rates"]["avg_ms"] > 0 and {"sent_per_s", "ok_per_s", "failed_per_s"} <= set(end["rates"])


def test_logging_a_tick_no_longer_adds_to_the_running_totals_twice(engine):
    eng, Tick = engine
    c = Tick(5, "base:fixed", "fixed", 1)
    asyncio.run(eng._send(FakeClient(200), c))
    before = dict(eng.totals)
    eng._log_tick(c)
    assert eng.totals["sent"] == before["sent"] == 1 and eng.totals["ok"] == before["ok"] == 1 and eng.totals["planned"] == 5


# --- the diagnosis sentences on both pages, run in Node with the numbers of the screenshot you sent
NODE = shutil.which("node")


def run_diagnose(html_name, s, c):
    html = (ROOT / "ui" / html_name).read_text(encoding="utf-8")
    fn = re.search(r"function diagnose\(s,c\)\{.*?\n\}\n", html, re.S).group(0)
    script = ("const f1=n=>(Math.round(n*10)/10).toString(), fmt=n=>Number(n).toLocaleString();\n"
              "let lastAsk=null, changedAt=0;\n" + fn +
              f"\nconst s={json.dumps(s)}, c={json.dumps(c)};\nconsole.log(JSON.stringify(diagnose(s,c)));")
    return json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)


def snd(planned=0, sent_s=0.0, ok_s=0.0, failed_s=0.0, in_flight=0, avg_ms=0.0):
    return {"last_tick": {"planned": planned}, "tick_seconds": 5, "in_flight": in_flight,
            "rates": {"sent_per_s": sent_s, "ok_per_s": ok_s, "failed_per_s": failed_s, "avg_ms": avg_ms}}


def cnt(rps=0.0, avg_ms=0.0, failing_now=0):
    return {"rps": rps, "avg_ms": avg_ms, "failing_now": failing_now}


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
@pytest.mark.parametrize("page", ["sender.html", "counter.html"])
def test_page_explains_what_is_wrong_in_plain_words(page):
    d = run_diagnose(page, snd(), cnt())
    assert d["lvl"] == "idle"
    # your screenshot: asked for 2000 per tick (400/s); the sender manages ~230/s; 24/s reach the front door
    d = run_diagnose(page, snd(planned=2000, sent_s=230, in_flight=900), cnt(rps=24))
    assert d["lvl"] == "bad" and "only manages" in d["t"]
    d = run_diagnose(page, snd(planned=200, sent_s=38, in_flight=40), cnt(rps=10))
    assert d["lvl"] == "bad" and "queueing" in d["t"]
    d = run_diagnose(page, snd(planned=200, sent_s=40, ok_s=40), cnt(rps=40, avg_ms=4000))
    assert d["lvl"] == "warn" and "slow" in d["t"]
    d = run_diagnose(page, snd(planned=200, sent_s=40, ok_s=35, failed_s=5), cnt(rps=40))
    assert d["lvl"] == "bad" and "failing" in d["t"]
    d = run_diagnose(page, snd(planned=200, sent_s=40, ok_s=40, in_flight=3), cnt(rps=40, avg_ms=60))
    assert d["lvl"] == "ok"
    assert run_diagnose(page, None, cnt(rps=3))["lvl"] == "warn"
    assert run_diagnose(page, snd(planned=200, sent_s=40), None)["lvl"] in ("warn", "bad")


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_a_freshly_changed_number_gets_time_to_settle_before_blaming_anyone():
    html = (ROOT / "ui" / "sender.html").read_text(encoding="utf-8")
    fn = re.search(r"function diagnose\(s,c\)\{.*?\n\}\n", html, re.S).group(0)
    script = ("const f1=n=>(Math.round(n*10)/10).toString(), fmt=n=>Number(n).toLocaleString();\nlet lastAsk=null, changedAt=0;\n" + fn +
              f"\nconst c={json.dumps(cnt(rps=24))};\nconst before={json.dumps(snd(planned=100, sent_s=20, ok_s=20))};\n"
              f"const after={json.dumps(snd(planned=2000, sent_s=230, in_flight=900))};\n"
              "diagnose(before,c); console.log(JSON.stringify([diagnose(after,c).lvl]));")
    out = json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)
    assert out == ["ok"] or out == ["warn"]                # the user just changed 100 -> 2000: no verdict about speed for 15 s
