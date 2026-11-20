"""
test_fixes.py - tests for the fixes of the November 2026 review: append mode, tail reading, mailer, health alert, manager lock.

    python -m pytest tests/test_fixes.py -q
"""
import smtplib
import threading
import time
from unittest import mock

import pandas as pd
import pytest

from agent import config as cfg
from agent import graph, health, mailer, nodes
from agent.state import new_state


@pytest.fixture(autouse=True)
def clean_files():
    cfg.LLM_PROVIDER = "fake"
    nodes.reset_files()
    yield


def run_ticks(n, start=100, state=None):
    app = graph.build_graph()
    state = state or new_state(30.0, 50, 2, start - 1)
    for i in range(n):
        state["tick"] = {"minute": start + i, "traffic_now": 60, "forecast": 60, "forecast_for": start + i + 10, "forecast_h20": None}
        state["force_alert"] = False
        state = app.invoke(state)
    return state


# ------------------------------------------------------------------ 1. history is appended, never wiped
def test_second_run_appends_to_the_files_of_the_first():
    run_ticks(5)
    nodes.mark_run_start()                                             # what run.py does at start (without --fresh)
    run_ticks(4, start=200)
    assert len(pd.read_csv(cfg.PREDICTIONS_CSV)) == 9


def test_fresh_still_clears_when_asked():
    run_ticks(3)
    nodes.reset_files()
    assert not cfg.PREDICTIONS_CSV.exists()


def test_old_alerts_survive_a_normal_start():
    cfg.ALERT_DIR.mkdir(parents=True, exist_ok=True)
    old = cfg.ALERT_DIR / "alert_1_20260101_000000.txt"
    old.write_text("old")
    nodes.mark_run_start()
    assert old.exists()


# ------------------------------------------------------------------ 2. reading stays fast and run-scoped
def test_tail_reader_returns_the_last_rows_of_a_big_file():
    for i in range(3000):
        nodes.append_row(cfg.PREDICTIONS_CSV, nodes.PRED_COLS, {"minute": i, "traffic_now": 1.0, "forecast": 2.0,
                                                                  "forecast_for": i + 10, "forecast_h20": "", "replicas": 1})
    df = nodes.read_predictions(50)
    assert len(df) == 50 and int(df["minute"].iloc[-1]) == 2999 and int(df["minute"].iloc[0]) == 2950


def test_rows_of_an_older_run_are_not_recent():
    run_ticks(6)
    nodes.mark_run_start()
    assert nodes.read_predictions().empty
    run_ticks(2, start=500)
    assert list(nodes.read_predictions()["minute"]) == [500, 501]


def test_reason_with_a_line_break_stays_one_csv_row():
    nodes.append_row(cfg.ACTIONS_CSV, nodes.ACTION_COLS, {"minute": 1, "mode": "timer", "reason": "a\nb", "decision_reason": "x\r\ny"})
    assert len(nodes.read_actions(5)) == 1
    assert len(cfg.ACTIONS_CSV.read_text().strip().splitlines()) == 2


# ------------------------------------------------------------------ 3. mail
def _creds(monkeypatch, password="abcd efgh ijkl mnop", to="b@example.com; c@example.com"):
    monkeypatch.setattr(cfg, "EMAIL_SENDER", "a@example.com")
    monkeypatch.setattr(cfg, "EMAIL_PASSWORD", password)
    monkeypatch.setattr(cfg, "EMAIL_TO", to)


def test_subject_with_line_break_is_sent_and_password_spaces_removed(monkeypatch):
    _creds(monkeypatch)
    with mock.patch("smtplib.SMTP_SSL") as ssl:
        server = ssl.return_value.__enter__.return_value
        ok, msg = mailer.send_email("[URGENT] line one\nline two", "body")
    assert ok, msg
    server.login.assert_called_once_with("a@example.com", "abcdefghijklmnop")
    sent = server.send_message.call_args
    assert "\n" not in sent[0][0]["Subject"] and sent[1]["to_addrs"] == ["b@example.com", "c@example.com"]


def test_wrong_password_gives_a_plain_reason(monkeypatch):
    _creds(monkeypatch)
    with mock.patch("smtplib.SMTP_SSL") as ssl:
        ssl.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
        ok, msg = mailer.send_email("s", "b")
    assert not ok and "APP PASSWORD" in msg


