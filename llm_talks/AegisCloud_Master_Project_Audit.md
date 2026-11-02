# AegisCloud — Master Project Audit and Research Readiness Report

**Project:** AegisCloud — Agentic AI-Based Predictive Cloud Resource Management  
**Audit date:** 2 November 2026  
**Audit scope:** Uploaded `Major_Project.zip`, including the nested `agent.zip`, every project Python source file, all Markdown and text documentation, the Jupyter notebook and saved outputs, monitoring configuration/dashboard JSON, the project paper draft, and all six supplied research PDFs.

> **Audit conclusion.** AegisCloud is a reproducible-in-principle, trace-replay research prototype for forecast-aware replica-count decisions. It combines a ten-minute-ahead LSTM workload forecast, deterministic trigger and scaling logic, optional Gemini/Mistral decision review, a deterministic guardrail, CSV audit logs, alert generation, and Prometheus/Grafana instrumentation. The uploaded implementation does **not** provision real containers, Kubernetes pods, or cloud resources: `agent/nodes.py::set_replicas()` is an explicit `pass` placeholder. Further, the uploaded archive does not contain the dataset CSV or any trained `.pt` checkpoint required to instantiate the forecaster. Historical test results are documented, but cannot be independently reproduced from this archive alone.

---

## Executive assessment

| Dimension | Audit assessment | Evidence |
|---|---|---|
| Problem definition | Clear: reduce the lag and uncertainty of purely reactive scaling by forecasting per-application request demand and deciding replica counts with headroom. | `README.md` Sections Project goals, Architecture; `agent/config.py`; `notebook/predict.py` |
| Implemented forecasting | A single-variable LSTM forecaster per application, with a 60-minute input window and a nominal 10-minute horizon in the saved experiment. | `notebook/lstm_model.ipynb`; `notebook/predict.py::LSTMForecaster`, `predict_at`; `models/meta.json` |
| Controller | Implemented as a LangGraph state machine with unusual-event LLM review, timer-based LLM review, and deterministic auto-scaling paths. | `agent/graph.py::build_graph`; `agent/nodes.py` |
| Safety layer | Min/max clamping and bounded replica-count step changes are implemented. | `agent/nodes.py::guardrail`; `agent/config.py` |
| Real infrastructure actuation | **Not implemented.** Replica changes only update the in-memory graph state. | `agent/nodes.py::set_replicas()` |
| Agentic sophistication | A bounded, single-controller workflow with an LLM decision node; not a multi-agent system, RL controller, tool-using cloud operator, or autonomous deployment manager. | `agent/graph.py`; `agent/llm.py`; comparison with MOYA / SSRN papers |
| Observability | Prometheus exporter, Grafana provisioning, and 21 dashboard panels are included. The process/host metrics describe the allocator host/process, not the target application container. | `agent/metrics.py`; dashboard JSON; `MONITORING.md` |
| Evidence/reproducibility | Historical logs and a notebook with outputs exist. The archive lacks the dataset and model checkpoints, has no dependency lockfile, and has no CI. | `output/test_output.md`; `notebook/lstm_model.ipynb`; `requirements.txt`; `fixes/fix_to_do.md` |
| Security | **High-priority issue:** nested `agent.zip` contains a populated `.env` with API credentials, email credentials, and a Grafana password. Secret values are intentionally not reproduced here. | `agent.zip` → `.env`; `.gitignore` does not exclude `agent.zip` |

### Most important findings

1. **No live cloud scaling:** `set_replicas()` is empty. “Applied replicas” means a simulated integer, not a Docker/Kubernetes/cloud operation (`agent/nodes.py`, lines 231–233, 259–285).
2. **The archive is not self-contained:** no CSV dataset and no `.pt` model checkpoint are present. `Feed.__init__()` requires both (`agent/nodes.py`, lines 68–79); `notebook/predict.py::find_model()` exits if the model is missing (lines 44–52).
3. **The reported LSTM advantage is tiny:** mean WAPE is 0.189 for LSTM versus 0.191 for HistGradientBoosting, an absolute gap of 0.002. The draft correctly says this does not establish LSTM superiority; per-application results are mixed (`notebook/lstm_model.ipynb`, `notebook/notebook_readme.md`, draft Table 4/5).
4. **Forecast failures can be severe on bursty applications:** the saved `app_185` history in nested `agent.zip` records traffic of 6,921 requests/min against a forecast of 5.8 requests/min. The notebook reports `app_185` WAPE near 0.98. The guardrail limits ramp speed, and the scaler is only simulated; no startup-delay or service-level evaluation is present.
5. **Research-paper methods are mostly background, not implemented algorithms:** DeepRM's REINFORCE cluster scheduler, PASM's scaling/migration formulas, Borg's production scheduler/Autopilot, and MOYA's multi-agent agent registry are not present in AegisCloud code.
6. **Security must be addressed before further sharing:** rotate all credentials found in the nested `.env`; remove the populated archive from distribution/history; keep only placeholders in `.env.example`.

---

# 1. High-level project purpose and core problem statement

## 1.1 The problem AegisCloud targets

A cloud-hosted application receives a request stream that changes over time. A purely reactive autoscaler observes current CPU/request load, waits for a threshold/window, and then adds or removes replicas. Reactive scaling can be late during a burst and wasteful when capacity remains allocated after demand falls. AegisCloud targets this control problem at the **application replica-count level**: forecast near-future request volume, estimate how many replicas are required, decide whether to change the count, bound the proposed change, and alert an operator when the controller cannot safely handle the condition.

The project's own README frames the goal as forecast-aware resource allocation and reduced under/over-provisioning (`README.md`, lines 32–90). Its architecture image shows a historical Azure Functions invocation trace feeding a forecast model, trigger evaluation, a rule/LLM decision path, guardrail, and simulated action with logging/monitoring. The data source and target are therefore narrower than a general cloud resource manager: this implementation operates on **per-minute invocations for one selected application**, not on CPU, memory, storage, network, placement, or an entire cluster scheduler (`agent/nodes.py::Feed`; `notebook/predict.py::load_data`).

## 1.2 What the system is designed to do

At a high level, the implemented workflow is:

1. Load one application's minute-level traffic series and its saved LSTM checkpoint.
2. Start replay at the nominal 70% train/test boundary, with at least one day of history available to compute the model's daily seasonal features.
3. At each replay minute, produce a forecast for `minute + H` (the notebook checkpoint uses `H=10`) and append the observed and forecast values to a prediction CSV.
4. Evaluate unusual-event rules: forecast spike, near-capacity load, or recent forecast error.
5. If an unusual event is detected, call the configured LLM provider; if a periodic timer is due, call the LLM; otherwise use a deterministic formula.
6. Apply replica min/max and rate-of-change guardrails.
7. Record the applied simulated count, decision, and any alert; optionally generate and send an email; optionally expose Prometheus metrics.

This is visible in `agent/graph.py::build_graph`, `agent/nodes.py::store_prediction`, `trigger_check`, `auto_scale`, `guardrail`, `apply_and_log`, and `alert_human`.

## 1.3 What the project is not (at the audited revision)

The name and early descriptions can suggest a general autonomous cloud resource manager. The code does not currently demonstrate that breadth. It is not:

- a live Docker, Kubernetes, AWS, Azure, or GCP scaler;
- a cluster scheduler that places jobs on machines or packs multiple resource dimensions;
- an RL policy trained from rewards or an online learning controller;
- a multi-agent framework with agent discovery/registry, tool delegation, RAG, or shared semantic memory;
- a validated cost optimizer using cloud invoices/pricing APIs;
- a real-time stream processor consuming production telemetry.

The explicit placeholder in `agent/nodes.py::set_replicas()` and the architecture image's replay-only note are decisive evidence. `agent/metrics.py` also labels several measures as replay/simulated quantities.

## 1.4 Suitable research framing

A defensible research framing for the next paper is:

> **A trace-replay evaluation framework for forecast-aware, guardrail-constrained replica-count control, in which a lightweight LSTM forecast informs a hybrid deterministic/LLM decision policy and all actions are audited.**

This framing is accurate for the current code. Claims of “autonomous cloud resource management,” “production auto-scaling,” “multi-agent orchestration,” or “improved QoS/cost” require additional implementation and controlled evidence.

---

# 2. Architecture and component breakdown

## 2.1 End-to-end architecture

### Offline model preparation

`notebook/lstm_model.ipynb` loads a minute-indexed Azure Functions traffic matrix, selects six representative application series, engineers features and trains/evaluates forecasting baselines. It saves the selected best model checkpoints to `.pt` files. `models/meta.json` records only method/window/horizon/application metadata; it is **not** a model checkpoint.

### Replay/controller runtime

`agent/run.py` parses CLI options, checks setup, constructs `Feed`, initializes the LangGraph state, optionally starts the Prometheus exporter, and iterates through the held-out trace. One dataset minute is processed per graph invocation. `TICK_SECONDS` controls real wall-clock delay between replay iterations; its default is one second, so a simulated minute is not one real elapsed minute.

### Decision graph

The graph runs `START → store_prediction → trigger_check → script_creator`. It then selects exactly one decision path: `llm_unusual` for a detected unusual event, `llm_timer` when the periodic timer is due, or `auto_scale` otherwise. All three paths converge at `apply_and_log`. From there, the graph calls `alert_human` when an alert condition is met; otherwise it ends without the alert node.

