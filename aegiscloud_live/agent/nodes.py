"""
nodes.py - the eight nodes of the graph, plus the few helpers they share.

Every node is a plain function:  node(state) -> dict of the keys it changes.

    1. store_prediction   predict traffic for +10 min, append one row to predictions.csv
    2. trigger_check      choose the mode: unusual > timer > auto
    3. script_creator     write the last-10-minutes report from predictions.csv
    4. llm_unusual        LLM call because something unusual happened
    5. llm_timer          LLM call because the timer is due
    6. auto_scale         no LLM, plain formula
    7. apply_and_log      guardrail, set replicas, write actions.csv   (shared by all three branches)
    8. alert_human        only if something is wrong: the LLM writes an urgent email, it is saved and sent
"""
import csv
import io
import logging
import math
import time

import numpy as np
import pandas as pd

from agent import config as cfg
from agent import health
from agent import llm
from agent import mailer

PRED_COLS = ["minute", "traffic_now", "forecast", "forecast_for", "forecast_h20", "replicas"]
ACTION_COLS = ["minute", "mode", "reason", "traffic_now", "forecast", "replicas_before",
               "proposed", "applied", "action", "decision_reason"]


# ================================================================ helpers
def replicas_for(demand, capacity, min_rep, max_rep):
    """Replicas needed for `demand` requests/min, with headroom, inside the limits."""
    need = math.ceil(demand * (1 + cfg.MARGIN) / capacity)
    return int(min(max_rep, max(min_rep, need)))


READ_ROWS = 300       # the nodes only ever look at the recent past (script = 10 rows, alert report = 60 rows + the forecasts made before them)
_RUN_START = {"pred": 0, "actions": 0}   # file sizes when THIS run began: rows of an older run never count as "recent"


def reset_files():
    """Clear the CSV files and saved alerts. Only used when you ask for it (python -m agent.run --fresh) and by the tests.
    A normal start now APPENDS to the old files, so no history is lost."""
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg.PREDICTIONS_CSV.unlink(missing_ok=True)
    cfg.ACTIONS_CSV.unlink(missing_ok=True)
    cfg.ALERT_DIR.mkdir(parents=True, exist_ok=True)
    for old_alert in cfg.ALERT_DIR.glob("alert_*.txt"):
        old_alert.unlink()
    mark_run_start()


def mark_run_start():
    """Remember where the files end right now. Everything the graph reads afterwards comes from after this point,
    so appending to an old file cannot make the first minutes of a new run look at hours-old rows."""
    for key, path in (("pred", cfg.PREDICTIONS_CSV), ("actions", cfg.ACTIONS_CSV)):
        try:
            _RUN_START[key] = path.stat().st_size
        except FileNotFoundError:
            _RUN_START[key] = 0


def _clean(value):
    """One CSV row must stay one line (an LLM reason with a line break would otherwise break the tail reader)."""
    return " ".join(value.split()) if isinstance(value, str) else value


def append_row(path, cols, row):
    for attempt in range(3):
        try:
            new_file = (not path.exists()) or path.stat().st_size == 0
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                if new_file:
                    w.writeheader()
                w.writerow({k: _clean(v) for k, v in row.items()})
            return
        except OSError as e:                                           # file locked (open in Excel) or disk problem
            if attempt == 2:
                logging.getLogger("agent").warning("could not write one row to %s (%s): row dropped, agent keeps running", path.name, e)
                return
            time.sleep(0.3)


def _tail_rows(path, cols, rows, floor=0):
    """The last `rows` rows of a growing CSV, read from the END of the file (never the whole file) and never from
    before byte `floor`. Returns a DataFrame with the normal columns (empty if there is nothing)."""
    empty = pd.DataFrame(columns=cols)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return empty
    if size <= floor:
        return empty
    block, start, data = 8192, size, b""
    with open(path, "rb") as f:
        while start > floor and data.count(b"\n") <= rows + 1:
            start = max(floor, start - block)
            f.seek(start)
            data = f.read(size - start)
            block *= 2
    lines = data.decode("utf-8", errors="replace").splitlines()
    if start > floor and lines:
        lines = lines[1:]                                              # the first line is probably cut in half
    lines = [ln for ln in lines if ln.strip() and not ln.startswith(cols[0] + ",")][-rows:]
    if not lines:
        return empty
    return pd.read_csv(io.StringIO("\n".join(lines)), names=cols, header=None, on_bad_lines="skip")


def read_predictions(rows=READ_ROWS):
    """Recent rows of agent_ticks.csv for THIS run. Reading is O(rows), not O(file), so an ever-growing log never slows the agent."""
    return _tail_rows(cfg.PREDICTIONS_CSV, PRED_COLS, rows, _RUN_START["pred"])


