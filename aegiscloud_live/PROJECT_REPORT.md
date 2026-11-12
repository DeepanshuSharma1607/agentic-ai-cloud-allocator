# AegisCloud: A Forecast-Driven, LLM-Governed Autoscaler for Real Container Replicas

**Project Report**

| | |
|---|---|
| **Author** | Deepanshu Sharma |
| **Programme** | B.Tech Computer Science and Engineering |
| **Institution** | IILM University, Greater Noida |
| **Roll No. / Section** | 2410030927 / 3CSE6 |
| **Guide / Supervisor** | *(add)* |
| **Date** | November 2026 |
| **Repository** | *(add link)* |

---

## Abstract

Cloud applications must add replicas when traffic rises, but a new replica needs several seconds to start, so purely reactive autoscalers let users experience slow responses during every spike. This project builds **AegisCloud**, a prototype that tries to scale *ahead* of demand. An LSTM forecasts request volume ten simulated minutes ahead, and a LangGraph agent decides the replica count. A rule handles ordinary ticks, a large language model (Gemini) is consulted for unusual ticks and on a timer, and a guardrail clamps every proposal to the device limits. Decisions are applied to **real Docker containers** with enforced CPU and memory limits, behind a gateway that measures end-to-end latency, so start-up delay, overload and failures are measured rather than simulated.

The complete loop (traffic generation, metric collection, forecasting, agent decision, real scaling, dashboard, logging and alerting) was built and run. Measurements show real scale-out from 1 up to 9 replicas, replica start-up times of 4.3 to 10.5 s (mean 6.7 s, n = 22), and zero failed requests in the recorded agent session. The agent kept working when the LLM became unreachable, falling back to the rule-based scaler. The measurements also exposed weaknesses: on live traffic the LSTM (46.4% WAPE) was not better than a naive predictor (45.0%) and was worse than a 10-minute moving average (38.6%); capacity calibration varied by a factor of 2.3 between runs; and the load generator delivered only 51% of planned requests during heavy scaling. The planned four-policy comparison (static, reactive, HPA-rule, AegisCloud) was not completed, so no claim of superiority over baselines is made. The report documents the design, the measurements, and the failure modes honestly.

**Keywords:** autoscaling, predictive scaling, LSTM, LangGraph, LLM agents, Docker, SLO, cloud resource management

---

## Table of Contents

1. Introduction
2. Objectives
3. Background and Related Concepts
4. System Requirements
5. System Design
6. Implementation
7. Experimental Setup
8. Results
9. Discussion
10. Limitations and Threats to Validity
11. Conclusion
12. Future Work
13. Appendix A: How to Reproduce
14. Appendix B: Data Files
15. Appendix C: Glossary

---

## 1. Introduction

### 1.1 Problem

Elastic cloud platforms scale applications by adding or removing replicas. Common autoscalers, such as the Kubernetes Horizontal Pod Autoscaler (HPA), are **reactive**: they measure current load or CPU and then adjust. Because starting a replica takes real time, there is a window after each load spike during which capacity is too low and latency exceeds the service-level objective (SLO). Over-provisioning avoids this but wastes money.

### 1.2 Idea

If future load can be predicted, replicas can be started before the spike arrives. AegisCloud combines three components:

1. a **forecaster** (LSTM) that predicts request volume 10 ticks ahead;
2. a **governor** (LangGraph agent with an LLM) that turns forecasts and recent traffic into a replica count, with a rule-based path for normal conditions and a guardrail for safety;
3. an **actuator** that starts and drains **real containers** and measures what happens.

### 1.3 Scope

The project is a research prototype running on a single machine with synthetic load. It is intended to study the behaviour of forecast-driven, LLM-governed scaling under real start-up delay, not to be a production autoscaler.

---

## 2. Objectives

1. Build an end-to-end pipeline from live traffic to real container scaling.
2. Train and serve an LSTM forecaster for request volume.
3. Design an agent that uses an LLM safely (guardrail, fallback, alerts) for scaling decisions.
4. Measure real replica start-up time, latency, failures and cost.
5. Provide a reproducible harness to compare static, reactive, HPA-rule and AegisCloud policies.
6. Document what works, what does not, and what has and has not been proven.