The source graph has eight nodes, even though the introductory docstring in `nodes.py` says “six nodes” before listing eight logical nodes. `graph.py` defines the actual node/edge topology (`agent/graph.py`, lines 33–56). The three routes are mutually exclusive: unusual > timer > auto (`agent/graph.py::route_mode`; `agent/nodes.py::trigger_check`).

### Monitoring and notification sidecar

The optional exporter exposes `/metrics` on port 8000 by default, Prometheus scrapes it, and Grafana provisions the datasource/dashboard using Docker Compose. The alert path saves text files and can attach the latest prediction/action CSV excerpts to SMTP email. Monitoring is auxiliary; it does not perform resource orchestration.

## 2.2 Python files: full module map

| File | Main responsibilities and important functions | Inputs / outputs / interactions |
|---|---|---|
| `agent/__init__.py` | Empty package marker. | No runtime logic. |
| `agent/config.py` | Central paths and constants; `load_dotenv`; selected app, replay position, capacity inference, thresholds, cooldowns, SMTP settings, model/provider names. | Imported by almost every agent module. Defaults include `APP=app_62`, 70% start, `TICK_SECONDS=1`, timer 5, margin 10%, `LLM_PROVIDER=fake` (`lines 8–18, 20–31, 34–79`). |
| `agent/state.py` | `AgentState` TypedDict and `new_state()`. Carries minute position, traffic/forecast, replica/capacity bounds, selected mode/reason, decision, applied count, alert fields, timer/cooldown and failure counters. | Shared graph state; initial values from runtime `Feed` (`lines 14–57`). |
| `agent/graph.py` | `route_mode()`, `route_alert()`, `build_graph()`. Wires eight LangGraph nodes and conditional branches. | Receives a `Feed`; returns compiled graph (`lines 19–56`). |
| `agent/nodes.py` | Primary business logic: `replicas_for`, CSV reset/append/read, `Feed`, `make_store_prediction`, `unusual_reason`, `trigger_check`, report builder, LLM facts, branches, `auto_scale`, `guardrail`, `set_replicas`, alert policy, `apply_and_log`, `alert_human`. | Consumes forecaster and config; calls `llm.py`, `mailer.py`; emits prediction/action/alert files (`lines 15–30`, functions at 36–300+). |
| `agent/llm.py` | Prompts, fake provider, HTTP retry wrapper, Gemini/Mistral calls, JSON parsing/sanitization, safe failure response, alert-email drafting. | Accepts report/reason/facts; returns normalized decision dict or hold on error (`lines 26–210`). |
| `agent/mailer.py` | `send_email()` builds MIME email with CSV attachments; tries Gmail SSL 465 then STARTTLS 587; returns success/error instead of propagating exceptions. | Called from `alert_human()` (`lines 16–39`). |
| `agent/metrics.py` | `AllocatorMetrics` registers Prometheus gauges/counters/histogram, starts HTTP exporter, samples process/host resource stats, records each replay tick. | Called by `run.py`; emits metrics for simulated state and allocator process/host (`class at lines 15 onward`). |
| `agent/run.py` | `positive_int`, `parse_args`, `check_setup`, `main`; sets up runtime; replays trace; prints summary; handles interruption and optional exporter lifetime. | CLI entry point; uses graph, Feed, config, metrics (`lines 26–162`). |
| `notebook/predict.py` | Dataset/model discovery; `LSTMForecaster`; load model/data; `predict_at`; one-step forecast; backtest metrics; CLI. | Imported by `agent/nodes.py` and used for offline prediction (`lines 27–185`). |
| `test/graph_tester.py` | Integration-style graph test with forced unusual event and test alert, expected node sequence and CSV checks. | Needs real data/checkpoint; does not provide a self-contained fixture. |
| `test/llm_tester.py` | LLM output/parser smoke test with overload facts and sample decision/email content. | Exercises prompt/parser path; not an automated CI suite. |

### `agent/nodes.py` logic in detail

- `replicas_for(demand, capacity, min_rep, max_rep)` uses a ceiling formula: `ceil(demand * (1 + MARGIN) / capacity)`, then clamps to min/max. This creates a 10% headroom target by default (`nodes.py`, lines 36–40; `config.py`, line 30).
- `Feed.__init__()` loads the CSV, selects `cfg.APP`, loads its `.pt`, defines replay start at `max(int(n*0.7),1440)`, infers capacity as training mean divided by `AVG_REPLICAS` (default five) unless manually overridden, infers max replicas from 1.5 times the training maximum divided by that capacity, and initializes count from first replay traffic (`nodes.py`, lines 65–79). This capacity is a modeling assumption, not an experimentally measured service capacity.
- `store_prediction` reads current minute traffic, predicts a future value, stores `forecast_for = minute + H`, and appends one row (`nodes.py`, lines 82–97).
- `unusual_reason` tests: (a) forecast jump above 1.3× previous forecast and above 50% of current capacity; (b) max(current traffic, forecast) above 95% of current capacity when additional replicas are available; (c) five-minute WAPE above 0.5. It returns the first matching explanation (`nodes.py`, lines 100–124; `config.py`, lines 38–43).
- `trigger_check` gives unusual events priority, then periodic timer, otherwise automatic policy. It resets the timer after an unusual event and waits three simulated minutes after an unusual LLM decision (`nodes.py`, lines 127–143; `config.py`, lines 35, 43).
- `script_creator` formats the latest ten minutes, aligns each actual minute to an earlier forecast targeting it, reports WAPE/utilization, and lists the last three actions. This is the LLM's bounded textual context, not a retrieval system (`nodes.py`, lines 145–189).
- `_facts` supplies recent peak demand and the formula's replica count as a baseline. The LLM prompt explicitly asks the model to stay with the formula unless there is a clear reason (`nodes.py`, lines 193–199; `llm.py`, lines 28–44, 58–70).
- `auto_scale` selects the maximum of actual and forecast demand in the recent ten-minute window, applies the replica formula, and prevents scale-down for ten minutes after scale-up (`nodes.py`, lines 210–219; `config.py`, lines 45–50).
- `guardrail` enforces replica bounds and limits each upward action to the lesser of the proposal and max(current+2, 2×current); downscale is limited to 25% or at least one replica (`nodes.py`, lines 222–228).
- `set_replicas()` intentionally does nothing (`nodes.py`, lines 231–233). This is the implementation boundary between a simulator and a real scaler.
- `alert_reason_for` can alert on forced test, LLM escalation only when load remains >90% after the applied decision, two consecutive LLM failures, two consecutive pre-decision overload minutes, or overload at max replicas (`nodes.py`, lines 236–256; `config.py`, lines 55–59, 79).
- `apply_and_log` guards proposals, updates state, logs LLM decisions and any changed automatic decisions, accumulates error count, and records alert/scale-up time (`nodes.py`, lines 259–285). The action CSV does not preserve all useful diagnostics: in particular it omits `formula_replicas`, guardrail clipping amount, and explicit before/after utilization deltas.
- `alert_human` assembles the last-hour report and attaches prediction/action CSV data; it saves the generated email body and optionally calls SMTP (`nodes.py`, from line 289 onward; `mailer.py`).

### `agent/llm.py` safeguards and limitations

- Providers supported: `fake`, `gemini`, `mistral` (`llm.py`, lines 26–27). The default is fake in `config.py`, so the default runtime is not using an external LLM.
- The fake provider returns a formula-like decision (`llm.py::fake_llm`). It is a deterministic stand-in, not an AI model and not an independent learned controller.
- Gemini request sets temperature zero and asks for JSON MIME; Mistral uses chat completion with JSON-object response format (`llm.py`, lines 104–135).
- `post_json` retries HTTP 429/500/502/503/504 and transient connection/timeout errors, with configured retries and incremental waits. Other HTTP 4xx errors are raised immediately (`llm.py`, lines 82–101).
- `parse_reply` extracts a JSON object, checks `replicas` is numeric/finite/non-boolean, rounds/clamps it, recomputes action from the current count, truncates reason, and only accepts literal boolean `true` for `escalate` (`llm.py`, lines 138–160). It does not enforce a full JSON schema, validate the meaning of the `action` returned by the model, or retain a structured confidence score.
- `ask_llm` catches errors and returns a safe “hold current replicas” result with an error flag; this avoids a failed LLM call producing an arbitrary scale action (`llm.py`, lines 163 onward).
- The system prompt says new replicas take about two minutes to start (`llm.py`, line 33), but the replay/scaling implementation does not model startup delay. This is an important model-controller inconsistency.

## 2.3 Forecasting pipeline and model design

The saved notebook is a 24-cell notebook. Its data is described as a minute-level matrix with **20,160 minutes × 318 applications**. It selects six representative series: `app_1`, `app_62`, `app_123`, `app_185`, `app_248`, `app_318`. The forecast target is invocation traffic at `t+10`, with `W=60` minutes of history.

The runtime model class in `notebook/predict.py::LSTMForecaster` uses:

- one univariate LSTM: input dimension 1, hidden size 64, batch-first;
- a dense head combining the last hidden state with four static features;
- a Linear → ReLU → Linear head to one scalar.

