"""
predictor.py - turns the latest rows of live metrics into the exact input of your notebook's LSTM and predicts.

Notebook recipe, reproduced step by step (all per checkpoint, because mu / sd / dsd / H are stored in it):

  1. x      = log1p(8 metrics)                               (negative values are clipped to 0 first)
  2. window = (x[t-W+1 .. t] - mu) / sd                       -> the (W, 8) sequence
  3. static = [ (x_req[t-DAY+H] - mu_req) / sd_req,           yesterday's value at the moment we forecast
                (x_req[t-DAY+H] - x_req[t-DAY]) / sd_req,     how much yesterday changed over the same span
                sin(2*pi*(minute % DAY)/DAY),
                cos(2*pi*(minute % DAY)/DAY) ]
  4. out    = LSTM(window, static)
  5. forecast(t+H) = expm1( out * dsd + x_req[t] )  clipped at 0

So the history needs at least DAY + 1 consecutive rows (1,441). Several checkpoints for the same H are
averaged in log space (a cheap seed ensemble).
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch

from prediction.lstm_model import MultiFeatureLSTMForecaster

log = logging.getLogger("predictor")
CLIP_Z = 12.0      # safety only: a standardised input beyond +-12 sd (never seen in training) is cut, so one broken metric cannot blow up the LSTM


class LoadedModel:
    def __init__(self, path: Path):
        ckpt = torch.load(path, map_location="cpu", weights_only=False)     # mu/sd may be numpy arrays
        self.path = Path(path)
        self.name = ckpt.get("model_name", "lstm")
        self.H = int(ckpt["H"])
        self.W = int(ckpt["W"])
        self.DAY = int(ckpt["DAY"])
        self.metric_cols = list(ckpt["metric_cols"])
        self.target_col = ckpt["target_col"]
        self.ti = self.metric_cols.index(self.target_col)
        self.mu = np.asarray(ckpt["mu"], dtype=np.float64)
        self.sd = np.maximum(np.asarray(ckpt["sd"], dtype=np.float64), 1e-6)
        self.dsd = float(ckpt["dsd"])
        self.sampling_seconds = ckpt.get("sampling_seconds")
        model = MultiFeatureLSTMForecaster(int(ckpt["n_features"]), int(ckpt["n_static"]), int(ckpt.get("hidden", 64)))
        model.load_state_dict(ckpt["state_dict"])
        self.model = model.eval()


class Predictor:
    def __init__(self, models_dir: Path):
        self.models_dir = Path(models_dir)
        self.groups: dict[int, list[LoadedModel]] = {}
        for path in sorted(self.models_dir.rglob("*.pt")):
            try:
                m = LoadedModel(path)
            except Exception as e:                                           # a broken file must not stop the service
                log.warning("could not load %s: %s", path, e)
                continue
            self.groups.setdefault(m.H, []).append(m)
        self.horizons = sorted(self.groups)

    # ------------------------------------------------------------------ info
    @property
    def ready(self):
        return bool(self.groups)

    def describe(self):
        return {str(h): [m.path.name for m in ms] for h, ms in self.groups.items()}

    def rows_needed(self):
        return max((m.DAY + 1 for ms in self.groups.values() for m in ms), default=1441)

    # ------------------------------------------------------------------ prediction
    @staticmethod
    def _logx(hist, m: LoadedModel):
        return np.log1p(np.clip(hist[m.metric_cols].to_numpy(dtype=np.float64), 0, None))

    def _one(self, hist, m: LoadedModel):
        x = self._logx(hist, m)
        t = len(x) - 1
        if t < m.DAY or t < m.W - 1:
            return None
        window = np.clip((x[t - m.W + 1: t + 1] - m.mu) / m.sd, -CLIP_Z, CLIP_Z)
        yd = x[t - (m.DAY - m.H), m.ti]
        yd0 = x[t - m.DAY, m.ti]
        phase = 2 * np.pi * (int(hist["minute"].iloc[-1]) % m.DAY) / m.DAY
        static = np.array([(yd - m.mu[m.ti]) / m.sd[m.ti], (yd - yd0) / m.sd[m.ti], np.sin(phase), np.cos(phase)])
        with torch.no_grad():
            out = m.model(torch.tensor(window[None], dtype=torch.float32),
                          torch.tensor(static[None], dtype=torch.float32)).item()
        return out * m.dsd + x[t, m.ti]                                       # forecast in log space

    def forecast(self, hist):
        """{H: forecast of requests at minute+H} for every loaded horizon, or {} if the history is too short."""
        result = {}
        for h, models in self.groups.items():
            logs = [v for v in (self._one(hist, m) for m in models) if v is not None]
            if logs:
                result[h] = float(max(np.expm1(np.mean(logs)), 0.0))
        return result

    # ------------------------------------------------------------------ drift check (are live inputs like the training data?)
    def drift(self, hist):
        """Mean standardised distance of the last W rows from the training mean, per metric.
        Returns (worst_abs_z, worst_metric). Above ~3 the live data looks unlike the training data."""
        if not self.groups:
            return 0.0, ""
        m = next(iter(self.groups.values()))[0]
        x = self._logx(hist.tail(m.W), m)
        z = (x.mean(axis=0) - m.mu) / m.sd
        i = int(np.argmax(np.abs(z)))
        return float(abs(z[i])), m.metric_cols[i]
