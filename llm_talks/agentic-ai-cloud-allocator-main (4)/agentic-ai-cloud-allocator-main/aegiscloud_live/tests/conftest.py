"""Tests run against a throw-away data folder and a tiny model trained on FAKE data. Nothing in your real data/ is touched."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="aegis_test_"))
os.environ["AEGIS_DATA_DIR"] = str(TMP / "data")
os.environ["AEGIS_MODELS_DIR"] = str(TMP / "models")
os.environ["AEGIS_LOADGEN_AUTOSTART"] = ""
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import settings as S  # noqa: E402


@pytest.fixture(scope="session")
def fake_df():
    from prediction.training.synthetic import make_synthetic
    return make_synthetic(n=3400, seed=1)


@pytest.fixture(scope="session")
def trained(fake_df):
    """Tiny models for H=10 and H=20 (2 epochs) written to the temp models dir."""
    from prediction.training.train_horizon import train_and_save
    paths = [train_and_save(fake_df, H, S.MODELS_DIR, seed=0, epochs=2, train_fraction=0.7, verbose=False)[0] for H in (10, 20)]
    return paths
