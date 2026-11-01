"""The agent graph, run on a scripted list of ticks with the fake LLM (no network, no keys)."""
import math

import pytest

from agent import config as cfg
from agent import graph, nodes
from agent.state import new_state


@pytest.fixture(autouse=True)
def clean_files():
    cfg.LLM_PROVIDER = "fake"
    nodes.reset_files()
    yield


def run_ticks(traffics, forecasts, h20=None):
    app = graph.build_graph()
    cap = 30.0
    state = new_state(cap, 50, 2, 99)
    for i, (t, f) in enumerate(zip(traffics, forecasts)):
        state["tick"] = {"minute": 100 + i, "traffic_now": t, "forecast": f, "forecast_for": 110 + i, "forecast_h20": h20}
        state["force_alert"] = False
        state = app.invoke(state)
    return state


def test_scales_up_for_a_forecast_spike():
    state = run_ticks([60] * 6 + [200] * 4, [60] * 6 + [900] * 4)
    assert state["replicas"] > 2
    assert state["replicas"] * state["capacity"] >= 200


def test_ticks_and_actions_are_written():
    import pandas as pd
    run_ticks([60] * 5, [60] * 5, h20=70)
    ticks = pd.read_csv(cfg.PREDICTIONS_CSV)
    assert len(ticks) == 5 and ticks["forecast_h20"].iloc[0] == 70
    assert cfg.ACTIONS_CSV.exists()


def test_missing_h20_is_fine():
    state = run_ticks([60] * 3, [60] * 3, h20=None)
    assert state["forecast_h20"] is None
    assert math.isfinite(state["forecast"])
