# AegisCloud

**A predictive, LLM-governed autoscaler that scales real containers.**

AegisCloud watches live request traffic, forecasts the next 10 minutes with an LSTM, and lets a LangGraph agent decide how many replicas to run. The agent's decisions are applied to **real Docker containers (or Kubernetes Pods)** with enforced CPU and memory limits, so replica start-up delay, overload, and latency are measured, not simulated.

> Status: working research prototype. See [Limitations](#limitations) and `README_research.md` for what has and has not been measured.

---

## How it works

```
 request sender ──► gateway ──► replica 1..N (real containers, 0.5 core / 192 MB each)
 (you control it)      │
                       ▼
                  collector (every tick) ──► live_metrics.csv
                       │
                       ▼
              prediction service (LSTM, +10 min forecast) ──► predictions.csv
                       │
                       ▼
              agent (LangGraph) ──► decides replicas ──► POST /infra/scale ──► ClusterManager
                       │                                                      starts / drains replicas
                       └──► actions.csv, alerts (file + optional email)

              dashboard (Streamlit) reads the CSVs and controls the sender
```

**Time scale:** 1 tick = 5 real seconds = 1 simulated minute (configurable). A "+10 minute" forecast is therefore 50 real seconds ahead. Replica start-up time is real and is **not** scaled, so a 7 s start-up equals about 1.4 ticks.

### The agent (LangGraph)

Eight nodes run once per tick:

`store_prediction → trigger_check → (script_creator → llm_unusual | llm_timer | auto_scale) → apply_and_log → alert_human`

| Mode | When | Who decides |
|---|---|---|
| `auto` | Nothing unusual, timer not due | A rule: replicas needed for the highest demand/forecast in the last 10 ticks |
| `unusual` | Traffic or forecast looks abnormal | The LLM (Gemini or Mistral) |
| `timer` | Every N ticks (default 12) | The LLM |

Proposals are clamped to the device's minimum and maximum replica count. If the LLM fails, the agent holds and the rule-based scaler keeps working. After repeated LLM failures it raises an alert (saved to `data/agent/alerts/`, emailed if configured).

### Real replicas

- **Gateway** (`infra/gateway.py`, port 8001) forwards each request to the least-busy Ready replica and measures end-to-end latency. If no replica is Ready, requests fail with 503, and this is counted as a real failure.
- **ClusterManager** (`infra/manager.py`) keeps the real replica count equal to what the agent asked for. Scale-down drains first. It records the real start-up time of every replica.
- **Backends:** `docker` (limits enforced), `k8s` (Pods of a Deployment), `process` (local processes, no limits, for machines without Docker).
- **Calibration** (`infra/calibrate.py`) measures the requests/s one replica can serve within the latency target (p95 ≤ 500 ms). The agent's capacity per replica comes from this measurement.

---

## Tech stack

Python · PyTorch (LSTM forecaster) · LangGraph (agent) · Google Gemini / Mistral (LLM) · FastAPI + Uvicorn (services) · Docker or Kubernetes (replicas) · Streamlit + Plotly (dashboard) · pandas / NumPy · pytest.

---

## Folder structure

| Folder / file | Purpose |
|---|---|
| `agent/` | LangGraph autoscaler: `graph.py`, `nodes.py`, `llm.py`, `mailer.py`, `feed.py`, `run.py` |
| `prediction/` | `predictor.py` (preprocessing + LSTM), `engine.py`, `server.py` (FastAPI :8004), `training/` (train any horizon / seed), `models/` (`.pt` files) |
| `traffic/` | `loadgen/` (sender and timer), `collector/` (metrics), `target_app/` (demo app) |
| `infra/` | `gateway.py`, `manager.py`, `calibrate.py`, `device.py`, `backends/`, `docker/`, `k8s/`, `experiments/` |
| `frontend/` | Streamlit dashboard |
| `obs/` | Logging, live log viewer |
| `data/` | `seed/` (training CSV), `live/`, `predictions/`, `agent/`, `infra/`, `loadgen/`, `experiments/`, `logs/` (plain CSV/JSON) |
| `tests/` | pytest suite |
| `run_live.py` | **Main entry point** (real replicas) |
| `run_all.py` | Simulated mode (replica count is only a number in a CSV) |

---

## Setup

**Requirements:** Python 3.10+, Docker Desktop (for the `docker` backend), an LLM API key (optional).

```bash
pip install -r requirements.txt -r requirements-infra.txt
```

1. Put your trained **`lstm_requests_forecaster.pt`** (or the files produced by training) in `prediction/models/`.
2. Put **`metrics_combined.csv`** in `data/seed/`. It gives the model its first day of history (1,441 rows are needed before the first forecast).
3. *(Optional)* Create a `.env` file in the **project root** (next to `run_live.py`), or in `agent/`:

```
GEMINI_API_KEY=your_key
# MISTRAL_API_KEY=your_key
EMAIL_SENDER=you@gmail.com
EMAIL_PASSWORD=your_gmail_app_password
EMAIL_TO=receiver@example.com
```

No spaces or quotes around values. On Windows, make sure the file is named exactly `.env`, not `.env.txt`. Never commit it.

---

## Run

```bash
python run_live.py --provider gemini        # real containers + real LLM
python run_live.py                          # real containers, fake (rule-based) LLM
python run_live.py --backend process        # no Docker
python run_live.py --backend k8s            # Kubernetes
python run_live.py --tick 10                # 10 real seconds per simulated minute
python run_live.py --no-agent --no-frontend # baselines (agent off)
```

The first start builds the replica image (about a minute).

| What | URL |
|---|---|
| Dashboard | http://localhost:8501 |
| Live logs (browser) | http://localhost:8006 |
| Gateway / counter | http://localhost:8001 |
| Request sender | http://localhost:8002 |
| Collector | :8003 · Prediction service :8004 · Supervisor API :8005 |

Live logs in a terminal: `python -m obs.viewer --follow`. Ports can be changed with `AEGIS_PORT_*` environment variables.

### Dashboard tabs

`Live` · `Cluster` · `Device & Timer` · `Control` · `Agent` · `Data`

### First-time device setup (dashboard → *Device & Timer*)

1. Enter your cores and RAM and the per-replica share. Press **Apply**.
2. **Stop traffic**, then press **Run calibration** (about one minute). Close other heavy programs while it runs.
3. Press **Apply** again so the agent uses the measured capacity.

> Calibration results can vary between runs. Repeat it 3 times and use the median.

### Sending traffic

From the **Control** tab, or:

```bash
python -m traffic.loadgen.cli start fixed --n 300
python -m traffic.loadgen.cli schedule --in 120 --duration 300 fixed --n 600
python -m traffic.loadgen.cli stop
```

`--n` is requests per tick. One calibrated replica handles roughly its capacity per tick, so choose `--n` above that to force scale-out.

---

## Forecaster training

```bash
python -m prediction.training.train_horizon \
  --data data/seed/metrics_combined.csv \
  --horizons 10 20 --seeds 3 --train-fraction 0.7 --out prediction/models
```

Use `--train-fraction 0.7` for an honest hold-out evaluation (WAPE is printed). Use `1.0` only for the final deployed model. The predictor averages checkpoints of the same horizon.

---

## Experiments

Compare four policies on the same spike (quiet → spike → quiet) with real replicas:

```bash
python run_live.py --no-agent --no-frontend            # baselines need the agent off
python -m infra.experiments.run_experiment --policy static   --static-n 3 --reps 3
python -m infra.experiments.run_experiment --policy reactive --reps 3
python -m infra.experiments.run_experiment --policy hpa      --reps 3

# stop, then restart WITH the agent
python run_live.py --no-frontend --provider gemini
python -m infra.experiments.run_experiment --policy aegis --reps 3

python -m infra.experiments.plot      # summary_table.csv + figures in data/experiments/
```

Useful options: `--base`, `--spike` (requests per tick), `--warmup-ticks`, `--spike-ticks`, `--cooldown-ticks`.

| Policy | Meaning |
|---|---|
| `static` | Fixed number of replicas |
| `reactive` | Sizes replicas for the latest tick's requests plus a margin; scales up at once, scales down after a calm period |
| `hpa` | The Kubernetes HPA rule re-implemented on CPU utilisation (target 60%, 15 s check period, 5 min scale-down window, 10% tolerance), not the real HPA |
| `aegis` | Forecast + LangGraph agent (this project) |

Metrics per run: SLO-miss ticks, failed requests, replica-seconds (cost), start-up times.

---

## Data files

| File | Content |
|---|---|
| `data/live/live_metrics.csv` | Per-tick traffic and latency from the collector |
| `data/predictions/predictions.csv` | Forecasts (+10, +20) per tick |
| `data/agent/actions.csv` | Every logged agent decision, mode, reason |
| `data/agent/agent_ticks.csv` | Per-tick agent state |
| `data/agent/alerts/` | Saved alert messages |
| `data/infra/replica_events.csv` | create / ready / draining / removed events with real start-up seconds |
| `data/infra/cluster_ticks.csv` | Per-tick desired, ready, requests, errors, p95 |
| `data/infra/resources.csv` | Real CPU / memory per replica |
| `data/infra/calibration.json` | Last capacity measurement and its steps |
| `data/loadgen/load_ticks.csv` | Planned vs sent requests per tick |
| `data/experiments/` | Experiment runs and summary table |

Several sessions append to the same CSVs. Separate runs by timestamp, or back up and clear `data/` between experiments.

---

## Tests

```bash
pytest
```

---

## Limitations

- **Time compression:** simulated minutes are 5 real seconds, but container start-up is real time. Start-up delay is therefore large relative to a tick.
- **Single machine, single application:** all replicas share one host with synthetic load.
- **Forecaster:** on the live traffic measured so far the LSTM did not beat a 10-minute moving average (see `README_research.md`). Only the +10 minute model is shipped.
- **Calibration** is a stepped measurement and can vary between runs; capacity is only resolved to the step grid.
- **Traffic sender / gateway stalls** under heavy scaling can turn smooth traffic into bursts. Check `data/loadgen/load_ticks.csv` (planned vs sent).
- **Anomaly trigger:** forecast-error percentage is unstable when traffic is near zero and can trigger unnecessary LLM calls.
- **LLM latency** (15–25 s per call) is several ticks; the agent may skip ticks when it falls behind.
- **HPA baseline** is a re-implementation of the rule, not the real Kubernetes HPA.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `GEMINI_API_KEY is empty` in `data/logs/agent.log` | `.env` is missing, misnamed, or in the wrong folder (use the project root) |
| Agent decisions say "fake LLM" | Start with `--provider gemini` |
| `could not reach the gateway to scale` | The gateway is busy or restarting; check `data/logs/` and retry |
| Replicas never exceed 1 | Traffic per tick is below one replica's capacity; send more with `--n` |
| `calibration already running` | Wait for it to finish; do not press the button twice |
| LLM or email errors with `getaddrinfo failed` | No internet / DNS; the rule-based scaler continues without the LLM |

---

## License and citation

Add your license here. Citation: see `README_research.md`.