The four static features are yesterday's traffic at the target time, yesterday's change over the horizon, and sine/cosine of time-of-day. The sequence and target are transformed in log space. The model predicts a scaled change in log traffic; inference reconstructs the log level and applies `expm1`, then clips values below zero (`predict.py`, lines 65–74, 98–132). `DAY=1440` and `predict_at` rejects positions before a full day of history (lines 27, 104–112).

The notebook compares naive last-value, yesterday-same-time, moving-average, HistGradientBoosting point and q90, LSTM point and q90. The HistGradientBoosting feature design includes lag values and rolling statistics; the LSTM uses the sequence plus calendar/yesterday static features. The training notes record HistGradientBoosting with 300 iterations, learning rate 0.05, depth 6; the LSTM has one 64-unit recurrent layer, Adam learning rate 0.002, batch size 256, up to 40 epochs, seed 0, and a last-10%-of-training validation split. The q90 variant uses pinball-style training. See `notebook/lstm_model.ipynb` saved cells and `notebook/notebook_readme.md`, Sections 3–8.

### Forecast results reported by the notebook

| Method | Mean WAPE across six apps | Notes |
|---|---:|---|
| LSTM point forecast | 0.189 | Lowest reported mean, but only 0.002 below GBM. |
| HistGradientBoosting point | 0.191 | Essentially tied at the reported precision. |
| HistGradientBoosting q90 | 0.308 | More conservative; underestimation lower, overestimation higher. |
| Moving average | 0.356 | Beats learned models on some low-WAPE applications. |
| Yesterday same minute | 0.359 | Simple seasonal baseline. |
| Last-value naive | 0.361 | Simple baseline. |
| LSTM q90 | 0.472 | Poorer average WAPE, though intended to target upper quantile. |

The notebook records 6,038 test points in total and mixed per-app behavior: app_1 and app_123 tie LSTM/GBM at displayed precision, app_185 is very difficult (about 0.99 WAPE), app_248 slightly favors GBM, app_318 favors LSTM, and app_62 slightly favors GBM. The q90 variants trade underestimation for overestimation. The notebook README explicitly warns against claiming the tiny LSTM/GBM difference is meaningful without repeated experiments (`notebook/notebook_readme.md`, Sections 7–8).

**Interpretation:** the current forecast result is an early baseline comparison, not evidence that LSTM is the best architecture. Use paired per-minute loss differences, multiple temporal splits, multiple seeds, confidence intervals, and per-app stratification before making model-superiority claims.

## 2.4 Configuration, dependencies, and environment

`requirements.txt` lists `pandas`, `numpy`, `torch`, `scikit-learn`, `joblib`, `matplotlib`, `gdown`, `ipykernel`, `requests`, `python-dotenv`, and `langgraph`; the file is unpinned. `monitoring-requirements.txt` layers `prometheus-client>=0.20,<1` and `psutil>=5.9,<8` over the base requirements. There is no `pyproject.toml`, lockfile, Dockerfile for the allocator, reproducible environment export, or CI configuration.

`notebook/predict.py::load_data` tries known local paths and, if the CSV is absent and `gdown` is installed, downloads a Google Drive file by hard-coded ID (lines 33–42, 77–86). The download has no recorded checksum/version verification in the code. `find_model` searches the repository's model folders recursively for `<app>.pt` and exits if it cannot find one (lines 44–52).

## 2.5 Monitoring / Grafana dashboard

`agent/metrics.py` exposes:

- gauges for current, before, and proposed replica counts; max replicas; traffic; forecast; capacity per replica; capacity after scaling; post-decision utilization; pre-scale over-capacity; last LLM error; exporter timestamp;
- host and allocator-process CPU, memory, thread count, and uptime;
- counters for replay minutes, replica-minutes, over-capacity minutes, LLM calls/failures, replica changes, decisions, alerts, and email delivery outcomes;
- histogram for graph invocation duration.

The host/process distinction matters: CPU and memory sampled through `psutil` describe the **machine running AegisCloud**, not the application whose traffic is replayed. They are not per-container application CPU/memory metrics. “Replica-minutes” is a count-based proxy for allocated replica time, not a cloud bill or measured monetary cost (`metrics.py`, especially `record_tick`; `MONITORING.md`, Section Metric semantics/limitations).

The dashboard JSON contains 21 panels: current replicas; observed traffic; forecast traffic; post-decision utilization; actual versus forecast; replica count before/proposed/after; scaling actions; decision calls by mode/provider; alerts; LLM failures; pre-decision overloaded minutes; graph execution duration; process CPU/memory; host CPU/RAM; email successes/failures/saved-only; uptime; and pre-decision utilization. It has an `app` label variable. Some labels could be misread as target-app metrics unless carefully explained.

Prometheus is configured with a one-second scrape interval and targets the host exporter through `host.docker.internal:8000` (`monitoring/prometheus.yml`; `docker-compose.monitoring.yml`). Exporter binds `0.0.0.0` (`metrics.py`, lines 76–80). No authentication/TLS layer is configured for this endpoint; do not expose port 8000 to an untrusted network.

---

# 3. Theoretical and research foundation

The supplied papers inform the problem framing, but the implementation does not reproduce their algorithms. The correct way to cite them is as **related work and design inspiration**, not as components already present in AegisCloud.

## 3.1 DeepRM — Resource Management with Deep Reinforcement Learning

**Supplied file:** `Reaserch_Papers/deeprm_hotnets16.pdf` (7 PDF pages).  
**Paper:** Mao, Alizadeh, Menache, and Kandula, “Resource Management with Deep Reinforcement Learning,” HotNets-XV (2016), DOI 10.1145/3005745.3005750.

### Core formulation

DeepRM represents a cluster as a two-resource grid (e.g. CPU and memory). Jobs have resource vectors and durations. The scheduler observes a state derived from a resource-allocation image, queued jobs, and backlog, then chooses a job to schedule or a no-op. The simulation advances when no eligible job can be scheduled. This is a scheduling/packing problem over queued jobs and cluster resources, not a request-rate-to-replica-count problem.

The paper formulates a policy `pi_theta` and maximizes expected discounted reward:

```text
J(theta) = E under policy pi_theta [ sum over t of gamma^t * r_t ]
```

Its policy-gradient expression (paper Eq. 1, Section 3.2–3.3) is of the REINFORCE family:

```text
grad_theta J(theta) = E under pi_theta [
    grad_theta(log pi_theta(s_t, a_t)) * Q_pi_theta(s_t, a_t)
]
```

and its update uses sampled returns (paper Eq. 2):

```text
theta <- theta + alpha * sum_t[
    grad_theta(log pi_theta(s_t, a_t)) * v_t
]
```

The reward design seeks to reduce job slowdown. The paper defines per-job slowdown as completion time divided by service time, and uses a reward proportional to negative aggregate slowdown. It also discusses alternate objectives such as completion time, utilization, and makespan. The baseline subtraction reduces variance in policy-gradient updates.

### Evaluation and caveats

The evaluation uses simulated job arrivals, multiple resource types, short/long job durations, and baselines such as SJF, Packer/Tetris-style methods, and random scheduling. It studies training convergence and performance across load levels. The discussion notes practical limitations around machine fragmentation/locality, varying resource needs, bounded observation horizons, and the gap between a simplified simulator and a production cluster.

### Mapping to AegisCloud

| DeepRM concept | AegisCloud status |
|---|---|
| RL policy `pi_theta`, REINFORCE gradient, reward optimization | **Absent.** No policy network, reward, return, gradient update, or RL training in `agent/`. |
| Queue of jobs and placement actions | **Absent.** AegisCloud forecasts one application's request count and selects replica count. |
| Multi-resource CPU/memory allocation grid | **Absent.** The runtime uses requests/minute and a scalar capacity-per-replica assumption. |
| Scheduling baselines and simulated cluster | **Not reproduced.** There is a trace replay, but no cluster/job simulator. |
| General motivation for learned resource management | Related-work context only. |

**Research-use note:** DeepRM is a valid conceptual antecedent for learning-based resource management, but AegisCloud must not say it implements DeepRM or uses its REINFORCE algorithm.

## 3.2 PASM — Pervasive Auto-Scaling Method for Improving the Quality of Resource Allocation in Cloud Platforms

**Supplied file:** `Reaserch_Papers/Pervasive_Auto-Scaling_Method_for_Improving_the_Qu.pdf` (22 PDF pages).  
**Paper:** Rajasekar and Santhi, *Big Data and Cognitive Computing*, 9(11), 294 (2025), DOI 10.3390/bdcc9110294.

### Core ideas and mathematical model

PASM discusses a cloud allocation/scaling method involving application demand, QoS, overflow, service failures, provider capacity, vertical/horizontal scaling, and migration of resource demand between providers. It presents a learning network / deep reinforcement-learning motivation and an iterative allocation procedure. The equations in Sections 3.1–3.9 introduce a set of symbols for effective utilization, QoS, application demand, overflow, scaling rate, prior capacity, resource allocation, migration, wait time, and service failure.

The paper's displayed equations include:

```text
(1) EU_s(c_(t+1)) = Loadbal(Appl_t + QoS) - (UPscale + Downscale)
```

```text
(2) V(UPscale + Downscale) = Loadbal(Appl_t + QoS) - RA_t
```

```text
(3) QoS(scalingO) = Appl_demand - Ov_f
```