def read_actions(rows=20):
    return _tail_rows(cfg.ACTIONS_CSV, ACTION_COLS, rows, 0)          # recent decisions of any run are fine context for the LLM


# ================================================================ node 1
def store_prediction(state):
    """The newest tick (traffic + forecasts from the prediction service) goes into the agent's own log."""
    t = state["tick"]
    h20 = t.get("forecast_h20")
    append_row(cfg.PREDICTIONS_CSV, PRED_COLS, {
        "minute": int(t["minute"]),
        "traffic_now": round(float(t["traffic_now"]), 1),
        "forecast": round(float(t["forecast"]), 1),
        "forecast_for": int(t["forecast_for"]),
        "forecast_h20": "" if h20 is None else round(float(h20), 1),
        "replicas": state["replicas"],
    })
    return {"minute": int(t["minute"]), "traffic_now": float(t["traffic_now"]), "forecast": float(t["forecast"]),
            "forecast_h20": None if h20 is None else float(h20)}


# ================================================================ node 2
def unusual_reason(df, state):
    """Plain-code anomaly rules. Returns a sentence, or None if everything looks normal."""
    forecast, traffic = state["forecast"], state["traffic_now"]
    total_cap = state["replicas"] * state["capacity"]

    # 1. forecast jumped compared with the previous minute's forecast
    if len(df) >= 2:
        prev = float(df["forecast"].iloc[-2])
        if prev > 0 and forecast > cfg.SPIKE_RATIO * prev and forecast > cfg.SPIKE_MIN_LOAD * total_cap:
            return f"spike: forecast jumped {100 * (forecast / prev - 1):.0f}% in one minute"

    # 2. forecast or traffic close to the capacity we have (and we can still add replicas)
    if state["replicas"] < state["max_replicas"] and max(forecast, traffic) > cfg.NEAR_CAPACITY * total_cap:
        return f"near capacity: {max(forecast, traffic):.0f}/min against {total_cap:.0f}/min capacity"

    # 3. forecasts made earlier were far from what really happened
    predicted_for = dict(zip(df["forecast_for"], df["forecast"]))
    recent = df.tail(cfg.ERROR_WINDOW)
    pairs = [(predicted_for[m], a) for m, a in zip(recent["minute"], recent["traffic_now"]) if m in predicted_for]
    if len(pairs) == cfg.ERROR_WINDOW:
        wape = sum(abs(p - a) for p, a in pairs) / max(sum(a for _, a in pairs), 1e-9)
        if wape > cfg.ERROR_LIMIT:
            return f"forecast error: {100 * wape:.0f}% over the last {cfg.ERROR_WINDOW} minutes"
    return None


def trigger_check(state):
    df = read_predictions()
    minute = state["minute"]

    if minute - state["last_unusual_minute"] >= cfg.UNUSUAL_COOLDOWN:     # unusual has the highest priority
        why = unusual_reason(df, state)
        if why:
            return {"mode": cfg.MODE_UNUSUAL, "reason": why,
                    "last_unusual_minute": minute, "last_timer_minute": minute}   # also resets the timer

    if minute - state["last_timer_minute"] >= cfg.TIMER_EVERY:
        return {"mode": cfg.MODE_TIMER, "reason": f"timer: {cfg.TIMER_EVERY} minutes since the last check",
                "last_timer_minute": minute}

    return {"mode": cfg.MODE_AUTO, "reason": "nothing unusual and the timer is not due"}


# ================================================================ node 3
def report_table(df, rows_wanted):
    """Text table of the last rows: actual vs what was predicted earlier for that minute.
    Returns (lines, wape_percent or None, number_of_rows)."""
    predicted_for = dict(zip(df["forecast_for"], df["forecast"]))      # minute -> what was predicted for it earlier
    rows = df.tail(rows_wanted)
    lines = ["minute | actual | predicted_earlier | error | forecast_ahead | replicas"]
    abs_err, actual_sum = 0.0, 0.0
    for r in rows.itertuples():
        earlier = predicted_for.get(r.minute)
        if earlier is None:
            earlier_txt, err_txt = "n/a", "n/a"
        else:
            earlier_txt = f"{earlier:.0f}"
            err_txt = f"{100 * (earlier - r.traffic_now) / max(r.traffic_now, 1):+.0f}%"
            abs_err += abs(earlier - r.traffic_now)
            actual_sum += r.traffic_now
        lines.append(f"{r.minute} | {r.traffic_now:.0f} | {earlier_txt} | {err_txt} | {r.forecast:.0f} | {r.replicas}")
    wape = 100 * abs_err / actual_sum if actual_sum > 0 else None
    return lines, wape, len(rows)


def recent_actions_lines(n):
    """The last n rows of actions.csv as sentences."""
    rows = read_actions(n)
    return [f"minute {a.minute}: {a.mode}, replicas {a.replicas_before} -> {a.applied} ({a.action})"
            for a in rows.itertuples()] or ["none yet"]


