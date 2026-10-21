# AegisCloud

**An agentic autoscaler for any containerized app.** A forecaster and plain-code autoscaler do the daily work. An LLM "governor" wakes up only when needed, changes one safety setting, and asks a human when it is unsure. Every action passes a guardrail written in code.

> **Status (22 Oct 2026):** the forecaster is built and evaluated. The simulator, policy comparison, demo app and agent are **not built yet**. See [Roadmap](#roadmap). Nothing below claims results that do not exist.

---

## Why this project

Normal autoscaling (for example AWS target tracking and predictive scaling) follows simple rules. It cannot:

- say **why** traffic is high (a sale or an attack),
- stop a **runaway** scale-up caused by a bug (for example a memory-leak crash loop) that inflates the bill,
- **explain itself** or ask a human for help.

A forecaster alone is not new, since AWS already offers one. The value here has to come from the **agent layer**: explanations, safety limits, attack-versus-sale reasoning, runaway protection and human escalation.

## Claims to prove

- **A.** Forecast-based scaling uses fewer replicas than a threshold rule at the same or lower SLO-miss time.
- **B.** Under changing conditions, an agent that adjusts headroom and escalates keeps SLO-miss inside a budget, compared with a simple rule-based controller.
- If B shows the agent only matches the controller, that gets reported as is. The likely honest result is "same numbers, plus explanations and escalation".

---

## Architecture

```
App traffic (requests per minute)
   -> Forecaster: predicts traffic 10 to 60 min ahead        (no LLM)
   -> Autoscaler (plain code, always on): sets replica count (no LLM)
         |  short JSON summary, only on a trigger
         v
      LLM governor -> Guardrail (code) -> apply, or message a human
         v
   Audit log (SQLite) + dashboard + evaluation
```

**Autoscaler formula:**
`replicas = predicted traffic / (capacity of one replica x target utilization)`.
Example: one replica handles 100 req/s, target is 60%, forecast is 600, so 10 replicas.

**Headroom** is the single dial: the target utilization. Lower means more spare room (safer, costlier). Higher means cheaper and riskier.

| Part | Job | LLM? |
|---|---|---|
| Forecaster | Predicts future traffic | No |
| Autoscaler | Applies the formula | No |
| LLM governor | Adjusts headroom, explains spikes, stops runaway scaling, escalates | Yes, rarely |
| Guardrail | Checks every decision against fixed rules | No |
| Audit log | Saves every decision with reasons and before/after metrics | No |

**LLM triggers:** capacity short for a sustained period, forecast error suddenly large, or a routine check every 6 hours. It reads a short JSON summary, never raw logs, and is never called per request.

**Allowed actions (allowlist):** change target utilization within bounds and small steps, cap replicas to a budget, switch to a safe static policy, message the engineer with options and a recommendation. It may **never** run commands, delete anything or change code.

### Design decisions

| Decision | Reason |
|---|---|
| No reinforcement learning | Training risk, reward design, hard to defend |
| Real data only | An earlier version used a fake dataset |
| Simple forecaster first, LSTM optional | Keep the LSTM only if it clearly beats the simple model |
| LLM runs rarely, never per request | Token cost and reliability |
| Plain-code fast path always on | Something must keep working while the LLM sleeps |
| Guardrail in code | A system prompt is not a safety mechanism |
| Simulator and evaluation come first | Without them there is no result |

---

## What is built: the forecaster

**Task:** at minute `t`, predict traffic at `t + 10` (a new replica takes about 2 minutes to start, so acting early matters).

**Data:** Azure Functions invocation counts per minute, `azure_functions_ranked_timeseries.csv`: 20,160 minutes (14 days) x 318 apps, no missing or negative values. Six apps were used, chosen from busy to quiet: `app_1, app_62, app_123, app_185, app_248, app_318`. The original Azure trace layout was not re-verified for this README.

**Fair test:** time split 70/30 (no shuffling), features use only the past, and every method is scored on the same test minutes (6,038 per app).

**Methods:** `naive`, `moving_avg`, `yesterday`, `gbm` (HistGradientBoosting on lags, rolling stats, yesterday and time of day), `gbm_q90` (same, 90th percentile), `lstm` (PyTorch, 60-minute window, MSE), `lstm_q90` (pinball loss).

### Results (mean over 6 apps)

| Method | WAPE | under_10pct | over_10pct |
|---|---|---|---|
| lstm | **0.189** | 0.068 | 0.139 |
| gbm | 0.191 | 0.069 | 0.144 |
| gbm_q90 | 0.308 | **0.019** | 0.258 |
| moving_avg | 0.356 | 0.064 | 0.174 |
| yesterday | 0.359 | 0.157 | 0.188 |
| naive | 0.361 | 0.102 | 0.109 |
| lstm_q90 | 0.472 | **0.014** | 0.266 |

- **WAPE** = total absolute error / total traffic (lower is better).
- **under_10pct** = share of minutes predicted more than 10% too low (risk of slowness).
- **over_10pct** = share of minutes predicted more than 10% too high (wasted cost).

### What the numbers really say

1. **LSTM vs GBM is a tie.** The 0.002 gap comes from one bursty app (`app_185`). Without it both score 0.030. One seed, 6 apps.
2. **Simple baselines win on smooth apps.** `moving_avg` beats both learned models on `app_1` and `app_123`.
3. **`app_185` is not solved.** WAPE near 1.0 for every method. This is where the agent layer should matter more than the forecaster.
4. **The 90th-percentile models almost never under-predict**, but over-predict in about 26% of minutes. `gbm_q90` is the better safety option. `lstm_q90` is worse (0.472 vs 0.308).
5. **The final choice between GBM and LSTM is open.** Decide it with simulator results (replica-minutes and SLO-miss minutes), not WAPE alone.

---

## Saved model bundle: `aegiscloud_best_lstm.zip`

| File | Content |
|---|---|
| `app_1.pt, app_62.pt, app_123.pt, app_185.pt, app_248.pt, app_318.pt` | One LSTM per app (about 89 KB each) |
| `meta.json` | `{"method": "lstm", "H": 10, "W": 60, "apps": [...]}` |

Each `.pt` file is a dict with: `state` (weights), `mu`, `sd` (input scaling), `dsd` (output scaling), `n_static` (4), `W` (60), `H` (10).

Models are **per app**. A new app needs its own training run. Exporting the LSTM does not mean it was proven better than the GBM (see above).

### Load a model

The class `LSTMForecaster` is defined in the notebook (1-layer LSTM, hidden 64, then a small head). Copy it into `src/forecaster.py` first.

```python
import torch
ckpt = torch.load("app_62.pt", map_location="cpu")
model = LSTMForecaster(ckpt["n_static"])
model.load_state_dict(ckpt["state"])
model.eval()
```

Inference input: the last `W` minutes of `log1p(traffic)`, normalized with `(v - mu) / sd`, plus 4 static features (yesterday's value, yesterday's change, sin and cos of time of day). The output is a scaled change in log traffic:
`prediction = expm1(out * dsd + log1p(traffic_now))`. The feature code is `make_features` in the notebook.

---

## Repository layout

**Today:**

```
aegiscloud.ipynb               exploration + forecaster comparison (Colab)
aegiscloud_best_lstm.zip       saved LSTM per app
README.md
```

**Planned:**

```
aegiscloud/
  data/            download script only
  src/             loader, forecaster, simulator, policies, controller, metrics
  src/agent/       governor, actions (allowlist), guardrail
  experiments/     one script per experiment
  app/             Streamlit app
  tests/           simulator tests and the five scenarios
  results/         plots and tables
```

## Run the notebook

1. Open `aegiscloud.ipynb` in Google Colab (a T4 GPU speeds up the LSTM).
2. Put `azure_functions_ranked_timeseries.csv` at the path set in the first code cell (the notebook mounts Google Drive).
3. Run all cells. The last cell exports the best trainable model as a zip.

Requirements: Python 3.11, numpy, pandas, matplotlib, scikit-learn, PyTorch, joblib.

---

## Evaluation plan (not run yet)

- **Simulator:** Python, 1-minute steps, replays the trace, includes a replica start-up delay of about 2 minutes. Without it, reactive rules look unfairly good.
- **Policies:** (1) threshold rule, CPU above 70% adds a replica; (2) target-tracking style; (3) forecast plus schedule; (4) forecast plus agent; plus a simple rule-based controller as the honest test for the agent.
- **Metrics:** replica-minutes (cost), minutes with capacity below demand (SLO miss), flapping count, number of agent actions, number of LLM calls.
- **Reporting:** spread over several trace slices, not one number. Time split only, never evaluate on training data.

### Five scenarios (also the agent's acceptance tests)

1. **Routine drift:** shortfalls creep up, the agent raises headroom slightly.
2. **Flash sale:** scale within a budget, explain why.
3. **Attack-like burst:** do not scale blindly, escalate to a human.
4. **Memory-leak crash loop:** stop runaway scaling, report the pattern.
5. **Forecast suddenly wrong:** fall back to the safe static policy and ask the human.

---

## Roadmap

| Phase | Work | Status |
|---|---|---|
| 1 | Data exploration, time split, baselines, GBM and LSTM forecasters | Done |
| 1 | Simulator with start-up delay, SLO-miss and cost metrics, threshold and target-tracking policies | To do |
| 1 | Forecast + schedule policy, results table, cost-versus-miss chart | To do |
| 1 | Streamlit demo with a headroom slider, tests, demo video | To do |
| 2 | Rule-based controller, then LangGraph governor, guardrail, audit log, five scenarios, agent vs controller comparison | To do |
| 3 | Optional: better forecaster (only if it wins), small live demo on K3s with Prometheus and k6, short write-up | To do |

The original plan targeted a working model by 25 Oct 2026. The simulator is the critical missing piece.

## Tech stack

- **Now:** Python 3.11, pandas, numpy, scikit-learn, PyTorch, matplotlib
- **Next:** Streamlit, pytest
- **Agent stage:** LangGraph, pydantic (action schemas), SQLite or JSONL log, any LLM with structured JSON output
- **Optional:** Docker, K3s or kind, Prometheus, k6 or Locust

## Limitations

- Only 6 of 318 apps tested, one seed, one split, 14 days of data.
- WAPE is a forecasting score, not a cost or SLO score. The simulator decides.
- The test data is replayed history, so scaling decisions cannot change user behavior.
- The agent's extra value is the hardest part to measure.
- This is a student portfolio project, not a production autoscaler.