Objectives 1 to 4 and 6 were achieved. Objective 5 was built (the runner and plotting code exist) but the comparison itself was not run.

---

## 3. Background and Related Concepts

**Service-level objective (SLO).** Here: p95 latency of at most 500 ms.

**Reactive autoscaling.** Replica count follows current utilisation. The Kubernetes HPA computes a desired count from the ratio of current to target utilisation. It is simple and robust but acts after load changes.

**Predictive autoscaling.** A model forecasts future load so capacity can be added early. Quality depends on forecast accuracy; poor forecasts cause both under- and over-provisioning.

**LSTM.** A recurrent neural network suited to sequences (Hochreiter and Schmidhuber, 1997). Used here to forecast request counts from a window of recent metrics.

**WAPE.** Weighted absolute percentage error, Σ|forecast − actual| / Σ actual. Chosen because plain percentage error is unstable when actual values are near zero.

**LLM agents.** A language model is given structured context and asked to choose an action. Such agents can be flexible but are slow and can fail, so they need guardrails and fallbacks. This project uses LangGraph to define the agent as a graph of nodes.

**Warm and cold start.** A new replica needs time (here about 4 to 10 s) before it can serve traffic. This delay is the reason forecasting can help at all.

*(When writing the final paper, add and verify references for reactive and predictive autoscaling and for LLM-based operations agents.)*

---

## 4. System Requirements

### 4.1 Functional

- Generate configurable request traffic (fixed, pattern, scheduled).
- Collect per-tick metrics (requests, latency, CPU, memory).
- Forecast 10 ticks ahead and expose the forecast through an API.
- Decide replica count each tick and apply it to real replicas.
- Log every decision and raise alerts on repeated LLM failure.
- Provide a dashboard for monitoring and control.
- Run baseline policies and record comparable metrics.

### 4.2 Non-functional

- Fault tolerance: the system must keep scaling when the LLM is unreachable.
- Observability: every component writes structured logs and plain CSV/JSON data.
- Portability: Docker, Kubernetes or plain-process backends.
- Reproducibility: documented run order and experiment commands.

### 4.3 Software and hardware

Python 3.10+, PyTorch, LangGraph, FastAPI/Uvicorn, Streamlit/Plotly, pandas/NumPy, Docker Desktop (or Kubernetes), Google Gemini API (optional Mistral). Hardware: a single Windows PC with Docker Desktop. *(Add CPU model, cores, RAM for the final version.)*

---

## 5. System Design

### 5.1 Architecture

```
 request sender ──► gateway ──► replica 1..N (containers, 0.5 core / 192 MB each)
                       │
                       ▼
                  collector ──► live_metrics.csv
                       │
                       ▼
          prediction service (LSTM, +10 ticks) ──► predictions.csv
                       │
                       ▼
          agent (LangGraph) ──► set_replicas(n) ──► gateway /infra/scale ──► ClusterManager
                       │
                       └──► actions.csv, agent_ticks.csv, alerts

          dashboard (Streamlit) reads CSVs and controls the sender
```

Time scale: 1 tick = 5 real seconds = 1 simulated minute. Replica start-up is real time and is not scaled.

### 5.2 Components

| Component | Responsibility |
|---|---|
| `traffic/loadgen` | Sends requests; fixed, pattern and scheduled modes; planned vs sent logging |
| `infra/gateway.py` | Routes to the least-busy Ready replica; measures end-to-end latency; returns 503 if no replica is Ready (counted as a real failure) |
| `traffic/collector` | Builds per-tick metrics from the gateway snapshot |
| `prediction/` | Preprocessing, LSTM inference, FastAPI service |
| `agent/` | LangGraph decision graph, LLM client, mailer |
| `infra/manager.py` | ClusterManager: keeps real count equal to the agent's request, drains before removal, records start-up time and resources |
| `infra/backends/` | Docker, Kubernetes and process backends |
| `infra/calibrate.py` | Measures per-replica capacity under the SLO |
| `infra/device.py` | Device profile (cores, RAM, per-replica share), max replicas |
| `frontend/` | Streamlit dashboard |
| `obs/` | Structured logging and live viewer |

### 5.3 Forecaster