```text
(4) Appl_demand = W_t / (W_t + S_f)
(5) Ov_f = RA_f / (RA_f + S_dy)
```

The article continues with the following displayed expressions. The notation below is a readable transcription of the paper's symbols; several symbols are not operationally specified well enough to turn these expressions into an unambiguous executable policy:

```text
(6)  scalingrate = 2 * Loadbal(Appl_t + QoS) * X1 - Ov_f

(7)  PrevCA_i = 2 * X2 + QoS(scalingO) / (Appl_demand + Ov_f)

(8)  RAsqc(t+1) = (Appl_t1 * PrevCA_i1 + ... + Appl_tn * PrevCA_in) / Ov_f

(9)  RA1 = |T1 - PrevCA_i1 * delta_alpha|
     RA2 = |T2 - PrevCA_i2 * delta_beta|
     ...
     RAn = |Ti - PrevCA_in * delta_gamma|

(10) MigrateResP(Demd_high / Demd_low) =
     [C(UPscale -> Downscale) + RA_Demd_high] /
     [C(UPscale <- Downscale) + RA_Demd_low]

(11) W_t = (Demd_high - Demd_low) / Ov_f + Serv_min

(12) S_f = (1 / sqrt(2*pi)) * {
       [C(UPscale -> Downscale) / C(UPscale <- Downscale) - Serv / Ov_f]
       / [2 * (CurCAin - ØCAin)]
     }
```

Algorithm 1 in Section 3.9 (PDF p.12) iterates over demand, overflow, wait/failure values, network training, scaling, allocation updates, provider migration, and QoS monitoring.

**Notation caution:** some PASM variables and operations (including the scale factors, several deltas, and provider-cost terms) are introduced without enough operational definition to independently reconstruct a unique numerical implementation from the PDF alone. Equations 10–12 are especially notation-dense. They should not be transplanted into AegisCloud without a careful symbol/units audit and a verified implementation.

### Mapping to AegisCloud

- PASM's broad autoscaling objective is related to the AegisCloud problem.
- PASM's explicit overflow, service-failure, wait-time, provider-migration and resource-allocation variables do not exist as a unified state in `agent/state.py`.
- AegisCloud has no multi-provider resource migration, no DRL learning loop, no service-failure model, no queueing/wait-time calculation, and no provider sharing logic.
- `agent/nodes.py::replicas_for` is a basic ceil-with-headroom rule. It is not an implementation of PASM equations 1–12.
- `agent/nodes.py::guardrail` is a deterministic safety clamp, not PASM's learning network.

**Research-use note:** cite PASM as related work on autoscaling and QoS-aware resource allocation; do not claim its PASM algorithm or equations are implemented.

## 3.3 Borg: Large-scale cluster management at Google with Borg

**Supplied file:** `Reaserch_Papers/Tirmazi_Borg.pdf` (14 PDF pages).  
**Paper:** Tirmazi et al., “Borg: the Next Generation,” EuroSys 2020, DOI 10.1145/3342195.3387517.

### Core findings

The paper analyzes changes in Google's Borg cluster manager and workload traces across 2011 and 2019. It reports growth in fleet size, machine shapes, platform types, job/resource classes, scheduling activity, and the scale of trace data. It studies utilization, job lifecycles/evictions, scheduler throughput and delay, heavy-tailed job resource consumption, and vertical resource-limit tuning using Autopilot.

A particularly important result for cloud-resource research is the heavy-tailed demand distribution. The paper reports very high coefficients of variation for CPU and memory consumption, with a small fraction of jobs accounting for most resource use. It discusses the M/G/1 queueing relationship (paper Section 7.3):

```text
E[W_q] = (rho / (1 - rho)) * ((C^2 + 1) / 2)
```

where `rho` is utilization and `C-squared` is squared coefficient of variation of service time. The lesson is that high variability can amplify queueing delay even when average utilization is not close to 100%.

The paper also describes Borg Autopilot's predictive vertical resource-limit adjustment. That is not the same as horizontal replica-count scaling: it tunes resource limits for jobs/containers, rather than deciding the number of application replicas from an invocation forecast.

### Mapping to AegisCloud

- Borg motivates trace-driven evaluation and the importance of burst/variability analysis.
- AegisCloud uses a selected Azure Functions invocation trace, not Borg cluster traces.
- AegisCloud has no Borg-style job scheduler, placement engine, machine fragmentation model, multidimensional resource vectors, or vertical CPU/memory allocation policy.
- The current `app_185` burst underforecast highlights why heavy tails and rare bursts should be included in the next study; it does not establish Borg findings for this dataset.
- Any cost/SLO/throughput conclusions from Borg cannot be transferred directly to AegisCloud.

## 3.4 MOYA — Engineering LLM Powered Multi-Agent Framework for Autonomous CloudOps

**Supplied file:** `Reaserch_Papers/cloud_Research_papers.pdf` (11 PDF pages).  
**Paper:** Parthasarathy et al., “Engineering LLM Powered Multi-agent Framework for Autonomous CloudOps,” CAIN 2025, DOI 10.1109/CAIN66642.2025.00031.

### Framework and evaluation

MOYA responds to limitations of a monolithic LLM/RAG assistant for cloud operations. Its framework includes request handling, an LLM processor, orchestrator, context memory, agent selector, agent registry, lifecycle management, and governance/guardrails. It uses specialist agents (e.g., reporting, static RAG, API/notification, summaries, cost, dashboard) and can delegate/aggregate across agents.

Its evaluation uses 26 prompts expanded into ten variants (260 prompts), expert-curated gold standards, and human inspection of issue types. Automated metrics include ROUGE-1, BLEU, METEOR, and BERTScore. The reported aggregate results improve over the monolithic baseline (for example ROUGE-1 0.321→0.448, BLEU 0.102→0.221, METEOR 0.265→0.423, BERTScore F1 0.843→0.868); user-identified issue counts are also lower in its tested sample. The paper notes limitations around agent-selection accuracy as the agent set grows, AWS-centric evaluation/generalizability, model drift, token use, and hallucinated counts.

### Mapping to AegisCloud

AegisCloud is **not** a MOYA-style multi-agent architecture. It has one fixed LangGraph controller with three mutually exclusive decision routes. It does not contain an agent registry, dynamic specialist selection, RAG/vector retrieval, hierarchical context summarization, external CloudOps API agents, or a gold-standard response evaluation harness. Its ten-minute CSV-derived textual report is bounded context, not semantic memory. Its LLM proposes a replica count; deterministic code clamps it.

MOYA is the closest supplied architectural reference for future agentic CloudOps extensions, but its reported metric gains are MOYA's own experiment results and are not AegisCloud results.

## 3.5 Review of contemporary autoscaling methods

**Supplied file:** `Reaserch_Papers/2511.11603v1.pdf` (17 PDF pages).  
**Paper:** Bodra and Khairnar, “A Review of AI-Based Resource Allocation and Task Scheduling in Cloud Computing,” *Frontiers in Computer Science* (2025), DOI 10.3389/fcomp.2025.1678976.

This is a review article, not a single unified autoscaling algorithm. It screens a large literature set and compares ten selected approaches across deep RL, neural forecasting/optimization, traditional ML, and multi-agent learning. It reports that individual referenced studies obtained improvements in execution time, energy, cost, utility, latency, makespan, or forecast error. These percentages come from different papers, datasets, baselines, simulators, and metrics. They are **not a common head-to-head benchmark** and must not be presented as directly comparable results.

The review's most relevant methodological points are:

- no single model/policy is universally optimal across cloud environments;
- forecasting, optimization, orchestration and task scheduling are coupled but distinct problems;
- dataset, resource types, workload, baseline strength, and metric selection materially affect claimed gains;
- algorithmic performance can trade off against training/inference complexity and scalability;
- cross-study comparisons should be interpreted cautiously (Section 5–8).

**Mapping:** the survey supports a broad literature rationale for forecasting and intelligent allocation, but none of its ten reviewed algorithms is reproduced in `agent/` or the notebook. If numerical gains from its Table 1 are quoted in a paper, cite the original study as well as the review and explicitly say the numbers are reported in separate study settings.

## 3.6 Agentic AI Frameworks for Autonomous Cloud Resource Management (unpublished manuscript)

**Supplied file:** `Reaserch_Papers/Agentic_AI_Cloud_Resource_Management_SSRN.pdf` (12 PDF pages).  
**Document status:** The file is dated 5 March 2026 and presents itself as an agentic-cloud-resource-management manuscript. It has an authorship inconsistency: the title page names one author pairing, while the running footer uses a different pairing. The supplied copy does not provide a verified DOI/publisher record. Treat as grey literature / an unverified manuscript until the authorship and publication status are confirmed.

The manuscript organizes agentic resource management around perception, reasoning, action, memory, and governance. It discusses read-only/low-blast-radius actions versus high-blast-radius guarded actions, episodic/semantic/procedural memory, autoscaling/cost/anomaly/self-healing/scheduling/compliance use cases, prompt injection, explainability, robustness, formal verification, and human oversight.

**Mapping:** AegisCloud has a simple observe/reason/act/audit pattern: traffic/forecasts are observed; rule/LLM logic reasons; an integer replica proposal is guarded; CSV/alert logs provide an audit trail. It does not implement the manuscript's broader three-form memory system, vector search, policy verification, multi-tool action layer, formal governance, or comprehensive blast-radius controls. It is a useful conceptual checklist, but not a reliable bibliographic anchor until its publication/authorship is verified.

