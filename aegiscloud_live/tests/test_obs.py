"""
test_obs.py - checks Part 1 (logging): the shared setup, the request middleware, the readers, the viewer and the web page.

Run:  python -m pytest tests/test_obs.py -q
Each test name says what it proves. They use a temporary log folder, so your real logs are never touched.
"""
import json
import logging
import time

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import settings as S
from obs import log as obslog
from obs import problems, store, viewer
from obs.middleware import RequestLogMiddleware


@pytest.fixture()
def logdir(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "LOG_DIR", tmp_path)
    return tmp_path


def write(logdir, app, entries):
    with open(logdir / f"{app}.jsonl", "a", encoding="utf-8") as f:
        for t, level, msg in entries:
            f.write(json.dumps({"t": t, "app": app, "level": level, "src": app, "msg": msg}) + "\n")


# ------------------------------------------------------------------ log.py
def test_setup_writes_json_lines_and_console(logdir, capsys):
    root = logging.getLogger()
    saved, saved_marker = list(root.handlers), getattr(root, "_aegis_app", None)
    if saved_marker:
        del root._aegis_app
    try:
        obslog.setup("unit")
        logging.getLogger("unit").warning("hello %s", "world")
        for h in root.handlers:
            h.flush()
        lines = [json.loads(x) for x in (logdir / "unit.jsonl").read_text(encoding="utf-8").splitlines()]
        assert lines[-1]["msg"] == "hello world" and lines[-1]["level"] == "WARNING" and lines[-1]["app"] == "unit"
        assert "hello world" in capsys.readouterr().out
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved:
            root.addHandler(h)
        if hasattr(root, "_aegis_app"):
            del root._aegis_app
        if saved_marker:
            root._aegis_app = saved_marker


def test_warn_every_limits_repeats(caplog):
    lg = logging.getLogger("rate")
    with caplog.at_level(logging.WARNING):
        wrote = [obslog.warn_every("k-test", 60, lg, "same problem") for _ in range(5)]
    assert wrote == [True, False, False, False, False]


# ------------------------------------------------------------------ middleware.py
def make_app(window_s=0.0):
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware, name="mw", hot=("/work",), window_s=window_s)

    @app.get("/work")
    def work(fail: int = 0):
        return JSONResponse({"ok": not fail}, status_code=503 if fail else 200)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/infra/scale")
    def scale():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    return app


def test_hot_path_is_summarised_not_logged_per_request(caplog):
    c = TestClient(make_app(window_s=0.0))
    with caplog.at_level(logging.DEBUG, logger="mw"):
        for _ in range(5):
            c.get("/work")
    work_lines = [r for r in caplog.records if r.name == "mw" and "/work" in r.getMessage()]
    assert 1 <= len(work_lines) <= 5
    assert all("arrived" in r.getMessage() and "still waiting" in r.getMessage() for r in work_lines)


def test_failures_in_a_summary_are_a_warning(caplog):
    c = TestClient(make_app(window_s=0.0))
    with caplog.at_level(logging.INFO, logger="mw"):
        c.get("/work?fail=1")
        c.get("/work")
    assert any(r.levelno == logging.WARNING and "1 failed" in r.getMessage() for r in caplog.records)


def test_rare_calls_are_logged_one_by_one_and_quiet_ones_only_at_debug(caplog):
    c = TestClient(make_app())
    with caplog.at_level(logging.INFO, logger="mw"):
        c.post("/infra/scale")
        c.get("/health")
    msgs = [r.getMessage() for r in caplog.records if r.name == "mw"]
    assert any("POST /infra/scale -> 200" in m for m in msgs)
    assert not any("/health" in m for m in msgs)


def test_exception_is_logged_with_traceback_and_request_id_header_is_set(caplog):
    c = TestClient(make_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="mw"):
        r = c.get("/boom")
        ok = c.get("/health")
    assert r.status_code == 500
    assert any(rec.exc_info and "kaboom" in str(rec.exc_info[1]) for rec in caplog.records)
    assert len(ok.headers["x-request-id"]) == 8


# ------------------------------------------------------------------ problems.py
def test_known_errors_get_a_plain_english_cause():
    assert "Docker" in problems.explain("Docker is not running (or not reachable).")
    assert "prediction service" in problems.explain("prediction service unreachable (row is saved)")
    assert "Ready" in problems.explain("503 no ready replica")