An LSTM (hidden size 64) over a window of 8 normalised features, concatenated with static features, followed by a small feed-forward head (Linear → ReLU → Linear) that outputs the forecast. Inputs are z-score normalised and clipped. Training data is a 20,160-row series (14 days at one-minute resolution) with requests, p50/p95/p99 latency, achieved rps, app CPU, host CPU and app memory. The shipped model predicts 10 ticks ahead. Several checkpoints of the same horizon can be averaged.

### 5.4 Agent

Eight nodes run once per tick: `store_prediction`, `trigger_check`, `script_creator`, `llm_unusual`, `llm_timer`, `auto_scale`, `apply_and_log`, `alert_human`.

| Mode | Trigger | Decision |
|---|---|---|
| `auto` | Nothing unusual, timer not due | Rule: replicas needed for the highest demand or forecast of the last 10 ticks |
| `unusual` | Traffic or forecast looks abnormal | LLM |
| `timer` | Every 12 ticks (configurable) | LLM |

Safety design:

- every proposal is clamped to the minimum and maximum replica count of the device;
- on LLM failure the agent **holds** and the rule-based scaler continues;
- after repeated LLM failures an alert is written to file and emailed if SMTP is configured;
- scale-down drains replicas before removing them.

### 5.5 Baseline policies (for experiments)

| Policy | Rule |
|---|---|
| `static` | Fixed number of replicas |
| `reactive` | Replicas for the latest tick's requests plus a margin; up immediately, down after a calm period |
| `hpa` | The Kubernetes HPA rule re-implemented on CPU utilisation (target 60%, 15 s period, 5 min scale-down window, 10% tolerance); not the real HPA |
| `aegis` | Forecast plus LangGraph agent |

---

## 6. Implementation

### 6.1 Technology choices

| Need | Choice | Reason |
|---|---|---|
| Forecasting | PyTorch LSTM | Sequence model for time series |
| Agent orchestration | LangGraph | Explicit graph of nodes, easy to test and trace |
| LLM | Gemini (Mistral supported) | API access; model-agnostic client |
| Services | FastAPI + Uvicorn | Light HTTP services |
| Replicas | Docker (also K8s / process) | Real CPU and memory limits |
| Dashboard | Streamlit + Plotly | Fast to build, CSV-driven |
| Data | Plain CSV/JSON | Transparent, easy to analyse |

### 6.2 Development phases

1. **Part 1:** forecaster and prediction service.
2. **Part 2:** LangGraph agent with guardrail and mailer.
3. **Part 3:** live traffic, collector, dashboard and observability.
4. **Final phase:** real replicas (gateway, ClusterManager, backends, calibration, device profile, experiment runner).

### 6.3 Testing

A pytest suite in `tests/` covers the agent, prediction, traffic, observability, mailer and infrastructure modules. In addition, the system was exercised end to end with real containers and a real LLM, and the resulting data files were analysed (Section 8).

---

## 7. Experimental Setup

- **Machine:** single Windows PC with Docker Desktop, 10 maximum replicas, 0.5 core and 192 MB per replica.
- **Tick:** 5 real seconds.
- **SLO:** p95 ≤ 500 ms.
- **Capacity source:** calibration (Section 8.3).
- **LLM:** Gemini, timer every 12 ticks plus anomaly-triggered calls.
- **Traffic:** `pattern` mode (training-like daily shape) and `fixed` mode (constant requests per tick) for forced scale-out.
- **Planned comparison:** quiet → spike → quiet (20 / 30 / 30 ticks), four policies, 3 repetitions each, plus a no-LLM ablation. **This comparison was not run.**

---

## 8. Results

All numbers come from data files produced by the project.

### 8.1 Forecasting

Baselines on the seed data (10 ticks ahead):

| Predictor | WAPE |
|---|---|
| Same as now | about 29% |
| Same time yesterday | about 29% |
| 10-minute moving average | about 22.7% (21.4% on the last 30%) |

LSTM versus baselines on **live traffic** (2,730 ticks):

| Predictor | WAPE |
|---|---|
| LSTM (H = 10) | **46.4%** |
| Same as now | 45.0% |
| 10-minute moving average | **38.6%** |

