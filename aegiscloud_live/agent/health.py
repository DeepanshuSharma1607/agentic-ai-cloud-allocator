"""
health.py - looks at the REAL service (latency and failed requests), so the alert email does not depend only on a capacity guess.

ROLE
    The other alert rules compare traffic with  replicas x capacity.  If that capacity number is wrong (for example an estimate that
    is 3x too high) the service can be slow or failing and no alert ever fires. This file adds one more rule that reads what the
    gateway really measured in the last tick (through the collector's /latest) and counts bad ticks in a row.

HOW IT WORKS
    check(run) -> (new_run, reason or None)
      - a tick is "slow" if p95 > ALERT_P95_MS, "failing" if errors / requests > ALERT_ERROR_RATE (idle ticks change nothing)
      - reason is a sentence once ALERT_P95_TICKS slow ticks or ALERT_ERROR_TICKS failing ticks happened in a row
      - the same minute is never counted twice; if the collector cannot be reached the counters are left alone

REMEMBER
    Switch it off with HEALTH_ALERTS = False in agent/config.py. It only READS; it never changes replicas.
    The usual ALERT_COOLDOWN still applies, so one long problem sends one email, not hundreds.
"""
import requests

import settings as S
from agent import config as cfg

EMPTY = {"minute": -1, "slow": 0, "failing": 0}


def latest_row():
    """The collector's newest row, or None if it cannot be reached (never raises)."""
    try:
        row = requests.get(f"{S.URL_COLLECTOR}/latest", timeout=1.0).json()
        return row if isinstance(row, dict) and row else None
    except Exception:
        return None


def check(run, row=None):
    """Update the counters with the newest gateway row. Returns (counters, alert sentence or None)."""
    run = dict(EMPTY, **(run or {}))
    if not cfg.HEALTH_ALERTS:
        return run, None
    row = row if row is not None else latest_row()
    if not row or int(row.get("minute", -1)) == run["minute"]:
        return run, None
    run["minute"] = int(row["minute"])
    requests_now = float(row.get("requests") or 0)
    if requests_now <= 0:
        return run, None                                             # an idle tick says nothing about health
    slow = float(row.get("p95_ms") or 0) > cfg.ALERT_P95_MS
    failing = float(row.get("errors") or 0) / requests_now > cfg.ALERT_ERROR_RATE
    run["slow"] = run["slow"] + 1 if slow else 0
    run["failing"] = run["failing"] + 1 if failing else 0
    if run["failing"] >= cfg.ALERT_ERROR_TICKS:
        return run, (f"real service is failing: more than {100 * cfg.ALERT_ERROR_RATE:.0f}% of requests failed for "
                     f"{run['failing']} ticks in a row (last tick {row.get('errors')}/{row.get('requests')})")
    if run["slow"] >= cfg.ALERT_P95_TICKS:
        return run, (f"real service is slow: p95 latency above {cfg.ALERT_P95_MS:.0f} ms for {run['slow']} ticks in a row "
                     f"(last tick p95 {float(row.get('p95_ms') or 0):.0f} ms)")
    return run, None
