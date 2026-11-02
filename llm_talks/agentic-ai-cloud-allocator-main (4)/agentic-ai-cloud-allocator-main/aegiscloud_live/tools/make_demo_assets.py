"""
make_demo_assets.py - creates FAKE seed data and small FAKE checkpoints so you can see the whole system run
before your real notebook files are copied in. Writes into data/seed/ and prediction/models/ unless told otherwise.

    python tools/make_demo_assets.py                # fake seed + fake H=10 and H=20 models (a minute or two)
    python tools/make_demo_assets.py --epochs 3     # faster, even less accurate

DELETE these files and use your real metrics_combined.csv + lstm_requests_forecaster.pt for anything you report.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import settings as S                                           # noqa: E402
from prediction.training.synthetic import make_synthetic       # noqa: E402
from prediction.training.train_horizon import train_and_save   # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--epochs", type=int, default=8)
    p.add_argument("--seed-out", default=str(S.SEED_CSV))
    p.add_argument("--models-out", default=str(S.MODELS_DIR / "demo"))
    a = p.parse_args()
    df = make_synthetic()
    Path(a.seed_out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.seed_out, index=False)
    print("fake seed written:", a.seed_out)
    for H in S.HORIZONS:
        train_and_save(df, H, a.models_out, seed=0, epochs=a.epochs, train_fraction=0.7)
    print("DEMO ASSETS ONLY - replace with your real data and checkpoints.")


if __name__ == "__main__":
    main()