## 3.7 Research-to-code traceability matrix

| Research idea | Paper anchor | Code status | Research gap |
|---|---|---|---|
| Forecast-informed scaling | PASM Section 3; Bodra & Khairnar review; Borg Section 8 | Basic LSTM forecast and replica formula exist (`predict.py`; `nodes.py`) | Forecast error under bursts; compare horizons/models and prove scaling benefit. |
| RL-based resource allocation | DeepRM Sections 2–4; PASM Section 3.6 | Not implemented | No reward, state-action policy, training loop, or RL comparison. |
| Cluster/job scheduling | DeepRM Sections 3–5; Borg Sections 5–7 | Not implemented | No job queue, placement, fragmentation, multi-resource packing. |
| LLM agent orchestration | MOYA Sections IV–VI; SSRN Sections 3–6 | Limited single LLM review node | No agent registry, tool delegation, RAG/memory, or systematic LLM evaluation. |
| QoS/overflow/wait/failure | PASM Sections 3.3–3.9 | Partial overload detection only | No latency SLO, queueing, service failure, request drop, or QoS ground truth. |
| Governance/guardrails | MOYA Section IV; SSRN Sections 3,5–6 | Replica bounds, step limits, alert rules | No identity/authorization, policy verification, canary/rollback, workload isolation. |
| Heavy-tail workload evaluation | Borg Section 7; Bodra & Khairnar Section 5 | One historical traffic dataset; six selected apps | Need burst-class stratification, repeated traces, and robust confidence intervals. |

---

# 4. Documentation and usage: Markdown / text files

## 4.1 `README.md` (528 lines)

The main README is the primary project guide. It contains:

- project goals and architecture diagram/workflow (lines 32–90);
- implemented feature inventory and repository layout (lines 91–145);
- dependencies and install steps (lines 147–182);
- dataset/model prerequisites (lines 182–186);
- agent `.env` and root Grafana password configuration (lines 188–212);
- forecasting commands and saved-model usage (lines 214–237);
- fake and real provider commands, CLI flags and testing commands (lines 239–312);
- Prometheus/Grafana startup, interfaces, PromQL examples, metric meanings and troubleshooting (lines 313–429);
- email alert configuration (lines 430–447);
- forecasting experiment/results and test checklist (lines 448–488);
- known limitations, roadmap, and security notes (lines 489–528).

The README is the best starting point for a user, but the archive does not include all the data/model artifacts it tells the reader to provide. It should explicitly call out the missing checkpoint package and model/data hashes in the release artifact.

## 4.2 `agent/step_based_working_readme.md` (159 lines)

A short step-by-step description of the LangGraph controller: graph sequence, three modes, guardrail, LLM layer, alert path, state keys, folder map, setup/run, validation workflow, and places to tune. It is useful for following the runtime. Its old threshold description says overload must persist for five minutes in places; current `config.py` sets `ALERT_MISS_MINUTES=2` and `nodes.py::alert_reason_for` uses that constant. Treat the source code as authoritative for the uploaded revision and update the stale guide.

## 4.3 `learning/AegisCloud Notebook Notes (Simple English).md` (352 lines)

A beginner-facing walkthrough of the project purpose, vocabulary, folder layout, data flow, per-minute graph, three decision modes, formula, guardrail, alerts, file-by-file agent guide, notebook/model explanation, output interpretation, run steps, progress, known issues, and monitoring. It is helpful onboarding documentation, but some model-file availability claims describe the developer environment rather than the distributed archive: the supplied `models/` directory contains only `meta.json`, not six `.pt` files. Its overload-duration explanation also needs reconciling with the current two-minute code setting.

## 4.4 `learning/learn_agent.md` (395 lines)

A deeper beginner-level explanation of the agent and libraries. It walks through config, state, LLM prompts/providers, mailer, helper methods and `Feed`, each graph node, graph routing, CLI runtime, small files, tests, and a worked example. It is a valuable companion for code review. Because it is explanatory prose, verify all numeric defaults against `agent/config.py` rather than copying values into the final paper without source checking.

## 4.5 `MONITORING.md` (94 lines)

Quick monitoring guide: dependency install; starting Prometheus/Grafana; running agent metrics; checking UI; PromQL snippets for exporter reachability, simulated replicas, traffic/forecast, utilization, scale events, alerts, LLM failures and graph duration; metric semantics and shutdown. Its statement of the Grafana default credential (`admin/admin`) conflicts with the root Compose fallback `change-this-password` and `MONITORING_SETUP.md`. Use the actual environment variable / Compose configuration, not the stale generic password description.

## 4.6 `MONITORING_SETUP.md` (116 lines)

A more detailed setup/runbook for monitoring and email: copy paths, install dependencies, launch stack, run fake provider and alert tests, enable email, configure Gemini/Mistral, troubleshooting and PromQL checks. It is more operationally detailed than `MONITORING.md`. Its instructions still depend on supplying valid `.env` variables and the missing data/model assets.

## 4.7 `notebook/notebook_readme.md` (145 lines)

The forecasting experiment record: data shape, target and split, baseline descriptions, metrics definitions, aggregate/per-app results, interpretation, known limitations, output/checkpoint structure, and next steps. This is a key research-methodology reference and correctly notes that a 0.002 mean WAPE gap is too small to claim a clear win. It also records only one temporal split and one seed, which is insufficient for a strong statistical claim.

## 4.8 `fixes/fix_to_do.md` (154 lines)

The engineering backlog. P1 items 1–7 are checked as completed: failure state; false-escalation handling; anti-flapping; LLM reason cleanup; node cleanup; SMTP 587 fallback; root `.gitignore`. P2 items 8–14 remain unchecked: strengthen quality assertions; log formula baseline/mismatch; verify model identifiers; run Mistral; replace repeated CSV reads with in-memory/sliding history; add unit tests/CI; refresh documentation. P3 contains longer-term work including real feed/scaler and simulator/policy comparisons. This backlog itself is useful evidence of incomplete research controls.

## 4.9 `output/test_output.md` (153 lines)

A dated historical test log (24 October 2026). It records reported smoke/integration runs: fake provider 28/28, Gemini 29/29, Gemini plus email 30/30; a 120-minute fake-provider replay; and a Gemini replay stopped after 54 minutes. It reports no Gemini errors in the recorded period, but also documents an alert at approximately 82% utilization (described as false) and scale-up/scale-down oscillation around adjacent minutes. It states that Mistral and real overload behavior for the hardest app were not tested. These are historical claims, not fresh audit runs.

The historical notes report 817 replica-minutes and 9 scale events during the 120-minute fake replay. Replica-minutes should not be called dollars, measured cost, or provider billing. The report's summary says new replicas are assumed to start instantly, which confirms the absence of a startup-delay model.

## 4.10 `AegisCloud_Paper_Revision_Plan.txt` (11 lines)

A concise paper-revision plan. It calls for repeated tables, validation of dataset provenance/metadata, an explicit simulator with per-replica capacity and startup delay, policy comparisons (reactive/rule/unguarded LLM/guarded LLM/quantile), and reporting replica-minutes, overload, churn, guardrail intervention, LLM failures and alert quality. This is an appropriate research plan and should be made executable as a benchmark protocol before drafting performance claims.

## 4.11 `agent/.env.example` and `LICENSE`

`.env.example` is a template for API credentials and email settings; it should contain placeholders only. The root `LICENSE` is Apache License 2.0. The nested archive contains a real `.env` and must not be distributed.

---

# 5. Current working state and data flow

## 5.1 Input-to-output trace

### Step A — startup and asset loading

`python -u agent/run.py ...` enters `agent/run.py::main()`. Argument parsing supports replay length, sleep/tick delay, timer interval, selected app, LLM provider, email, quiet mode, metrics port, disabling metrics, forced test alert, and keeping the exporter alive. `check_setup()` validates basic required setup for the configured provider. The program imports the graph and node modules, resets the run output files, creates `Feed`, and creates initial `AgentState` (`agent/run.py`, lines 26–60 and 60–140; `agent/nodes.py::Feed`; `agent/state.py::new_state`).

`Feed` loads the minute-indexed CSV, selects one app column, loads the matching `.pt`, calculates the replay start, capacity-per-replica assumption, maximum replica limit, first replica count, and initial minute. The model needs at least 1,440 minutes of history (`nodes.py`, lines 65–79; `predict.py`, lines 104–112).

### Step B — one replay minute enters the graph

For each position, the runner puts `pos` into the state, invokes the compiled graph, measures graph runtime, updates metrics, and optionally sleeps `tick` seconds before the next simulated minute. The default one-second tick means the 60-minute historical window and 10-minute forecast horizon are in **dataset-minute units**, while runtime wall clock may move much faster (`config.py`, line 23; `run.py` main loop; `metrics.py::record_tick`).

### Step C — forecast and persist

`store_prediction` reads the current actual traffic and runs `predict_at`. The forecaster transforms the selected series using `log1p`, slices the latest 60 observations, normalizes them using checkpoint statistics, builds yesterday/time-of-day features, executes the LSTM without gradients, reconstructs future traffic, and returns a nonnegative forecast. The node appends current traffic, forecast, target minute, and current replica count to `agent/data/predictions.csv` (`predict.py::predict_at`; `nodes.py::store_prediction`).

