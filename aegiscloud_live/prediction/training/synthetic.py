"""
synthetic.py - FAKE traffic shaped like metrics_combined.csv, for tests and for trying the system before
your real files are copied in. Never use it for results you report.
"""
import numpy as np
import pandas as pd


def make_synthetic(n=20160, seed=0):
    rng = np.random.default_rng(seed)
    m = np.arange(n)
    base = 150 * (1 + 0.6 * np.sin(2 * np.pi * ((m % 1440) - 360) / 1440))
    burst = np.ones(n)
    for s in np.flatnonzero(rng.random(n) < 0.002):
        burst[s:s + rng.integers(3, 10)] *= rng.uniform(2, 6)
    requests = np.clip(rng.poisson(base * rng.lognormal(0, 0.2, n) * burst), 6, None).astype(float)
    util = requests / 600.0
    p50 = 25 + 40 * util ** 2 + rng.normal(0, 2, n)
    p95 = p50 * 2.0 + rng.normal(0, 4, n)
    return pd.DataFrame({
        "minute": m, "requests": requests,
        "p50_ms": np.clip(p50, 5, None), "p95_ms": np.clip(p95, 8, None), "p99_ms": np.clip(p95 * 1.3, 10, None),
        "achieved_rps": requests / 5.0,
        "app_cpu_pct": np.clip(15 + 0.12 * requests + rng.normal(0, 3, n), 1, 100),
        "host_cpu_pct": np.clip(10 + 0.09 * requests + rng.normal(0, 3, n), 1, 100),
        "app_mem_mb": 100 + rng.normal(0, 0.4, n),
    })
