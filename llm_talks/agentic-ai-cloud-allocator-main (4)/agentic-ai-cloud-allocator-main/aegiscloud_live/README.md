# AegisCloud live

Traffic goes in, an LSTM forecasts the next 10 and 20 minutes, an autoscaler agent decides the replicas, and a
dashboard shows all of it live. Built around your notebook's trained model.

```
 request sender ──► target app ──► collector ──► prediction service ──► predictions.csv
 (you control it)   (receives)     (every 5 s,    (notebook preprocessing        │
                                    live_metrics   + LSTM H=10 / H=20)            ▼
                                    .csv)                                    agent (LangGraph) ──► actions.csv, alerts
                                                                                   │
                                          dashboard (Streamlit) reads the CSVs and controls the sender
```

**Time:** 1 tick = 5 real seconds = 1 simulated minute (as in your training data). "Forecast +10 minutes" is therefore
50 real seconds ahead, "+20" is 100 real seconds. The first forecast normally needs 1,441 rows; the seed file removes that wait.

## The five folders

| Folder | What is inside |
|---|---|
| `agent/` | Your LangGraph autoscaler (same 8 nodes, same guardrail). `feed.py` reads live forecasts, `run.py` runs one graph pass per tick. |
| `prediction/` | `predictor.py` (notebook preprocessing + LSTM), `engine.py` (history + CSV), `server.py` (FastAPI :8004), `training/` (train any horizon / seeds), `models/` (put `.pt` files here). |
| `traffic/` | `target_app/` receives requests (:8001), `loadgen/` sends them and has a timer/schedule (:8002), `collector/` gathers the metrics (:8003). |
| `frontend/` | The Streamlit dashboard (:8501): live charts, forecasts, controls, timer, agent log. |
| `data/` | `seed/` (your training CSV), `live/`, `predictions/`, `agent/`, `loadgen/`, `logs/`. All plain CSV. |

## Setup (once)

```bash
pip install -r requirements.txt
```
1. Copy your downloaded **`lstm_requests_forecaster.pt`** into `prediction/models/`.
2. Copy **`metrics_combined.csv`** into `data/seed/` (it gives the model its first day of history and sizes the replicas).
3. Optional: copy `.env.example` to `.env` and add `GEMINI_API_KEY` (or Mistral) for the real LLM.

## Run

```bash
python run_all.py                  # everything, fake LLM in the agent
python run_all.py --provider gemini
python run_all.py --demo           # no files yet? try it with FAKE data and FAKE models first
```
Open **http://localhost:8501**. Use the **Control** tab to send traffic, or the terminal:

```bash
python -m traffic.loadgen.cli start fixed --n 300
python -m traffic.loadgen.cli schedule --in 120 --duration 300 fixed --n 600
python -m traffic.loadgen.cli stop
```
Each part can also be started alone (see the docstring at the top of its file). Logs: `data/logs/`.

## More accuracy (do this once, in your notebook environment)

Your notebook trained H=10 only. This trains the +20 model and a 3-seed ensemble on **all** rows (the predictor averages
checkpoints of the same horizon):

```bash
python -m prediction.training.train_horizon --data data/seed/metrics_combined.csv --horizons 10 20 --seeds 3 --train-fraction 1.0 --out prediction/models
```
Run it first with `--train-fraction 0.7` to see the honest test WAPE for each horizon, and compare with the naive and
moving-average baselines before trusting the model. The dashboard also shows live forecast error versus a naive baseline.
Keep your original `lstm_requests_forecaster.pt` in `prediction/models/` too, or delete it if you only want the new ones.

## Things to know (honest limits)

* **Tested:** the whole chain end to end with FAKE data and tiny FAKE models, 14 automated tests, and the dashboard loads
  without errors. **Not tested:** your real `.pt` file, a real Gemini/Mistral call, and the look of the dashboard in a browser.
* **Out-of-distribution live data.** The LSTM only knows the traffic range of your training data (6 to ~1,136 per tick).
  The dashboard warns when live traffic or any metric drifts far from it. `app_mem_mb` was almost constant in training,
  so the demo app holds ~103 MB of ballast to stay in range; if you monitor a different app, expect to see that warning.
* **Daily pattern.** The model uses "yesterday at the same time" features, so the default `pattern` traffic follows your data's daily curve.
  Fixed or random traffic is legitimate for experiments but is unlike what the model learned.
* **Replicas are simulated** (no Docker yet) and new replicas start instantly. `set_replicas()` in `agent/nodes.py` is the one place to connect real scaling.
* **Capacity per replica** is `mean traffic / 5` from the seed, as in your old agent. Calibrating it from a real load test is the next accuracy step.
* All agent "minutes" settings count ticks: `TIMER_EVERY = 12` is one real minute.
* The load sender can only target the demo app configured in `settings.py` and is capped at `MAX_REQUESTS_PER_TICK`.

## Tests

```bash
python -m pytest
```
They use a temporary folder and fake data, never your `data/`.