def script_creator(state):
    table, wape, n = report_table(read_predictions(), cfg.SCRIPT_MINUTES)
    util = state["traffic_now"] / (state["replicas"] * state["capacity"])
    lines = [
        f"App {cfg.APP}, minute {state['minute']}. Capacity {state['capacity']:.0f} requests/min per replica, "
        f"{state['replicas']} replicas running (limits {cfg.MIN_REPLICAS}-{state['max_replicas']}).",
        f"Last {n} minutes (predicted_earlier = forecast made earlier for this minute; "
        f"forecast_ahead = new forecast for the future):",
    ] + table
    if wape is not None:
        lines.append(f"Forecast error in this window (WAPE): {wape:.0f}%")
    lines.append(f"Now: traffic {state['traffic_now']:.0f}/min, forecast {state['forecast']:.0f}/min, utilisation {100 * util:.0f}%.")
    if state.get("forecast_h20") is not None:
        lines.append(f"Longer outlook: forecast {state['forecast_h20']:.0f}/min in 20 minutes.")
    lines.append("Recent actions:")
    lines += recent_actions_lines(3)
    return {"script": "\n".join(lines)}


# ================================================================ nodes 4, 5, 6 (the three branches)
def _facts(state):
    recent = read_predictions().tail(cfg.DOWN_WAIT)
    peak = float(np.maximum(recent["traffic_now"], recent["forecast"]).max())     # highest demand in the last minutes
    return {"traffic_now": state["traffic_now"], "forecast": state["forecast"], "replicas": state["replicas"],
            "capacity": state["capacity"], "min_replicas": cfg.MIN_REPLICAS, "max_replicas": state["max_replicas"],
            "recent_peak": peak,
            "formula_replicas": replicas_for(peak, state["capacity"], cfg.MIN_REPLICAS, state["max_replicas"])}


def llm_unusual(state):
    return {"decision": llm.ask_llm(state["script"], cfg.MODE_UNUSUAL, state["reason"], _facts(state))}


def llm_timer(state):
    return {"decision": llm.ask_llm(state["script"], cfg.MODE_TIMER, state["reason"], _facts(state))}


def auto_scale(state):
    recent = read_predictions().tail(cfg.DOWN_WAIT)                    # the newest row is always included
    demand = float(np.maximum(recent["traffic_now"], recent["forecast"]).max())
    need = replicas_for(demand, state["capacity"], cfg.MIN_REPLICAS, state["max_replicas"])
    current = state["replicas"]
    if state["minute"] - state.get("last_scale_up_minute", -10 ** 9) < cfg.DOWN_WAIT:
        need = max(need, current)                                      # just scaled up: do not undo it (stops flapping)
    action = "scale_up" if need > current else "scale_down" if need < current else "hold"
    return {"decision": {"action": action, "replicas": need,
                         "reason": f"auto: highest demand in the last {len(recent)} min is {demand:.0f}/min, needs {need} replicas"}}


# ================================================================ node 7
def guardrail(proposed, current, max_replicas):
    """Plain code that limits ANY decision (LLM or auto): inside min/max, bounded step size."""
    r = max(cfg.MIN_REPLICAS, min(max_replicas, int(proposed)))
    r = min(r, max(current + 2, int(current * cfg.MAX_UP_MULTIPLIER)))      # at most double (always +2 allowed)
    r = max(r, current - max(1, int(current * cfg.MAX_DOWN_FRACTION)))      # at most -25% (always -1 allowed)
    return max(cfg.MIN_REPLICAS, min(max_replicas, r))


def set_replicas(n):
    """PLACEHOLDER. Later this will call Docker / Kubernetes. For now the new number only lives in the state."""
    pass


def alert_reason_for(state, decision, applied, failures, health_reason=None):
    """Returns a sentence if a human must be told, else None. Plain code, no LLM."""
    if state.get("force_alert"):                                       # tests only: used by test/graph_tester.py, ignores the cooldown
        return "TEST ALERT: forced by graph_tester.py"
    minute = state["minute"]
    if minute - state.get("last_alert_minute", -10 ** 9) < cfg.ALERT_COOLDOWN:
        return None                                                    # an alert was sent recently

    if decision.get("escalate"):                                       # the LLM may only wake a human when plain code also sees high load
        load = max(state["traffic_now"], state["forecast"]) / max(applied * state["capacity"], 1e-9)
        if load > cfg.ESCALATE_MIN_LOAD:
            return f"the LLM asks for a human: {decision['reason']}"
    if failures >= cfg.LLM_FAILURES_BEFORE_ALERT:                      # one failed call is not an emergency
        return f"the LLM failed {failures} times in a row: {decision['reason']}"

    recent = read_predictions().tail(cfg.ALERT_MISS_MINUTES)
    if len(recent) == cfg.ALERT_MISS_MINUTES and (recent["traffic_now"] > recent["replicas"] * state["capacity"]).all():
        return f"traffic was above capacity for {cfg.ALERT_MISS_MINUTES} minutes in a row"
    if applied >= state["max_replicas"] and state["traffic_now"] > applied * state["capacity"]:
        return f"already at the maximum of {applied} replicas and traffic is still above capacity"
    if health_reason:                                                  # what the gateway REALLY measured (agent/health.py)
        return health_reason
    return None


