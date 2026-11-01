"""
AegisCloud - predict traffic 10 minutes ahead with the saved LSTM.

Put this file in the `notebook` folder. It finds the models and the CSV by itself:

    Major_Project/
        notebook/
            predict.py
            dataset.csv                (or in notebook/data/, or Major_Project/data/)
            models/  app_1.pt app_62.pt ...   (or Major_Project/models/, any sub-folder is fine)

Run (VS Code terminal, from the notebook folder):

    python predict.py --app app_62 --backtest     # should print WAPE close to 0.027
    python predict.py --app app_62                # forecast from the last row in the CSV
    python predict.py --app app_62 --at 15000     # treat minute 15000 as "now"
    python predict.py --all                       # every .pt model found
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

DAY = 1440
HERE = Path(__file__).resolve().parent
ROOTS = [HERE, HERE.parent]                         # notebook/ and Major_Project/
GDRIVE_ID = "1KLtkWrC96XvBm9JVJKpzjrHHfix7wW1K"     # same file the notebook downloads


def find_csv(user_path=None):
    if user_path:
        return Path(user_path)
    for r in ROOTS:
        for rel in ["dataset.csv", "data/dataset.csv", "azure_functions_ranked_timeseries.csv",
                    "data/azure_functions_ranked_timeseries.csv"]:
            if (r / rel).exists():
                return r / rel
    return HERE / "dataset.csv"                     # will be auto-downloaded if gdown is installed


def find_model(app, models_dir=None):
    roots = [Path(models_dir)] if models_dir else [r / "models" for r in ROOTS] + ROOTS
    for r in roots:
        if r.exists():
            hits = [p for p in r.rglob(f"{app}.pt") if ".venv" not in p.parts]
            if hits:
                return hits[0]
    raise SystemExit(f"Could not find {app}.pt. Pass --models <folder with the .pt files>.")


def list_apps(models_dir=None):
    roots = [Path(models_dir)] if models_dir else [r / "models" for r in ROOTS]
    for r in roots:
        if r.exists():
            names = sorted({p.stem for p in r.rglob("*.pt")})
            if names:
                return names
    raise SystemExit("No .pt files found. Pass --models <folder>.")


# ---- model: must be identical to the class in the notebook ------------------
class LSTMForecaster(nn.Module):
    def __init__(self, n_static, hidden=64):
        super().__init__()
        self.lstm = nn.LSTM(1, hidden, batch_first=True)
        self.head = nn.Sequential(nn.Linear(hidden + n_static, 64), nn.ReLU(), nn.Linear(64, 1))

    def forward(self, seq, static):
        _, (h, _) = self.lstm(seq.unsqueeze(-1))
        return self.head(torch.cat([h[-1], static], dim=1)).squeeze(1)


# ---- loading ----------------------------------------------------------------
def load_data(csv_path=None):
    csv_path = find_csv(csv_path)
    if not csv_path.exists():
        try:
            import gdown
        except ImportError:
            raise SystemExit(f"{csv_path} not found. Put the CSV there, or `pip install gdown` to auto-download.")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        gdown.download(f"https://drive.google.com/uc?id={GDRIVE_ID}", str(csv_path), quiet=False)
    return pd.read_csv(csv_path).set_index("minute")


def load_model(pt_path):
    ckpt = torch.load(pt_path, map_location="cpu")
    model = LSTMForecaster(ckpt["n_static"])
    model.load_state_dict(ckpt["state"])
    model.eval()
    return model, ckpt


# ---- the actual prediction --------------------------------------------------
def predict_at(series, positions, model, ckpt):
    """
    series    : pd.Series, traffic per minute for ONE app, index = minute number
    positions : integer positions in `series` that count as "now" (the latest known minute)
    returns   : np.array, predicted traffic at (now + H) for each position

    Needs W minutes of history before "now" and a full day (1440 min) of history for the
    'yesterday' features, so the earliest usable position is DAY.
    """
    W, H = ckpt["W"], ckpt["H"]
    mu, sd, dsd = ckpt["mu"], ckpt["sd"], ckpt["dsd"]

    positions = np.atleast_1d(positions).astype(int)
    if positions.min() < DAY:
        raise ValueError(f"Need at least {DAY} minutes of history before 'now' (position >= {DAY}).")

    x = np.log1p(series.values.astype(float))          # model works on log1p(traffic)
    minutes = series.index.values

    # last W minutes, normalised the same way as in training
    seq = (x[positions[:, None] + np.arange(-W + 1, 1)[None, :]] - mu) / sd

    # 4 static features: yesterday's value, yesterday's change, time of day (sin, cos)
    y_target = x[positions - DAY + H]                  # yesterday, same minute as the target
    y_change = y_target - x[positions - DAY]           # how much it moved yesterday over those H minutes
    tod = minutes[positions] % DAY
    static = np.c_[(y_target - mu) / sd, y_change / sd,
                   np.sin(2 * np.pi * tod / DAY), np.cos(2 * np.pi * tod / DAY)]

    with torch.no_grad():
        out = model(torch.tensor(seq, dtype=torch.float32),
                    torch.tensor(static, dtype=torch.float32)).numpy()

    # model predicts the scaled CHANGE in log traffic; convert back to invocations/min
    return np.clip(np.expm1(out * dsd + x[positions]), 0, None)


# ---- modes ------------------------------------------------------------------
def forecast_now(df, app, models_dir, at=None):
    model, ckpt = load_model(find_model(app, models_dir))
    s = df[app].astype(float)
    pos = len(s) - 1 if at is None else int(np.where(s.index.values == at)[0][0])
    pred = predict_at(s, pos, model, ckpt)[0]
    now_minute = int(s.index[pos])
    return now_minute, float(s.iloc[pos]), float(pred), ckpt["H"]


def backtest(df, app, models_dir):
    model, ckpt = load_model(find_model(app, models_dir))
    H = ckpt["H"]
    s = df[app].astype(float)
    n = len(s)
    cut = int(n * 0.7)                                   # same 70/30 split as the notebook
    pos = np.arange(cut, n - H)                          # same test rows as the notebook
    pred = predict_at(s, pos, model, ckpt)
    actual = s.values[pos + H]
    wape = np.abs(pred - actual).sum() / actual.sum()
    under = (pred < 0.9 * actual).mean()
    over = (pred > 1.1 * actual).mean()
    print(f"{app}: test minutes={len(pos)}  WAPE={wape:.3f}  under_10pct={under:.3f}  over_10pct={over:.3f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default=None)
    p.add_argument("--models", default=None)
    p.add_argument("--app", help="e.g. app_62")
    p.add_argument("--all", action="store_true", help="run for every .pt model found")
    p.add_argument("--at", type=int, help="minute number to treat as 'now' (default: last row)")
    p.add_argument("--backtest", action="store_true", help="score on the 30%% test split")
    a = p.parse_args()

    df = load_data(a.csv)
    apps = list_apps(a.models) if a.all else [a.app]
    if apps == [None]:
        p.error("give --app app_62 or --all")

    for app in apps:
        if a.backtest:
            backtest(df, app, a.models)
        else:
            minute, now_val, pred, H = forecast_now(df, app, a.models, a.at)
            print(f"{app}: at minute {minute} traffic is {now_val:.0f}/min -> "
                  f"forecast for minute {minute + H}: {pred:.0f}/min")


if __name__ == "__main__":
    main()