The LSTM did not beat the naive predictor on live traffic and was clearly worse than the moving average. Live traffic differed from the training distribution (many idle ticks; mean about 113 versus about 158). In the agent logs the forecasts often tracked current traffic closely and overshot on spikes (for example a forecast of 1,746 when traffic was 586, followed by traffic of zero).

### 8.2 Real replica behaviour

- **Start-up time:** n = 22 real starts, mean **6.7 s**, std 1.5 s, minimum 4.3 s, maximum 10.5 s (about 1.3 ticks).
- **Real scale-out:** the agent raised real replicas from 1 up to 5 in the recorded cluster data and up to 9 in the final session.
- **Failures:** in the recorded agent session, 10,908 requests with **0 failed requests** and 0 "no replica ready" errors.
- **Latency:** p95 exceeded 500 ms in 22 of 70 ticks with a measurement (31%), worst case about 6.9 s, mostly when replicas were still starting or when bursts hit few replicas.

### 8.3 Capacity calibration

| Run | Result (requests/s per replica) |
|---|---|
| 9 Nov, 19:49 | 128.68 |
| 11 Nov, 21:06 | 128.68 |
| 11 Nov, 21:08 | 55.15 |

Two runs two minutes apart differed by 2.3×. The reported value is the highest passing step of a stepped load test, not an exact capacity. The lower value reduced the agent's capacity assumption from 547 to 234 requests per tick and led to over-provisioning (for example 9 replicas for a reading of 586 requests).

### 8.4 Agent behaviour

Final recorded run summary:

| Item | Value |
|---|---|
| Ticks processed | 291 (45 skipped because the agent was slower than the data) |
| LLM calls | 44 |
| Replica changes | 51 |
| Alerts | 2 |
| Replica-ticks (cost proxy) | 797 |
| Ticks above capacity | 10 (assumes instant replica start) |

Observations:

- 17 of 30 logged decisions were LLM decisions (unusual mode) and 13 were rule-based; 3 logged decisions were LLM-error holds.
- **Fault tolerance:** during a loss of DNS/internet the LLM failed 16 times in a row. The agent held, the rule-based scaler kept scaling, and an alert was saved to file (email failed for the same network reason).
- LLM calls took about 15 to 25 s, which is 3 to 5 ticks.
- The LLM's own explanations often said forecasts were "unreliable", consistent with Section 8.1.

### 8.5 Load generation

During the fixed-load phase the sender planned 18,262 requests and sent 9,373 (51%). About 60% of ticks recorded zero requests, with bursts of 600 to 800 in between. Scale calls to the gateway also timed out several times. A plausible but unconfirmed cause is that the gateway blocks while containers start.

### 8.6 Policy comparison

Not run. The runner (`infra/experiments/run_experiment.py`) and plotting code (`infra/experiments/plot.py`) are in place.

---

## 9. Discussion

**What the project demonstrates.** The full control loop works against real infrastructure. The LLM can sit inside an autoscaler in a guarded role: it made sensible-sounding decisions, and when it failed the system degraded gracefully to the rule-based scaler. Start-up delay is real and non-trivial relative to a one-minute tick, which is the motivation for prediction.

**Why the forecaster matters most.** Predictive scaling is only as good as its forecasts. A forecaster that is no better than "same as now" cannot provide the lead time the design depends on. A moving average beat it on live traffic, so a simple smoothed rule is a stronger baseline than expected and must be included in any fair comparison.

**Rule versus LLM.** Most ticks (the `auto` path) were decided by a rule using the maximum of recent demand and forecast. This is robust but conservative: one spike held 5 to 9 replicas for about 10 ticks. The LLM was invoked for a minority of ticks and its effect on outcomes was not isolated, because the no-LLM ablation was not run.

**Measurement quality.** Calibration variability and load-generator stalls add noise. Results should be read as a demonstration of the system's behaviour, not as precise performance numbers.

**Bugs and design issues found.**

1. The anomaly test computes forecast error as a percentage of actual traffic and produces absurd values (billions of percent) when traffic is near zero, which triggers unnecessary LLM calls. A floor on the denominator (for example a fraction of capacity) would fix this.
2. LLM latency is several ticks, so the agent skips ticks while waiting.
3. The internal "ticks above capacity" count assumes instant replica start and understates real overload.
4. Calibration should be repeated and the median used.