### Step D — choose mode

`trigger_check` reads the prediction CSV and checks unusual rules in a fixed order: spike, near capacity, forecast miss. If none applies and the timer is due, choose `timer`; otherwise choose `auto`. The unusual and timer modes invoke the LLM; auto does not (`nodes.py::unusual_reason`, `trigger_check`; `graph.py::route_mode`).

### Step E — prepare bounded evidence and decide

`script_creator` builds a small text report with the last ten observed minutes, earlier forecasts aligned to those minutes, WAPE, current forecast, utilization and recent actions. `_facts` adds current/maximum/minimum replicas, per-replica capacity, recent peak, and formula baseline.

In unusual/timer modes, `llm.ask_llm` calls the selected provider. In fake mode this is a deterministic formula stand-in. Gemini and Mistral receive the system and user prompts with JSON output mode, use retries for transient errors, and return a sanitized decision. On failure, AegisCloud holds the current count and increments an error streak. In auto mode, the recent ten-minute peak of actual/forecast traffic is passed through the deterministic replica formula (`nodes.py::script_creator`, `_facts`, `auto_scale`; `llm.py::ask_llm`, `parse_reply`).

### Step F — guard, simulate, and log

`apply_and_log` applies `guardrail()` to every proposed replica count. It calls `set_replicas(applied)`, but that method is a no-op. The resulting integer is written to the state; LLM decisions and replica-changing decisions are appended to `agent/data/actions.csv`. The alert policy checks the alert conditions and records cooldown/scale-up timestamps (`nodes.py::guardrail`, `set_replicas`, `apply_and_log`, `alert_reason_for`).

### Step G — optional alert and monitoring

If an alert reason exists, `alert_human` generates an email (LLM or deterministic template), saves the body under `agent/data/alerts/`, attaches up to 60 minutes of prediction/action history, and optionally sends SMTP. Prometheus receives the simulated replica state, forecast/traffic, capacity, utilization, action counters, alert counters, and allocator-host metrics. Grafana visualizes them (`nodes.py::alert_human`; `mailer.py::send_email`; `metrics.py::record_tick`; dashboard JSON).

### Step H — end-of-replay output

The runner prints minutes replayed, LLM calls, replica changes, alerts, replica-minutes and overloaded minutes. If `--serve-after-replay` is used, the metrics endpoint can remain live while the final counters are scraped. It does not leave a cloud service scaled, because there is no resource provider API in the code (`run.py`, end-of-replay summary and serve loop).

## 5.2 Outputs and artifact semantics

| Output | Purpose | Important caveat |
|---|---|---|
| `agent/data/predictions.csv` | One row per replay minute: current traffic, forward forecast, target minute, replica state. | Reset at run start by `reset_files`; not a durable experiment database unless copied elsewhere. |
| `agent/data/actions.csv` | Decision/action rows, including mode, reason, before/proposed/applied counts and decision reason. | Omits formula baseline, guardrail delta and confidence; not an exhaustive decision trace. |
| `agent/data/alerts/alert_*.txt` | Human-readable alert messages. | Alert files are deleted at the next run because `reset_files` clears them. |
| Prometheus metrics | Current replay/controller/host state and counters. | Exporter binds to all interfaces; protect it. Host stats are not target app stats. |
| Grafana dashboard | Trend views for replay and agent health. | No actual cloud cost or production SLO metrics. |
| Historical nested CSVs | A small snapshot of old decisions/predictions in `agent.zip`. | Not the complete experiment dataset; nested archive also includes secrets. |

## 5.3 What is currently proven vs. what is asserted

**Verified directly from source/artifacts in this archive:**

- Python files compile successfully with `python -m compileall`.
- Notebook parses as nbformat 4 with 24 cells.
- The dashboard JSON, Prometheus YAML, Grafana provisioning YAML, Compose YAML and `models/meta.json` parse successfully.
- Six research PDFs and the project draft are present; all six PDFs were rendered for page inspection.
- The source contains a fake/Gemini/Mistral provider path, graph branches, guardrail, CSV log path, alert path and metrics exporter.
- The live scaler method is empty.
- The main archive contains no `.csv`, `.pt`, or `.pth` files. The nested ZIP contains historical CSV outputs, but no trained checkpoint.

**Documented historically but not reproduced in this audit:**

- Model metrics and checkpoint export reported in the notebook and README.
- Fake/Gemini integration and replay counts in `output/test_output.md`.
- SMTP delivery reportedly tested successfully in the historical test log.
- The previous VM/EC2/Prometheus/Grafana run described across the Markdown notes.

**Cannot be verified from this archive:**

- The provenance, checksum, license, and current availability of the dataset downloaded by `gdown`.
- Exact trained checkpoint weights or whether they were generated from the same dataset version and split shown in the notebook.
- Fresh LLM provider compatibility and account-specific model access.
- Fresh end-to-end runtime and email delivery.
- Any real infrastructure scaling, application performance, latency improvement, or monetary cost reduction.

## 5.4 Historical burst evidence and its significance

The nested `agent.zip` includes a small saved prediction/action snapshot for `app_185`. It records forecast values around 4–6 requests/minute while observed traffic jumps to 1,724 and then 6,921 requests/minute. The corresponding saved alert describes 8 replicas at approximately 52 requests/minute each (about 416 requests/minute total capacity), giving observed utilization around 16.6× capacity at the peak. The controller's maximum replica proposal is constrained by the per-decision guardrail; the scaler cannot add the theoretical 147 replicas in one step. This snapshot is consistent with the notebook's very high `app_185` WAPE and demonstrates a critical failure mode: severe forecast underprediction on a burst can overwhelm a slowly ramping guarded controller.

This is a historical saved trace, not a controlled benchmark result. Preserve it as a qualitative failure case, then reproduce it in a deterministic simulator with explicit startup/latency and service-level metrics.

---

# 6. Gaps, limitations, inconsistencies, and unfinished work

## 6.1 Critical correctness and modeling gaps

### A. No real actuation

`agent/nodes.py::set_replicas()` is `pass`. The state and dashboards show replica counts changing, but no container or cloud deployment changes. The README's own limitations/roadmap and architecture diagram acknowledge replay-only operation. This prevents operational claims.

### B. No startup-delay model despite prompt assumption

`agent/llm.py::SYSTEM_PROMPT` says a new replica needs about two minutes to start (`llm.py`, line 33), and `run.py` summary says replicas are assumed to start instantly. There is no startup state, pending replica, warmup time, boot failure, readiness probe, or delayed capacity contribution. This can make simulated capacity available earlier than a real deployment and biases overload metrics.

### C. Synthetic/weak capacity calibration

Unless overridden, `Feed` defines capacity as mean training traffic divided by five replicas. This is a convenient normalization, not an independently measured per-replica throughput at a specified latency/error SLO. It assumes linear scaling and identical replicas, with no concurrency bottleneck, resource contention, load balancing, queueing, cold start, saturation knee, or nonlinearity (`nodes.py::Feed`, lines 74–78).

### D. Forecast quality under bursts

The average WAPE masks application heterogeneity; `app_185` is near 1.0 WAPE. A model that forecasts normal daily patterns but misses sudden bursts can cause severe overload. The current point forecast and 10-minute horizon must be evaluated on event-specific metrics: peak underprediction, burst detection lead time, quantile coverage, overload duration, and service-level impact.

### E. Controller policy is not fully separated from model effect

The default fake provider is formula-like and timer/unusual LLM calls are interleaved with deterministic auto decisions. The existing experiment does not isolate: reactive-only, forecast-only formula, LLM-only/unguarded, guarded LLM, and quantile forecast effects under the same replay traces. The `AegisCloud_Paper_Revision_Plan.txt` already recognizes this requirement.

### F. No service-level or monetary ground truth

The project reports request capacity and replica-minutes, not measured request latency, error rate, queue length, completion time, cost per instance-hour, billing tiers, or SLO breaches. Avoid claims that the system improves user QoS, reduces real cloud expenditure, or minimizes operational cost.

## 6.2 Research evaluation and statistical gaps

- One 70/30 chronological split is not enough for a robust generalization claim.
- One recorded seed is insufficient to establish stability for stochastic training/LLM response behavior.
- A 0.002 WAPE difference is not a meaningful superiority conclusion without paired uncertainty analysis.
- Six selected app series may not represent all 318 applications; selection criteria and app IDs need explicit justification and an untouched holdout set.
- No confidence intervals, significance tests, bootstrap paired loss, or per-day distribution summaries are reported.
- Quantile forecast calibration/coverage is not reported, and q90 is worse in mean WAPE; its value should be judged by service-level underprediction reduction, not WAPE alone.
- No controlled baselines compare policies at a common action interval, capacity model, warm-up delay and scaling limits.
- No ablation quantifies the marginal value/cost of LLM review versus deterministic decisions.
- No prompt/model version, temperature, API response metadata, token/cost accounting, or per-decision latency distribution is logged for reproducible LLM experiments.
- Alert precision/recall, false positive rate, detection delay and missed-incident rate are not systematically measured.

## 6.3 Implementation and performance limitations

