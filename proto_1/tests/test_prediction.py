import numpy as np
import pandas as pd
import pytest
import torch

import seed as seed_mod
import settings as S
from prediction.engine import Engine, PRED_COLS
from prediction.predictor import Predictor
from prediction.training.train_horizon import METRIC_COLS, make_inputs


def test_predictor_reproduces_the_training_pipeline(fake_df, trained):
    """The live input builder must give the SAME numbers as the training-time one (this is the notebook's recipe)."""
    pred = Predictor(S.MODELS_DIR)
    assert pred.horizons == [10, 20]
    t = 2600
    hist = fake_df.iloc[: t + 1]
    got = pred.forecast(hist)
    for H in (10, 20):
        m = pred.groups[H][0]
        x = np.log1p(fake_df[METRIC_COLS].to_numpy(float))
        seq, st = make_inputs(x, fake_df["minute"].to_numpy(np.int64), np.array([t]), H, m.mu, m.sd)
        with torch.no_grad():
            out = m.model(torch.tensor(seq, dtype=torch.float32), torch.tensor(st, dtype=torch.float32)).item()
        want = max(float(np.expm1(out * m.dsd + x[t, 0])), 0.0)
        assert got[H] == pytest.approx(want, rel=1e-4)


def test_short_history_gives_no_forecast(fake_df, trained):
    assert Predictor(S.MODELS_DIR).forecast(fake_df.iloc[:1000]) == {}


def test_engine_seed_then_live_rows(fake_df, trained):
    S.SEED_CSV.parent.mkdir(parents=True, exist_ok=True)
    fake_df.iloc[:2500].to_csv(S.SEED_CSV, index=False)
    seed_mod._cache.clear()
    eng = Engine(Predictor(S.MODELS_DIR))
    assert eng.status()["ready"] and eng.status()["history_source"] == "seed"
    base = int(fake_df["minute"].iloc[2499]) + 1
    row = fake_df.iloc[2500].to_dict()
    row["minute"] = base
    out = eng.ingest(row)
    assert out and out["forecast_for_h10"] == base + 10 and out["forecast_for_h20"] == base + 20
    assert eng.ingest(row) is None                                        # duplicate minute is ignored
    df = pd.read_csv(S.PRED_CSV)
    assert list(df.columns) == PRED_COLS and len(df) == 1
    assert df["history_source"].iloc[0] == "seed"


def test_engine_without_seed_is_not_ready(trained, tmp_path, monkeypatch):
    monkeypatch.setattr(S, "SEED_CSV", tmp_path / "none.csv")
    monkeypatch.setattr(S, "LIVE_CSV", tmp_path / "live.csv")
    seed_mod._cache.clear()
    assert Engine(Predictor(S.MODELS_DIR)).status()["ready"] is False


def test_checkpoint_with_numpy_mu_loads(fake_df, tmp_path):
    """Your notebook's 2nd save stored mu/sd as numpy arrays; torch.load must still accept it."""
    path = next(S.MODELS_DIR.glob("lstm_h10*.pt"))
    ck = torch.load(path, weights_only=False)
    ck["mu"], ck["sd"] = np.asarray(ck["mu"], dtype=np.float32), np.asarray(ck["sd"], dtype=np.float32)
    (tmp_path / "np.pt").parent.mkdir(exist_ok=True)
    torch.save(ck, tmp_path / "np.pt")
    assert Predictor(tmp_path).horizons == [10]
