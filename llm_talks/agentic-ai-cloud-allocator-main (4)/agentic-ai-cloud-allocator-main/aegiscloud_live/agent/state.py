"""
state.py - the one dictionary that travels through the whole graph.

Every node receives the state, and returns ONLY the keys it wants to change.
LangGraph merges those keys into the state. Nothing else is shared between nodes.

Two groups of keys:
  - carried keys: kept by run.py from one minute to the next (replicas, timers, capacity)
  - per-minute keys: filled again every minute by the nodes
"""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    # ---- carried from minute to minute (run.py passes them back in) ----
    replicas: int               # replicas running right now
    capacity: float             # requests/min one replica can serve
    max_replicas: int           # upper limit for replicas
    last_timer_minute: int      # minute when the timer LLM check last ran
    last_unusual_minute: int    # minute when the unusual LLM call last ran
    last_alert_minute: int      # minute when the last urgent email was triggered
    llm_failures: int           # LLM failures in a row (alert after LLM_FAILURES_BEFORE_ALERT)
    last_scale_up_minute: int   # minute of the last scale-up (auto_scale will not scale down for DOWN_WAIT minutes after it)

    # ---- node 1: store_prediction ----
    tick: dict                  # the newest row from the prediction service (put here by run.py)
    minute: int                 # minute number of "now"
    traffic_now: float          # real traffic at this minute (requests/min)
    forecast: float             # predicted traffic at minute + 10
    forecast_h20: float         # predicted traffic at minute + 20 (None if no H=20 model is loaded)

    # ---- node 2: trigger_check ----
    mode: str                   # "unusual", "timer" or "auto"
    reason: str                 # why this mode was chosen, in plain words

    # ---- node 3: script_creator ----
    script: str                 # text of the last 10 minutes, given to the LLM

    # ---- branch nodes (llm_unusual, llm_timer, auto_scale) ----
    decision: dict              # {"action": ..., "replicas": ..., "reason": ...}

    # ---- last node: apply_and_log ----
    applied: int                # replicas after the guardrail
    alert_reason: str           # "" = all fine. Any text = something is wrong, alert_human must run

    # ---- alert_human ----
    alert_status: str           # what happened to the urgent email (sent / saved only / failed)
    force_alert: bool           # test only: used by test/graph_tester.py

def new_state(capacity, max_replicas, replicas, start_minute):
    """The starting state, created once by run.py before the first minute."""
    return AgentState(
        replicas=int(replicas),
        capacity=float(capacity),
        max_replicas=int(max_replicas),
        last_timer_minute=int(start_minute),   # the first timer check comes TIMER_EVERY minutes after the start
        last_unusual_minute=-10 ** 9,   # "never": the cooldown must not block the first unusual call
        last_alert_minute=-10 ** 9,     # "never": the first alert must not be blocked
    )