- `nodes.py` repeatedly reads the prediction/action CSVs in graph nodes; P2 in `fixes/fix_to_do.md` correctly proposes in-memory/sliding-window history.
- Prediction/action CSVs and alerts are wiped at run start. There is no experiment ID, append-only ledger, or durable artifact rotation.
- `actions.csv` does not log formula baseline, guardrail intervention distance, model/LLM identifier, latency, prompt hash, token usage, or full state snapshot.
- The fixed 10-minute context and 10-minute horizon should be parameterized together and recorded in each experiment.
- `LLM_FAILURES_BEFORE_ALERT` and error counter are useful, but email-writing LLM calls are not represented as normal decision-call telemetry; provider usage/cost is incomplete.
- No rate-limiting, per-provider circuit breaker, idempotency key, or budget guard is apparent in the LLM caller.
- `run.py` and graph tests rely on the external dataset/checkpoint rather than small committed fixtures.
- Dependencies are unpinned, and no automated unit test / CI workflow is included.

## 6.4 Documentation inconsistencies

| Topic | Current source of truth | Conflicting/stale documentation |
|---|---|---|
| Overload alert duration | `config.py` line 56: `ALERT_MISS_MINUTES = 2`; `nodes.py::alert_reason_for` uses it. | `agent/step_based_working_readme.md` and beginner notes describe a 5-minute persistence condition in places. |
| Grafana default login | `docker-compose.monitoring.yml` fallback is `change-this-password` (unless env overrides). | `MONITORING.md` mentions `admin/admin`. `MONITORING_SETUP.md` should be cross-checked with Compose. |
| Model files | `models/meta.json` only exists in archive. | Notebook notes describe six saved models; checkpoints are absent from delivery ZIP. |
| Environment secrets | `agent/.env.example` should be the non-secret template. | Nested `agent.zip` includes a populated `.env`, contrary to the security setup documentation. |
| Node count description | `graph.py` builds eight nodes; `learn_agent.md` describes eight workers. | `nodes.py` module docstring calls them six nodes before listing eight. |
| Startup delay | Prompt says 2-minute startup; runner says instant capacity. | No implementation reconciles the contradiction. |

## 6.5 Security and release hygiene

**Immediate action:** the nested `agent.zip` contains a populated `.env`. It includes a Gemini API key, Mistral API key, email sender/password/to fields, and Grafana admin password. Values are not reproduced in this report. If these credentials are live or the archive has been shared, revoke/rotate them immediately, review provider usage and account activity, rotate the Grafana password, and remove the populated `.env`/archive from every shared copy and repository history where possible.

The root `.gitignore` has entries for `.env`, `.env.*`, data outputs, and model binaries, but it does not ignore `agent.zip`. Add `agent.zip` and all credential-bearing bundles to deny patterns; add a secret scanner to CI; use a clean release packaging script that allowlists files rather than zipping the worktree. `metrics.py` starts an unauthenticated HTTP exporter on `0.0.0.0`; bind to loopback or a private interface and protect network access. The Grafana/Prometheus Compose stack should not be exposed publicly with a default password.

## 6.6 Prioritized roadmap for research readiness

### P0 — Before any further distribution or external testing

1. Rotate/revoke all secrets present in nested `agent.zip`; verify no provider/API key remains in Git history, shared ZIPs, logs or screenshots.
2. Remove the populated `agent.zip` from the release bundle and add it to `.gitignore`; generate a clean-source archive through allowlisting.
3. Supply the dataset with provenance, license, revision/date, SHA-256 checksum and exact schema; supply the trained `.pt` files with a manifest and checkpoint hashes, or provide a deterministic training command that regenerates them.
4. Pin dependencies and write an environment lockfile; record Python/CUDA/CPU and package versions.

### P1 — Make the simulator scientifically credible

5. Implement a simulator that models replica startup delay, readiness, scale-down termination, request arrival/queueing, capacity limits, failures and latency/SLO; no fake instantaneous capacity.
6. Measure per-replica sustainable requests/minute under a defined latency/error target, or clearly label capacity as an assumption and conduct sensitivity analysis.
7. Define workload traces, replay timing, warm-up, burn-in, scale action limits and failure policy once; use identical settings across all policy baselines.
8. Preserve raw observations and every decision in an append-only experiment ledger. Log model version, forecast target, actual target, baseline replica count, proposed/applied count, guardrail intervention, latency, API usage, and alert outcome.

### P2 — Run a controlled experiment

9. Compare at minimum: static capacity; reactive threshold; forecast + formula; LLM proposal without guardrail (offline diagnostic only); forecast + guarded LLM; calibrated q90 forecast + guarded policy.
10. Use multiple chronological splits / days and multiple model seeds; report paired confidence intervals and app-level distributions.
11. Report WAPE/MAE/RMSE plus peak underforecast, q90 coverage, overload minutes, latency percentiles, error rate, time-to-capacity, replica-minutes, scaling churn, guardrail intervention count, and alert precision/recall.
12. Isolate the LLM's contribution by comparing against the formula using the same facts and traces; record token count, API cost, response latency, invalid JSON, retries and safe-hold rate.
13. Evaluate per-app heterogeneity and stress tests: bursty `app_185`, step changes, ramp changes, zero/low traffic, missing data, forecast outage, LLM outage, max-capacity saturation.

### P3 — Operationalization / larger research scope

14. Implement a genuine adapter for Docker/Kubernetes or a cloud provider, with authorization, canary rollout, health checks, rollback, idempotency, rate limiting, and audit trail.
15. Add unit tests for formula, trigger thresholds, timer/cooldown, guardrails, alert policy, parsing and mail failure; use integration fixtures and CI.
16. If the project aims to claim a multi-agent framework, introduce and evaluate specialist agents, tool permissions, context/memory policy, orchestration, and agent-selection benchmarks; otherwise use the narrower “guarded LLM-assisted controller” terminology.

---

# Appendix A. Archive inventory and audit coverage

## A.1 Main project files

All files below were inventoried. Source code, documentation, configuration, dashboard, paper draft, notebook, and PDFs were inspected for this audit.

| Path | Type | Audit coverage / role |
|---|---|---|
| `.gitignore` | Git config | Inspected secret/data/model ignore rules; `agent.zip` not ignored. |
| `AegisCloud_Paper_Revision_Plan.txt` | Research planning | Read complete; recommendations incorporated into roadmap. |
| `AegisCloud_Research_Paper_First_Draft.docx` | Paper draft | Extracted all text/tables; 140 paragraphs, 9 tables; used as current research-positioning draft. |
| `LICENSE` | License | Confirmed Apache-2.0. |
| `README.md` | Markdown | Read all 528 lines/sections. |
| `MONITORING.md` | Markdown | Read all 94 lines. |
| `MONITORING_SETUP.md` | Markdown | Read all 116 lines. |
| `aegiscloud_architecture.png` | Architecture image | Visually inspected; replay-only boundary included. |
| `agent.zip` | Nested ZIP | Inspected contents and historical data; contains populated `.env`; must not redistribute. |
| `agent/.env.example` | Environment template | Inspected; placeholders only. |
| `agent/__init__.py` | Python | Empty. |
| `agent/config.py` | Python | Inspected all settings. |
| `agent/state.py` | Python | Inspected TypedDict and initialization. |
| `agent/graph.py` | Python | Inspected all route/node wiring. |
| `agent/nodes.py` | Python | Inspected all helpers and node functions. |
| `agent/llm.py` | Python | Inspected providers, prompts, retries and parser. |
| `agent/mailer.py` | Python | Inspected SMTP and attachment behavior. |
| `agent/metrics.py` | Python | Inspected metrics and host/process sampling. |
| `agent/run.py` | Python | Inspected CLI and replay driver. |
| `agent/step_based_working_readme.md` | Markdown | Read all 159 lines. |
| `docker-compose.monitoring.yml` | YAML | Parsed and inspected. |
| `monitoring/prometheus.yml` | YAML | Parsed and inspected. |
| `monitoring/grafana/provisioning/dashboards/cloud-allocator.yml` | YAML | Parsed and inspected. |
| `monitoring/grafana/provisioning/datasources/prometheus.yml` | YAML | Parsed and inspected. |
| `monitoring/grafana/dashboards/cloud-allocator-overview.json` | JSON | Parsed and inspected; 21 panels. |
| `monitoring-requirements.txt` | Requirements | Inspected. |
| `requirements.txt` | Requirements | Inspected; package versions unpinned. |
| `models/meta.json` | JSON metadata | Parsed; no model weights. |
| `notebook/lstm_model.ipynb` | Notebook | Parsed all 24 cells and saved outputs; inspected experimental details/results. |
| `notebook/notebook_readme.md` | Markdown | Read all 145 lines. |
| `notebook/predict.py` | Python | Inspected all functions. |
| `test/graph_tester.py` | Python test | Inspected integration test logic and assertions. |
| `test/llm_tester.py` | Python test | Inspected smoke test logic. |
| `test/.gitignore` | Git config | Inspected. |
| `output/test_output.md` | Markdown test log | Read all 153 lines; historical assertions only. |
| `fixes/fix_to_do.md` | Markdown backlog | Read all 154 lines; P1/P2/P3 status captured. |
| `learning/AegisCloud Notebook Notes (Simple English).md` | Markdown | Read all 352 lines. |
| `learning/learn_agent.md` | Markdown | Read all 395 lines. |
| `Reaserch_Papers/2511.11603v1.pdf` | Research PDF | 17 pages; rendered and inspected. |
| `Reaserch_Papers/Agentic_AI_Cloud_Resource_Management_SSRN.pdf` | Research PDF | 12 pages; rendered and inspected. |
| `Reaserch_Papers/Pervasive_Auto-Scaling_Method_for_Improving_the_Qu.pdf` | Research PDF | 22 pages; rendered and inspected, including equation pages. |
| `Reaserch_Papers/Tirmazi_Borg.pdf` | Research PDF | 14 pages; rendered and inspected. |
| `Reaserch_Papers/cloud_Research_papers.pdf` | Research PDF | 11 pages; rendered and inspected. |
| `Reaserch_Papers/deeprm_hotnets16.pdf` | Research PDF | 7 pages; rendered and inspected. |

