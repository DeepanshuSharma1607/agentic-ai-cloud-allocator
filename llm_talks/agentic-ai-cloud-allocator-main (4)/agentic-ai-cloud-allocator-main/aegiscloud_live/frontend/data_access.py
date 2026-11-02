"""
data_access.py - everything the dashboard reads or calls. No drawing here.

The dashboard never invents numbers: charts come from the CSV files the other parts write
(live_metrics.csv, predictions.csv, agent_ticks.csv, actions.csv) and controls go to the loadgen / collector APIs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import requests

import seed as seed_mod
import settings as S
from agent import config as agent_cfg


def read_csv(path, tail=None):
    try:
        df = pd.read_csv(path, on_bad_lines="skip")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()
    return df.tail(tail) if tail else df


def api(method, url, **kw):
    """(ok, json-or-error-text). Never raises."""
    try:
        r = requests.request(method, url, timeout=kw.pop("timeout", 4), **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            return False, str(detail)[:300]
        return True, r.json()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def services():
    """{name: True/False} for every part, via its /health endpoint."""
    urls = {"target app": S.URL_TARGET, "collector": S.URL_COLLECTOR, "prediction": S.URL_PREDICTION, "request sender": S.URL_LOADGEN}
    out = {}
    for name, u in urls.items():
        try:
            out[name] = requests.get(f"{u}/health", timeout=0.6).status_code == 200
        except Exception:
            out[name] = False
    return out


def accuracy(pred: pd.DataFrame, live: pd.DataFrame, horizon: int, window=360):
    """Live forecast error, measured only on forecasts whose target minute has already happened.
    Returns {"wape", "naive_wape", "n"}; naive = 'traffic will stay what it is now'."""
    col, tgt = f"forecast_h{horizon}", f"forecast_for_h{horizon}"
    if pred.empty or live.empty or col not in pred or tgt not in pred:
        return None
    actual = live.set_index("minute")["requests"]
    p = pred.dropna(subset=[col, tgt]).copy()
    p = p[pd.to_numeric(p[tgt], errors="coerce").notna()]
    p[tgt] = p[tgt].astype(int)
    p = p[p[tgt].isin(actual.index)].tail(window)
    if len(p) < 3:
        return None
    a = actual.loc[p[tgt]].to_numpy(dtype=float)
    f = p[col].to_numpy(dtype=float)
    now = p["requests_now"].to_numpy(dtype=float)
    return {"wape": float(np.abs(f - a).sum() / max(a.sum(), 1e-9)),
            "naive_wape": float(np.abs(now - a).sum() / max(a.sum(), 1e-9)), "n": int(len(p))}


def training_range():
    st = seed_mod.seed_stats()
    return st["min"], st["max"], st["mean"]


def capacity_per_replica():
    return agent_cfg.CAPACITY_PER_REPLICA or max(1.0, seed_mod.seed_stats()["mean"] / agent_cfg.AVG_REPLICAS)
