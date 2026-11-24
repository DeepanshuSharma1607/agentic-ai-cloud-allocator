"""
data_access.py - everything the dashboard reads or calls. No drawing here.

The dashboard never invents numbers: charts come from the CSV files the other parts write
(live_metrics.csv, predictions.csv, agent_ticks.csv, actions.csv) and controls go to the loadgen / collector APIs.
"""
from __future__ import annotations

import io
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import seed as seed_mod
import settings as S
from agent import config as agent_cfg

REFRESH_SECONDS = max(1.0, float(os.getenv("AEGIS_REFRESH_SECONDS", "5")))   # how often the live panels redraw (was 2-3 s: too heavy for one laptop)

_cache = {}                                         # (path, tail) -> (file stamp, DataFrame): a file that did not change is not parsed again


def _tail_bytes(path, size, n):
    """Header + the last n rows, read from the end of the file (a growing CSV is never read from the start)."""
    with open(path, "rb") as f:
        header = f.readline()
        want, start = 4096 + n * 200, max(len(header), size - (4096 + n * 200))
        while True:
            f.seek(start)
            chunk = f.read()
            if chunk.count(b"\n") > n + 1 or start <= len(header):
                break
            want *= 2
            start = max(len(header), size - want)
    if start > len(header):
        chunk = chunk[chunk.find(b"\n") + 1:]            # the first line is probably cut in half
    return header + chunk


def read_csv(path, tail=None):
    path = Path(path)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return pd.DataFrame()
    stamp = (stat.st_mtime_ns, stat.st_size)
    hit = _cache.get((str(path), tail))
    if hit and hit[0] == stamp:
        return hit[1].copy()
    try:
        if tail and stat.st_size > 200_000:
            df = pd.read_csv(io.BytesIO(_tail_bytes(path, stat.st_size, tail)), on_bad_lines="skip")
        else:
            df = pd.read_csv(path, on_bad_lines="skip")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()
    df = df.tail(tail) if tail else df
    _cache[(str(path), tail)] = (stamp, df)
    return df.copy()


_count_cache = {}                                   # path -> (file stamp, rows)
_bytes_cache = {}                                   # path -> (file stamp, bytes)


def count_rows(path):
    """Number of data rows of a CSV, counted once per file change (not at every refresh)."""
    path = Path(path)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return 0
    stamp = (stat.st_mtime_ns, stat.st_size)
    hit = _count_cache.get(str(path))
    if hit and hit[0] == stamp:
        return hit[1]
    with open(path, "rb") as f:
        rows = max(sum(1 for _ in f) - 1, 0)
    _count_cache[str(path)] = (stamp, rows)
    return rows


def file_bytes(path):
    """File content for a download button, re-read only when the file changed (it was re-read at every refresh before)."""
    path = Path(path)
    stat = path.stat()
    stamp = (stat.st_mtime_ns, stat.st_size)
    hit = _bytes_cache.get(str(path))
    if hit and hit[0] == stamp:
        return hit[1]
    data = path.read_bytes()
    _bytes_cache[str(path)] = (stamp, data)
    return data


_down: dict[str, float] = {}                         # host -> time of its last failed GET (see api)
DOWN_COOLDOWN_S = 6.0


def api(method, url, **kw):
    """(ok, json-or-error-text). Never raises. A GET to a host that just failed is skipped for a few seconds, so a stalled
    backend cannot make every dashboard refresh wait for the full timeout again and again."""
    import time as _t
    host = url.split("/", 3)[2] if "://" in url else url
    if method.upper() == "GET" and _t.time() - _down.get(host, 0.0) < DOWN_COOLDOWN_S:
        return False, "service not answering (will retry in a few seconds)"
    try:
        r = requests.request(method, url, timeout=kw.pop("timeout", 4), **kw)
        _down.pop(host, None)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            return False, str(detail)[:300]
        return True, r.json()
    except Exception as e:
        if method.upper() == "GET":
            _down[host] = _t.time()
        return False, f"{type(e).__name__}: {e}"


def services():
    """{name: True/False} for every part, via its /health endpoint (checked in parallel, so one slow part does not slow the dashboard)."""
    urls = {"target app": S.URL_TARGET, "collector": S.URL_COLLECTOR, "prediction": S.URL_PREDICTION, "request sender": S.URL_LOADGEN}

    def up(item):
        try:
            return item[0], requests.get(f"{item[1]}/health", timeout=0.6).status_code == 200
        except Exception:
            return item[0], False

    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(pool.map(up, urls.items()))


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
    return {
        "wape": float(np.abs(f - a).sum() / max(a.sum(), 1e-9)),
        "naive_wape": float(np.abs(now - a).sum() / max(a.sum(), 1e-9)),
        "n": int(len(p)),
    }


def training_range():
    st = seed_mod.seed_stats()
    return st["min"], st["max"], st["mean"]


def capacity_per_replica():
    from infra import config as infra_cfg            # with real replicas the capacity is the calibrated / estimated one
    from infra import runtime as infra_rt
    if infra_cfg.RUNTIME_JSON.exists():
        cap = infra_rt.load().get("capacity_per_tick")
        if cap:
            return float(cap)
    return agent_cfg.CAPACITY_PER_REPLICA or max(1.0, seed_mod.seed_stats()["mean"] / agent_cfg.AVG_REPLICAS)