The ZIP reports 59 filesystem entries when directory entries are counted. The extracted main tree contains 56 files. The nested `agent.zip` contains 28 entries, including older source copies, a populated `.env`, bytecode, and historical CSV/alert output. The nested source files are materially the same agent implementation as the top-level `agent/` directory; the nested archive is not a substitute for the missing model checkpoint or dataset.

## A.2 Files not present but needed

- No `dataset.csv`, `azure_functions_ranked_timeseries.csv`, or other dataset CSV is present in the main archive.
- No model `.pt` / `.pth` checkpoint is present anywhere in the main or nested archive.
- No `agent/data/` runtime output folder is present in the main archive; the nested ZIP has small historical output files only.
- No Dockerfile, Kubernetes manifests/Helm chart, cloud provider adapter, CI workflow, lockfile, or formal benchmark runner is present.

## A.3 Validation performed in this audit

- `python -m compileall -q agent test notebook/predict.py`: completed successfully.
- Notebook JSON/nbformat parse: successful; 24 cells, nbformat 4.
- JSON parse: successful for `models/meta.json` and `monitoring/grafana/dashboards/cloud-allocator-overview.json`.
- YAML parse: successful for `monitoring/prometheus.yml`, both Grafana provisioning YAML files, and `docker-compose.monitoring.yml`.
- All six supplied PDFs were rendered to page images and inspected; equation-heavy PASM pages were individually inspected for notation.
- Full end-to-end runtime was **not** executed because the dataset CSV and trained checkpoint required by `Feed` are absent. This is an intentional, evidence-based limitation, not a claim that runtime behavior passed.

---

# Appendix B. Reproducibility and research reporting checklist

Before results are reported in the paper, every row should be backed by a run manifest and saved artifact.

| Item | Required evidence | Status in uploaded archive |
|---|---|---|
| Dataset provenance | Original source, version/revision, license, retrieval date, exact file name, SHA-256 | Not included / incomplete |
| Dataset integrity | Row count, column count, missingness, duplicates, time continuity, app selection, outlier protocol | Notebook describes partial checks; raw data absent |
| Checkpoint provenance | Weights, model config, training code commit, seed, preprocessing stats, checksum | Checkpoints absent; metadata only |
| Train/test integrity | Chronological cut, no leakage, target horizon, warm-up, validation split | Notebook documents one 70/30 split and 10-minute horizon |
| Forecast evaluation | Per-app WAPE/MAE/RMSE, paired uncertainty, quantile coverage, burst error | Partial metrics; no uncertainty/coverage calibration |
| Capacity calibration | Requests/replica vs latency/error SLO, saturation tests | Heuristic from average traffic |
| Policy baselines | Static, reactive, formula, LLM, guarded LLM, quantile | Plan only; no complete controlled benchmark |
| Actuation model | Startup delay, readiness, queueing, failures, termination | Not implemented |
| Outcome metrics | Overload duration, latency, error rate, cost, replica-minutes, churn | Partial simulation-only metrics |
| LLM reproducibility | Model ID, prompt hash/version, temperature, latency, tokens, cost, retries, parser failures | Partial config; telemetry incomplete |
| Alert quality | Precision, recall, false alarms, missed incidents, detection delay | Historical anecdotes only |
| Statistical analysis | Multiple splits/seeds, confidence intervals, paired tests | Not present |
| Environment | Python and package lock; hardware; run command | Unpinned requirements; no lock |
| Artifact retention | Raw inputs, forecasts, decisions, logs, configs and hashes | Outputs are reset at run start |

---

# Appendix C. Primary code references and paper sections

This appendix collects the strongest source anchors for claims in the report.

## Code anchors

- `agent/config.py`: paths and dotenv (lines 10–18); default app/replay/capacity (20–31); timer/spike/near-capacity/error thresholds (33–43); scale cooldown/guardrail (45–50); alert configuration (52–66); providers/models/retries (68–82).
- `agent/state.py`: `AgentState` (class, lines 14–47); `new_state()` (49–57).
- `agent/graph.py`: route selection (19–31); actual graph topology (33–56).
- `agent/nodes.py`: replica formula (36–40); output reset/log helpers (42–63); `Feed` (65–80); `store_prediction` (83–97); unusual-event rules (101–124); trigger priority (127 onward); report building (145–189); LLM facts/branches (193–207); auto scale (210–219); guardrail (223–228); no-op scaler (231–233); alert conditions (236–256); apply/log (259–285); email/alert construction (289 onward).
- `agent/llm.py`: system prompt (28–44); email prompt (46–55); prompt assembly (58–70); fake provider (74–78); retry logic (82–101); Gemini/Mistral API calls (104–135); parser (139–160); provider dispatcher/fallback (164 onward).
- `agent/mailer.py`: environment checks and SMTP fallback (16–39).
- `agent/metrics.py`: metric declarations (class initialization); exporter binding (76–85); host/process sampling (87–104); per-tick recording (116–167).
- `agent/run.py`: CLI parsing/setup (26–59); replay driver/summary and optional exporter serve loop (60–159).
- `notebook/predict.py`: data/model discovery (33–61); model class (65–74); data/checkpoint loading (77–94); inference features and inverse transform (98–132); backtest/CLI (145–185).

## Research paper anchors

- DeepRM: Section 2 background; Section 3.1 resource model; Section 3.2 state/action/reward; Section 3.3 REINFORCE training and policy-gradient equations; Section 3.4 alternate objectives; Section 4 evaluation; Section 5 practical discussion; Section 7 conclusion.
- PASM: Section 3.1–3.9 method definitions/equations; Algorithm 1 in Section 3.9 (PDF p.12); Section 4 results; Section 5 conclusions.
- Borg: Section 4 utilization; Section 5 job states/evictions; Section 6 scheduling; Section 7 resource-consumption heavy tails and queueing; Section 8 Autopilot vertical scaling; Section 9 trace data generation; Section 10 open questions; Section 12 conclusion.
- MOYA: Sections IV–V framework/agents; Section VI evaluation; Section VII discussion; Section VIII threats to validity; Section X conclusion.
- Bodra & Khairnar: Section 3 method; Table 1 / algorithm comparison; Section 5 cross-study synthesis; Section 6 performance-complexity discussion; Section 8 conclusion.
- Idowu & Idowu manuscript: Sections 3–7 perception/reasoning/action/memory/governance, use cases, risks, future research and conclusion. Verify authorship/publication status before formal citation.

---

# Appendix D. Bibliographic notes for the supplied research corpus

1. Mao, H., Alizadeh, M., Menache, I., and Kandula, S. “Resource Management with Deep Reinforcement Learning.” HotNets-XV, 2016. DOI: 10.1145/3005745.3005750.
2. Rajasekar, V. R., and Santhi, G. “Pervasive Auto-Scaling Method for Improving the Quality of Resource Allocation in Cloud Platforms.” *Big Data and Cognitive Computing*, 9(11), 294, 2025. DOI: 10.3390/bdcc9110294.
3. Tirmazi, M. et al. “Borg: the Next Generation.” *Proceedings of the 15th European Conference on Computer Systems (EuroSys)*, 2020. DOI: 10.1145/3342195.3387517.
4. Parthasarathy, V. B. et al. “Engineering LLM Powered Multi-agent Framework for Autonomous CloudOps.” CAIN 2025. DOI: 10.1109/CAIN66642.2025.00031.
5. Bodra, M., and Khairnar, V. “A Review of AI-Based Resource Allocation and Task Scheduling in Cloud Computing.” *Frontiers in Computer Science*, 7, 1678976, 2025. DOI: 10.3389/fcomp.2025.1678976.
6. “Agentic AI Frameworks for Autonomous Cloud Resource Management.” Supplied PDF dated 5 March 2026. Publication/authorship not verified; title-page and footer author strings differ. Treat as an unverified manuscript until independently confirmed.

---

## Final verdict

AegisCloud has a coherent, understandable prototype architecture and a useful start on forecasting, policy routing, guardrails, auditing, notifications, and monitoring. Its strongest research contribution today is the **integration and replay framework**: a forecast-informed, rule-triggered, LLM-assisted replica-count proposal constrained by deterministic safety logic and observed through structured logs.

The next phase should not be more presentation polish or broader claims. It should be reproducibility and experimental validity: package the data and model artifacts, fix credential leakage, model startup/queueing, measure real per-replica capacity, compare controlled baselines, and report statistically supported service-level outcomes. Until then, describe AegisCloud as a **trace-replay prototype**, not a deployed autonomous cloud scaler.
