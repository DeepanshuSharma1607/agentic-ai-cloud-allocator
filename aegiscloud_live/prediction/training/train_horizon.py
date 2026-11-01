"""
train_horizon.py - train the notebook's LSTM for ANY horizon H (and several seeds), in the checkpoint format
the prediction service loads. Self-contained: it only needs a DataFrame with `minute` + the 8 metric columns.

Why it exists
  * your notebook trained H = 10 only; the dashboard also shows +20 minutes, which needs its own model,
  * a seed ensemble (several checkpoints per horizon) is averaged by the predictor and is usually more accurate,
  * --train-fraction 1.0 retrains on ALL rows for the final deployed model (the 70/30 split is for evaluation).

The maths is the notebook's, line for line: log1p -> standardise with training mu/sd -> 60-row window + 4 static
features -> predict the standardised change in log(requests) H ticks ahead -> 40 epochs of Adam, MSE loss, best
validation epoch kept.

Usage (laptop or Colab):
  python -m prediction.training.train_horizon --data data/seed/metrics_combined.csv \\
         --horizons 10 20 --seeds 3 --train-fraction 1.0 --out prediction/models
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from prediction.lstm_model import MultiFeatureLSTMForecaster

METRIC_COLS = ["requests", "p50_ms", "p95_ms", "p99_ms", "achieved_rps", "app_cpu_pct", "host_cpu_pct", "app_mem_mb"]
TARGET_COL = "requests"
W, DAY = 60, 1440


def build_arrays(df, H, mu=None, sd=None, train_idx=None):
    """Return (x_log, windows-builder inputs) shared by training and evaluation."""
    x = np.log1p(np.clip(df[METRIC_COLS].to_numpy(dtype=np.float64), 0, None))
    return x


def make_inputs(x, minute, idx, H, mu, sd):
    """Sequence (len(idx), W, 8) and static (len(idx), 4) for the rows `idx` (positions), exactly as the predictor builds them."""
    ti = METRIC_COLS.index(TARGET_COL)
    xn = (x - mu) / sd
    seq = xn[idx[:, None] + np.arange(-W + 1, 1)[None, :]]
    yday_t = x[idx - (DAY - H), ti]
    yday_0 = x[idx - DAY, ti]
    phase = 2 * np.pi * (minute[idx] % DAY) / DAY
    static = np.c_[(yday_t - mu[ti]) / sd[ti], (yday_t - yday_0) / sd[ti], np.sin(phase), np.cos(phase)]
    return seq, static


def fit_lstm(seq, st, y, device, epochs=40, batch_size=256, seed=0):
    torch.manual_seed(seed)
    k = int(len(y) * 0.9)                                    # 90% train / 10% validation (chronological), as in the notebook
    t = lambda a: torch.tensor(a, dtype=torch.float32, device=device)
    seq_t, st_t, y_t = t(seq), t(st), t(y)
    model = MultiFeatureLSTMForecaster(seq_t.shape[2], st_t.shape[1]).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=2e-3)
    loss_fn = nn.MSELoss()
    best_loss, best_state = 1e9, None
    for _ in range(epochs):
        model.train()
        perm = torch.randperm(k, device=device)
        for i in range(0, k, batch_size):
            b = perm[i:i + batch_size]
            opt.zero_grad()
            loss_fn(model(seq_t[b], st_t[b]), y_t[b]).backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            val = loss_fn(model(seq_t[k:], st_t[k:]), y_t[k:]).item()
        if val < best_loss:
            best_loss, best_state = val, {n: v.clone() for n, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    return model.eval()


def train_and_save(df, H, out_dir, seed=0, epochs=40, train_fraction=0.7, sampling_seconds=5.0, verbose=True):
    """Train one model and write lstm_h{H}_seed{seed}.pt. Returns (path, test_WAPE or None)."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    df = df.reset_index(drop=True)
    n = len(df)
    ti = METRIC_COLS.index(TARGET_COL)
    x = build_arrays(df, H)
    minute = df["minute"].to_numpy(dtype=np.int64)
    cut = int(n * train_fraction)
    last_train = (n - H - 1) if train_fraction >= 1.0 else (cut - H - 1)
    tr = np.arange(DAY, last_train + 1)                      # rows with a full day of history and a known target H ahead
    mu = x[tr].mean(axis=0)
    sd = np.maximum(x[tr].std(axis=0), 1e-6)

    seq_tr, st_tr = make_inputs(x, minute, tr, H, mu, sd)
    d_tr = x[tr + H, ti] - x[tr, ti]                          # change in log traffic H ticks ahead
    dsd = max(float(d_tr.std()), 1e-6)

    t0 = time.time()
    model = fit_lstm(seq_tr, st_tr, d_tr / dsd, device, epochs=epochs, seed=seed)
    model = model.to("cpu")

    wape = None
    if train_fraction < 1.0:
        te = np.arange(cut, n - H - 1)
        seq_te, st_te = make_inputs(x, minute, te, H, mu, sd)
        with torch.no_grad():
            out = model(torch.tensor(seq_te, dtype=torch.float32), torch.tensor(st_te, dtype=torch.float32)).numpy()
        pred = np.clip(np.expm1(out * dsd + x[te, ti]), 0, None)
        actual = df[TARGET_COL].to_numpy(dtype=float)[te + H]
        wape = float(np.abs(pred - actual).sum() / actual.sum())

    ckpt = {
        "model_name": "lstm", "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
        "metric_cols": list(METRIC_COLS), "target_col": TARGET_COL, "n_features": len(METRIC_COLS), "n_static": 4,
        "hidden": 64, "W": W, "H": int(H), "DAY": DAY,
        "mu": np.asarray(mu, dtype=np.float32).tolist(), "sd": np.asarray(sd, dtype=np.float32).tolist(),
        "dsd": float(dsd), "sampling_seconds": sampling_seconds,
        "seed": int(seed), "train_fraction": float(train_fraction),
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"lstm_h{H}_seed{seed}.pt"
    torch.save(ckpt, path)
    if verbose:
        print(f"H={H:<3} seed={seed} trained in {time.time() - t0:.0f}s  test WAPE={'n/a' if wape is None else f'{wape:.3f}'}  -> {path}")
    return path, wape


def main():
    p = argparse.ArgumentParser(description="Train the notebook LSTM for several horizons / seeds")
    p.add_argument("--data", required=True, help="CSV with a `minute` column and the 8 metric columns (e.g. metrics_combined.csv)")
    p.add_argument("--horizons", type=int, nargs="+", default=[10, 20])
    p.add_argument("--seeds", type=int, default=1, help="how many seeds per horizon (>1 = ensemble)")
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--train-fraction", type=float, default=0.7, help="0.7 = evaluate on the last 30%%; 1.0 = train on everything")
    p.add_argument("--out", default="prediction/models")
    a = p.parse_args()
    df = pd.read_csv(a.data)
    missing = [c for c in ["minute"] + METRIC_COLS if c not in df.columns]
    if missing:
        raise SystemExit(f"{a.data} is missing columns: {missing}")
    for H in a.horizons:
        for seed in range(a.seeds):
            train_and_save(df, H, a.out, seed=seed, epochs=a.epochs, train_fraction=a.train_fraction)


if __name__ == "__main__":
    main()