def test_both_ports_blocked_reports_network(monkeypatch):
    _creds(monkeypatch)
    with mock.patch("smtplib.SMTP_SSL", side_effect=OSError("blocked")), mock.patch("smtplib.SMTP", side_effect=OSError("blocked too")):
        ok, msg = mailer.send_email("s", "b")
    assert not ok and "reach" in msg


def test_alert_node_sends_and_saves(monkeypatch):
    _creds(monkeypatch)
    monkeypatch.setattr(cfg, "ALERT_SEND_EMAIL", True)
    with mock.patch("smtplib.SMTP_SSL") as ssl:
        app = graph.build_graph()
        state = new_state(30.0, 50, 2, 99)
        state["tick"] = {"minute": 100, "traffic_now": 60, "forecast": 60, "forecast_for": 110, "forecast_h20": None}
        state["force_alert"] = True
        state = app.invoke(state)
    assert "sent to" in state["alert_status"]
    assert ssl.return_value.__enter__.return_value.send_message.called
    assert list(cfg.ALERT_DIR.glob("alert_*.txt"))


def test_mail_command_check_runs(capsys):
    assert mailer.main(["--check"]) == 0
    assert "EMAIL_SENDER" in capsys.readouterr().out


# ------------------------------------------------------------------ 4. alerts that look at the REAL service
def _row(minute, requests=100, errors=0, p95=100):
    return {"minute": minute, "requests": requests, "errors": errors, "p95_ms": p95}


def test_slow_service_raises_a_health_alert_after_enough_ticks():
    run, why = {}, None
    for m in range(cfg.ALERT_P95_TICKS):
        run, why = health.check(run, _row(m, p95=900))
    assert why and "slow" in why


def test_one_slow_tick_or_idle_ticks_do_not_alert():
    run, why = health.check({}, _row(1, p95=900))
    assert why is None
    for m in range(2, 20):
        run, why = health.check(run, _row(m, requests=0, p95=0))
    assert why is None


def test_failing_requests_raise_a_health_alert():
    run, why = {}, None
    for m in range(cfg.ALERT_ERROR_TICKS):
        run, why = health.check(run, _row(m, errors=40))
    assert why and "failing" in why


def test_same_minute_is_not_counted_twice():
    run, _ = health.check({}, _row(5, p95=900))
    run, _ = health.check(run, _row(5, p95=900))
    assert run["slow"] == 1


def test_unreachable_collector_never_raises():
    with mock.patch("requests.get", side_effect=OSError("down")):
        run, why = health.check({})
    assert why is None


def test_graph_sends_an_alert_for_a_slow_service(monkeypatch):
    _creds(monkeypatch)
    monkeypatch.setattr(cfg, "ALERT_SEND_EMAIL", True)
    app = graph.build_graph()
    state = new_state(1000.0, 50, 2, 99)                               # huge capacity: the OLD rules can never fire
    with mock.patch("smtplib.SMTP_SSL"):
        for i in range(cfg.ALERT_P95_TICKS):
            state["tick"] = {"minute": 100 + i, "traffic_now": 60, "forecast": 60, "forecast_for": 110 + i, "forecast_h20": None}
            state["force_alert"] = False
            with mock.patch.object(health, "latest_row", return_value=_row(100 + i, p95=900)):
                state = app.invoke(state)
    assert state["alert_reason"].startswith("real service is slow")


# ------------------------------------------------------------------ 5. routing is not blocked while Docker works
def test_gateway_routing_is_not_blocked_while_a_container_is_created():
    from infra.backends.base import Backend
    from infra.device import Device
    from infra.manager import ClusterManager

    class SlowBackend(Backend):
        name, per_pod_routing, isolated = "slow", True, True

        def __init__(self):
            self.made = []

        def prepare(self, spec, build=False):
            pass

        def observe(self):
            return []

        def create(self, count, spec):
            time.sleep(1.0)                                            # Docker is slow
            self.made += ["r1"]
            return ["r1"]

        def remove(self, name):
            pass

        def stats(self):
            return {}

        def cleanup(self):
            pass

    mgr = ClusterManager(SlowBackend(), Device(), 1.0)
    mgr.set_desired(1)
    t = threading.Thread(target=mgr.reconcile)
    t.start()
    time.sleep(0.2)                                                    # reconcile is now inside the slow create()
    t0 = time.time()
    mgr.pick()
    mgr.counts()
    assert time.time() - t0 < 0.3, "routing had to wait for Docker"
    t.join()