def test_unknown_error_gets_no_explanation():
    assert problems.explain("something nobody has seen before") is None


# ------------------------------------------------------------------ store.py
def test_read_merges_parts_in_time_order_and_filters(logdir):
    now = time.time()
    write(logdir, "gateway", [(now - 5, "INFO", "g1"), (now - 1, "WARNING", "g2 no ready replica")])
    write(logdir, "agent", [(now - 3, "INFO", "a1")])
    assert [d["msg"] for d in store.read()] == ["g1", "a1", "g2 no ready replica"]
    assert [d["msg"] for d in store.read(apps={"agent"})] == ["a1"]
    assert [d["msg"] for d in store.read(level="WARNING")] == ["g2 no ready replica"]
    assert [d["msg"] for d in store.read(q="G1")] == ["g1"]
    assert [d["msg"] for d in store.read(since=now - 2)] == ["g2 no ready replica"]


def test_read_skips_broken_lines(logdir):
    write(logdir, "x", [(time.time(), "INFO", "good")])
    with open(logdir / "x.jsonl", "a") as f:
        f.write("{half a line")
    assert [d["msg"] for d in store.read()] == ["good"]


def test_follower_returns_only_new_lines_and_waits_for_a_half_written_line(logdir):
    write(logdir, "x", [(time.time(), "INFO", "old")])
    fol = store.Follower()
    assert fol.poll() == []                              # starts at the end: history is not repeated
    write(logdir, "x", [(time.time(), "INFO", "new1")])
    assert [d["msg"] for d in fol.poll()] == ["new1"]
    with open(logdir / "x.jsonl", "a") as f:
        f.write('{"t": 1, "app": "x", "level": "INFO", "msg": "par')
    assert fol.poll() == []                              # incomplete line is left for the next poll
    with open(logdir / "x.jsonl", "a") as f:
        f.write('tial"}\n')
    assert [d["msg"] for d in fol.poll()] == ["partial"]


def test_app_status_counts_recent_errors_and_shows_last_seen(logdir):
    now = time.time()
    write(logdir, "gateway", [(now - 2, "INFO", "ok"), (now - 1, "ERROR", "bad")])
    write(logdir, "agent", [(now - 400, "INFO", "old")])
    rows = {r["app"]: r for r in store.app_status(window_s=300)}
    assert rows["gateway"]["errors"] == 1 and rows["gateway"]["last_seen_s"] < 5
    assert rows["agent"]["errors"] == 0 and rows["agent"]["last_seen_s"] > 300


def test_problems_group_repeats_and_attach_cause(logdir):
    now = time.time()
    write(logdir, "collector", [(now - i, "WARNING", f"prediction service unreachable: attempt {i}") for i in range(4)])
    out = store.problems()
    assert len(out) == 1 and out[0]["count"] == 4 and "prediction" in out[0]["why"]


# ------------------------------------------------------------------ viewer.py and web.py
def test_viewer_adds_a_why_line_for_warnings_only():
    warn = viewer.render({"t": time.time(), "app": "g", "level": "WARNING", "msg": "no ready replica"}, color=False)
    info = viewer.render({"t": time.time(), "app": "g", "level": "INFO", "msg": "no ready replica"}, color=False)
    assert "why:" in warn and "why:" not in info


def test_viewer_prints_a_clear_message_when_there_are_no_logs(logdir, capsys):
    assert viewer.main([]) == 0
    assert "No logs yet" in capsys.readouterr().out


def test_web_page_and_api(logdir):
    from obs import web
    now = time.time()
    write(logdir, "gateway", [(now - 1, "WARNING", "503 no ready replica"), (now, "INFO", "fine")])
    c = TestClient(web.app)
    assert c.get("/health").json() == {"ok": True}
    assert "AegisCloud logs" in c.get("/").text
    rows = c.get("/api/logs?level=WARNING").json()
    assert len(rows) == 1 and "Ready" in rows[0]["why"]
    assert c.get("/api/apps").json()[0]["app"] == "gateway"
    assert c.get("/api/problems").json()[0]["count"] == 1
    dl = c.get("/api/download")
    assert "attachment" in dl.headers["content-disposition"] and len(dl.text.splitlines()) == 2