def apply_and_log(state):
    decision = state["decision"]
    before = state["replicas"]
    applied = guardrail(decision["replicas"], before, state["max_replicas"])
    reason_note = ""
    if set_replicas(applied) is False:                                 # the gateway never confirmed: do NOT pretend it worked, the next tick asks again
        applied = before
        reason_note = " [scale command not confirmed by the gateway, will retry next tick]"
    action = "scale_up" if applied > before else "scale_down" if applied < before else "hold"

    if state["mode"] != cfg.MODE_AUTO or applied != before:     # skip the boring "auto + hold" minutes
        append_row(cfg.ACTIONS_CSV, ACTION_COLS, {
            "minute": state["minute"], "mode": state["mode"], "reason": state["reason"],
            "traffic_now": round(state["traffic_now"], 1), "forecast": round(state["forecast"], 1),
            "replicas_before": before, "proposed": decision["replicas"], "applied": applied,
            "action": action, "decision_reason": decision["reason"] + reason_note,
        })

    failures = state.get("llm_failures", 0)
    if decision.get("error"):
        failures += 1                                              # another LLM failure in a row
    elif state["mode"] != cfg.MODE_AUTO:
        failures = 0                                               # the LLM answered, start counting again
    health_run, health_reason = health.check(state.get("health_run"))   # real latency / failures, counted every tick (cooldown is applied below)
    alert = alert_reason_for(state, decision, applied, failures, health_reason)
    out = {"applied": applied, "replicas": applied, "alert_reason": alert or "", "llm_failures": failures, "health_run": health_run}
    if alert:
        out["last_alert_minute"] = state["minute"]                 # start the alert cooldown now
    if applied > before:
        out["last_scale_up_minute"] = state["minute"]              # auto_scale will not scale down for DOWN_WAIT minutes
    return out


# ================================================================ node 8
def alert_human(state):
    """Runs only when alert_reason is set. The LLM writes the email, we save it and (if enabled) send it."""
    minute, reason = state["minute"], state["alert_reason"]
    full = read_predictions()
    last_hour = full.tail(cfg.ALERT_LOG_MINUTES)
    table, wape, n = report_table(full, cfg.ALERT_LOG_MINUTES)
    util = state["traffic_now"] / (state["replicas"] * state["capacity"])
    context = "\n".join([
        f"App {cfg.APP}, minute {minute}. Capacity {state['capacity']:.0f} requests/min per replica, "
        f"{state['replicas']} replicas running (limits {cfg.MIN_REPLICAS}-{state['max_replicas']}).",
        f"Now: traffic {state['traffic_now']:.0f}/min, forecast {state['forecast']:.0f}/min, utilisation {100 * util:.0f}%.",
        f"Last decision: {state['decision']['action']} to {state['decision']['replicas']} replicas ({state['decision']['reason']})",
        f"Last {n} minutes: traffic min {last_hour['traffic_now'].min():.0f}, max {last_hour['traffic_now'].max():.0f}"
        + (f", forecast error (WAPE) {wape:.0f}%." if wape is not None else "."),
        "Recent actions:", *recent_actions_lines(10),
        f"Last {n} minutes in detail:", *table,
    ])
    email = llm.write_alert_email(reason, context)

    attachments = [("last_hour_predictions.csv", last_hour.to_csv(index=False))]
    recent_actions = read_actions(20)
    if not recent_actions.empty:
        attachments.append(("last_actions.csv", recent_actions.to_csv(index=False)))

    if cfg.ALERT_SEND_EMAIL:
        ok, message = mailer.send_email(email["subject"], email["body"], attachments)
    else:
        ok, message = False, "email sending is off (ALERT_SEND_EMAIL = False)"
    status = message if ok else f"saved to file only: {message}"

    cfg.ALERT_DIR.mkdir(parents=True, exist_ok=True)
    path = cfg.ALERT_DIR / f"alert_{minute}_{time.strftime('%Y%m%d_%H%M%S')}.txt"      # unique: an older alert is never overwritten
    path.write_text(f"Subject: {email['subject']}\nStatus: {status}\n\n{email['body']}\n", encoding="utf-8")
    return {"alert_status": f"{status} ({path.name})"}