---

## 10. Limitations and Threats to Validity

1. **Time compression:** a simulated minute is 5 real seconds but start-up is real, so start-up is large relative to a tick.
2. **Single machine, single synthetic application,** one scenario, few repetitions; no claim about production clusters.
3. **Weak forecaster on live traffic.**
4. **Calibration instability** and **load-generator stalls.**
5. **HPA baseline is a re-implementation** of the rule, not the real HPA.
6. **Mixed sessions** append to the same CSVs; analysis must filter by timestamp.
7. **Data provenance:** the origin of the 20,160-row training series must be stated in any publication.
8. **No comparative or ablation results** yet.

---

## 11. Conclusion

AegisCloud shows that a forecast-driven, LLM-governed autoscaler can be built end to end and run against real containers, with real start-up delay, a guarded LLM role and graceful degradation when the LLM is unavailable. Measured start-up times (mean 6.7 s) and zero failed requests in the recorded session support the system's soundness. The project also shows, honestly, where the approach is weak: the forecaster did not beat simple baselines on live traffic, calibration and load generation were noisy, and the key comparison against reactive and HPA-style scaling remains to be done. The system and the experiment harness are ready for that next step.

---

## 12. Future Work

1. Retrain the forecaster on live traffic with a proper hold-out, and compare against the moving average and seasonal baselines.
2. Run the four-policy comparison with at least 3 repetitions and report mean ± std for SLO misses, failures and replica-seconds.
3. Add the no-LLM ablation (forecast plus rules) to isolate the LLM's effect.
4. Fix the anomaly metric and make scale calls non-blocking so the gateway keeps serving.
5. Calibrate automatically 3 times and use the median.
6. Add a +20 tick model and evaluate longer horizons.
7. Use the real Kubernetes HPA as a baseline on a multi-node cluster.
8. Evaluate on real production traces and more than one application.

---

## Appendix A: How to Reproduce

```bash
pip install -r requirements.txt -r requirements-infra.txt
# put the trained .pt in prediction/models/ and metrics_combined.csv in data/seed/
# create .env (project root) with GEMINI_API_KEY=...

python run_live.py --provider gemini                  # dashboard: http://localhost:8501

# spike test
python -m traffic.loadgen.cli start fixed --n 1500
python -m traffic.loadgen.cli stop

# experiments
python run_live.py --no-agent --no-frontend
python -m infra.experiments.run_experiment --policy static --static-n 3 --reps 3
python -m infra.experiments.run_experiment --policy reactive --reps 3
python -m infra.experiments.run_experiment --policy hpa --reps 3
python run_live.py --no-frontend --provider gemini
python -m infra.experiments.run_experiment --policy aegis --reps 3
python -m infra.experiments.plot
```

Calibrate three times with nothing else running and use the median. Check `data/loadgen/load_ticks.csv` (planned vs sent) before trusting a run.

## Appendix B: Data Files

| File | Content |
|---|---|
| `data/live/live_metrics.csv` | Per-tick traffic and latency |
| `data/predictions/predictions.csv` | Forecasts per tick |
| `data/agent/actions.csv`, `agent_ticks.csv` | Agent decisions and state |
| `data/agent/alerts/` | Saved alerts |
| `data/infra/replica_events.csv` | create / ready / draining / removed with start-up seconds |
| `data/infra/cluster_ticks.csv` | Per-tick desired, ready, requests, errors, p95 |
| `data/infra/resources.csv` | Real CPU and memory per replica |
| `data/infra/calibration.json` | Capacity measurement steps |
| `data/loadgen/load_ticks.csv` | Planned vs sent requests |
| `data/experiments/` | Experiment runs and summary |

## Appendix C: Glossary

| Term | Meaning |
|---|---|
| Tick | One simulated minute (5 real seconds by default) |
| Replica | One container running the application |
| SLO | Service-level objective: p95 latency ≤ 500 ms |
| p95 | 95th-percentile latency |
| WAPE | Weighted absolute percentage error |
| HPA | Kubernetes Horizontal Pod Autoscaler |
| Guardrail | Clamp that keeps proposals within device limits |
| Calibration | Measuring requests/s one replica can serve within the SLO |
