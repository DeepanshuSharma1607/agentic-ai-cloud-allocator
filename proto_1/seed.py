"""
seed.py - reads data/seed/metrics_combined.csv (your training data) and answers small questions about it.

The seed gives the prediction service its first day of history, so forecasts start immediately instead of
after 1,441 live ticks (about 2 hours). Everything here returns None when the file is missing.
"""
import numpy as np
import pandas as pd

import settings as S

_cache = {}


def load_seed():
    """DataFrame with columns minute + the 8 metrics, or None if the seed file does not exist."""
    if not S.SEED_CSV.exists():
        return None
    key = (str(S.SEED_CSV), S.SEED_CSV.stat().st_mtime)
    if key not in _cache:
        df = pd.read_csv(S.SEED_CSV)
        missing = [c for c in ["minute"] + S.METRIC_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"{S.SEED_CSV.name} is missing columns: {missing}")
        _cache.clear()
        _cache[key] = df[["minute"] + S.METRIC_COLS].astype(float).reset_index(drop=True)
    return _cache[key]


def seed_tail(rows):
    df = load_seed()
    return None if df is None else df.tail(rows).reset_index(drop=True)


def seed_stats():
    """Mean / max / min of requests in the seed, used to size capacity and to scale generated traffic."""
    df = load_seed()
    if df is None:
        return {"mean": 150.0, "max": 1100.0, "min": 6.0, "rows": 0}
    r = df["requests"]
    return {"mean": float(r.mean()), "max": float(r.max()), "min": float(r.min()), "rows": int(len(df))}


def daily_profile():
    """1,440 multipliers (mean = 1): the typical shape of one simulated day. Falls back to a smooth sine."""
    df = load_seed()
    if df is None or len(df) < S.DAY:
        m = np.arange(S.DAY)
        return 1.0 + 0.6 * np.sin(2 * np.pi * (m - 360) / S.DAY)
    daily = df.groupby(df["minute"].astype(int) % S.DAY)["requests"].mean().reindex(range(S.DAY)).interpolate().bfill().ffill()
    ext = pd.concat([daily.iloc[-30:], daily, daily.iloc[:30]]).rolling(31, center=True, min_periods=1).mean().iloc[30:-30]
    return (ext / ext.mean()).to_numpy()


def next_minute():
    """The minute number the collector should use next: after the live file, else after the seed, else 0."""
    if S.LIVE_CSV.exists() and S.LIVE_CSV.stat().st_size > 0:
        try:
            live = pd.read_csv(S.LIVE_CSV, usecols=["minute"], on_bad_lines="skip")
            if len(live):
                return int(live["minute"].iloc[-1]) + 1
        except (ValueError, pd.errors.ParserError):
            pass
    df = load_seed()
    return 0 if df is None else int(df["minute"].iloc[-1]) + 1
