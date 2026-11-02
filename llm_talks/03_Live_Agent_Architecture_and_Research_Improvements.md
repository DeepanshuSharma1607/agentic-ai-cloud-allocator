# Live Agent Architecture and Research Improvements

## 1. Starting Point and Design Change

The earlier agent replayed an Azure trace and used a one-metric, per-application model. The replacement was designed around the user's newer multivariate LSTM and a controllable live traffic application.

The newer model uses eight input metrics:
`requests`, `p50_ms`, `p95_ms`, `p99_ms`, `achieved_rps`, `app_cpu_pct`, `host_cpu_pct`, and `app_mem_mb`.

It uses a 60-tick history plus four static/time features: same-time-yesterday traffic, yesterday's change, and sine/cosine time-of-day values. It predicts a change in log traffic at H=10. The checkpoint contains preprocessing statistics (`mu`, `sd`, `dsd`) needed to reproduce the notebook.

## 2. Planned and Delivered Project Structure

The new project was organized into five main areas:

```text
aegiscloud_live/
├── agent/       LangGraph autoscaler and LLM layer
├── prediction/  preprocessing, LSTM inference and forecast service
├── traffic/     target app, request sender and collector
├── frontend/    Streamlit controls and live dashboard
└── data/        seed, live, prediction, agent and load-generator records
```

A root configuration, runner, requirements file, README and tests support the folders.

Per tick (5 real seconds = 1 simulated minute):
1. The sender issues requests to the target app.
2. The app records request, latency, CPU and memory metrics.
3. The collector writes a row to `live_metrics.csv`.
4. The collector forwards the row to the prediction service.
5. The service applies notebook-matching preprocessing and saves +10/+20 forecasts.
6. The agent evaluates the forecast and chooses a decision path.
7. The dashboard reads the CSV data and refreshes its views.

The target app measures itself and includes a workload; the sender supports fixed, random, daily-pattern and replay-style traffic, plus scheduled segments. The dashboard has Live, Control, Agent and Data areas.

## 3. LSTM and Agent Behaviour

The predictor:
- Applies `log1p` and saved standardization values to the eight metrics.
- Uses the latest 60 rows and the daily/static features.
- Converts the model output back into a request-count forecast.
- Can average multiple checkpoints for the same horizon.
- Includes a drift warning when live data differs from training data.

The eight-node LangGraph flow was described as:
1. Store prediction.
2. Select unusual, timer or automatic mode.
3. Create a recent-history report.
4. Call the LLM for unusual events.
5. Call the LLM on timer.
6. Use a plain formula for automatic scaling.
7. Apply guardrails and log the action.
8. Alert a human when configured conditions are met.

Guardrails described in the conversation included limiting scale-up to at most 2× per decision, scale-down to at most 25% per decision, and waiting through calm periods before reducing replicas.

## 4. Build and Test Status

The new five-folder project was reported as built and delivered. The 14 existing automated tests passed, including a test that the live input builder reproduced the notebook's training preprocessing. A full fake-data run connected the sender, target app, collector, predictions, agent and dashboard.

Not verified at that point:
- The user's real trained checkpoint.
- A real Gemini or Mistral call.
- Actual browser appearance of the dashboard (the automated load check succeeded).
- Real infrastructure scaling.

The +20 horizon required a separate model-training run; the notebook initially supplied only H=10. Replica actions remained simulated through a placeholder `set_replicas()` function. The target app also used ballast memory to resemble the nearly constant memory values in the training data.

## 5. Forecast Quality and Improvement Ideas

A notebook table in this conversation reported WAPE of 0.158 for LSTM, 0.167 for a 10-tick moving average, 0.172 for GBM and 0.184 for naive forecasting. The LSTM's advantage over the moving average was less than one percentage point and came from a single run, seed and chronological split.

Suggested validation and accuracy improvements:
- Rolling-origin evaluation and multiple seeds.
- LSTM ensembling and blending with GBM.
- Prediction intervals/quantile models and an upper confidence band for safer scaling.
- Keep test data untouched during model selection.
- Use training-like daily-pattern traffic by default and flag out-of-distribution manual loads.
- Track drift and consider retraining only after persistent drift.

Scaling improvements proposed:
- Calibrate per-replica capacity from measured p95 latency and timeout behaviour rather than a simple mean-traffic formula.
- Simulate replica startup delay and queueing.
- Compare static, reactive/HPA-style, forecast-only and agent-assisted policies on SLO-miss minutes and replica-minutes.

## 6. Research Direction Discussed

The most focused proposed research question was: **When does an LLM governor add value in predictive autoscaling?**

The suggested ablation compares formula-only, timer-triggered LLM and unusual-event-triggered LLM across periodic traffic, bursts and drift. A second experiment injects controlled forecast bias, lag and noise to test whether forecasting metrics such as WAPE actually predict scaling outcomes.

Other ideas included a self-demoting agent that tracks LLM regret against the deterministic formula, drift handling with rollback, and publishing the testbed/traces with known burst timestamps.

The conversation estimated about 6–8 weeks part-time for a minimum credible benchmark and 3–4 months for a more complete workshop/conference-oriented effort. These were planning estimates, not completed work.
