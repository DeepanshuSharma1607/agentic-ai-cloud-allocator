# Agentic AI Cloud Resource Allocator and Auto-Scaling

### Predictive Reinforcement Learning for Cloud Resource Allocation with a Selective LLM-Based Auditor

This Project is a research project for making cloud resource allocation more efficient
and reliable.

The main idea is simple:

> **Predict upcoming workload, let a reinforcement learning controller make fast
> resource decisions continuously, and periodically use an LLM-based auditor to check
> whether the system is still behaving correctly.**

The LLM is **not** responsible for every cloud decision. The RL controller operates
continuously; the LLM is invoked periodically, on a fixed schedule, to audit system
health rather than approve or reject individual actions.

---

## 1. The Problem

Cloud workloads change over time — a food-delivery or ride-hailing style service sees
predictable daily peaks (breakfast, lunch, dinner), unpredictable spikes (promotions,
weather), and slow long-term growth.

If too few resources are allocated: queues grow, latency rises, requests start failing,
and SLA/SLO commitments are violated.

If too many resources are allocated: infrastructure cost rises, capacity sits idle, and
scaling becomes wasteful.

> **Goal: allocate enough resources to handle upcoming demand while minimizing
> unnecessary cost, waste, and SLA violations.**

---

## 2. Core Idea — Three Components

### 1. Forecasting
Predicts upcoming workload from recent history.
> *"What is likely to happen next?"*

### 2. Reinforcement Learning (PPO)
Chooses a scaling action given the current state and the forecast.
> *"Given what we expect, what should we do?"*

### 3. Selective LLM Auditor
Periodically (not on every decision) checks whether the forecasting/RL system is
behaving within acceptable ranges, and if not, recommends a corrective response.
> *"Is the system still behaving correctly — and if not, what should change?"*

A deterministic safety layer has final authority over whether any recommended
intervention is actually allowed to execute.

---

## 3. System Overview

```text
                  Historical Workload
                         |
                         v
                  +-------------+
                  | Forecasting |
                  |    Model    |
                  +-------------+
                         |
                         v
              Future Workload Forecast
                    + Confidence
                         |
                         v
                  +-------------+
                  | PPO / RL    |
                  | Controller  |
                  +-------------+
                         |
                         v
                  Resource Action
                         |
                         v
                  +-------------+
                  | Environment |
                  | / Simulator |
                  +-------------+
                         |
                         v
                 Actual Outcomes
                         |
                         v
              System Metrics & Reward
                         |
                         +--------------------+
                         |                    |
                    Next RL step       Periodic Audit
                                              |
                                              v
                                      +---------------+
                                      | LLM Auditor   |
                                      +---------------+
                                              |
                                     Health Assessment
                                    (Best / Mid / Worst)
                                              |
                                              v
                                  Recommendation / Diagnosis
                                              |
                                              v
                                  Deterministic Guardrails
                                              |
                                              v
                                   Allowed Intervention
```

---

## 4. Data Model

This Project uses **continuous telemetry**, not discrete job records — the workload is
modeled as a request-rate time series (like a live web/delivery service), not a queue
of individually-scheduled batch jobs. This was a deliberate choice: it matches the
target use case (an app with fluctuating live traffic) much more closely than a
DeepRM/Borg-style job-scheduling model, which is built for batch cluster workloads.

Each row of the dataset is one snapshot in time, containing:

**Demand & time context**
```text
timestamp, day, day_of_week, day_type (normal/rain/festival), time_of_day
request_rate
```

**Capacity**
```text
active_pods, pods_booting, spot_pods, ondemand_pods
```

**Reliability**
```text
preemption_event, error_rate
```

**Performance**
```text
cpu_utilization, memory_utilization, queue_length, p95_latency_ms
```

**Cost**
```text
cost_per_hour
```

This telemetry is what the forecaster learns from, what the RL controller observes as
its state, and what the LLM auditor summarizes when checking system health.

A separate **audit log** (built in Phase 5) will record: audit timestamp, current
metrics, recent trends, RL recommendation, whether the LLM was invoked, its
recommendation and reasoning, the final validated action, and the actual outcome.

**Data realism included so far:**
- Daily demand curves (morning/lunch/evening peaks), weekday vs. weekend shape
- Random day-type events (festival, rain) that shift demand independent of time-of-day
- Autocorrelated (not independent) noise, so bursts persist realistically
- A slow compounding growth trend over time
- Boot delay (capacity doesn't appear instantly) and a scaling cooldown period
- Spot vs. on-demand cost tiers, with random spot preemption events
- Latency/error-rate that stays flat under normal load, then degrades sharply past
  ~80% utilization

Deferred for later: multi-service correlation (e.g. order-placement and
delivery-tracking as two related but distinct demand streams).

---

## 5. How the System Works

**Step 1 — Observe.** The system collects workload/request rate, CPU/memory demand,
queue length, and timestamps. Initially from the synthetic generator described above;
public cloud traces (e.g. Google Borg) will be used later for generalization testing.

**Step 2 — Forecast.** The forecasting model receives recent history and predicts
near-future demand, along with a confidence/error estimate. It does not decide
resource allocation — that's the RL controller's job.

**Step 3 — Decide (PPO).** The RL controller receives current state + forecast and
chooses an action: do nothing, add N resource units, or remove a resource unit. It
learns, through repeated simulated experience, a long-term balance between
performance, SLA compliance, cost, waste, and scaling stability.

**Step 4 — Periodic audit.** Every 10–15 minutes (exact interval to be tuned
experimentally), the LLM receives a structured summary of recent trends — not raw
telemetry — and compares them against predefined best/mid/worst reference ranges based
on measurable outcomes (not subjective LLM opinion).

**Step 5 — Recommend, then validate.** The LLM may recommend: `CONTINUE`,
`USE_CONSERVATIVE_POLICY`, `TRIGGER_MODEL_RETRAINING`, `FALLBACK_TO_RULE_BASED_POLICY`,
or `REQUEST_HUMAN_REVIEW`. Every recommendation passes through a deterministic
validator (minimum/maximum resource limits, cooldowns, cost limits) before anything
executes.

---

## 6. Research Questions

- **RQ1 (Forecasting):** Can workload forecasting provide useful look-ahead information
  for proactive resource allocation?
- **RQ2 (RL):** Can PPO improve cloud resource allocation compared with classical
  scheduling/scaling approaches?
- **RQ3 (Forecast + RL):** Does adding forecasts improve the cost-performance-SLA
  trade-off of the RL controller?
- **RQ4 (Agentic Auditing):** Can a periodic LLM-based auditor detect degradation or
  poor decisions in the predictive RL system?
- **RQ5 (Selective Reasoning):** Can selective/periodic LLM auditing match or beat
  always-on LLM control while using far fewer LLM calls?
- **RQ6 (Robustness):** How does the system behave when workload patterns shift or the
  forecaster becomes inaccurate?

---

## 7. Baselines & Ablations

```text
FCFS
SJF
Packing Heuristic
Reactive Threshold Autoscaling      <- our current data's built-in baseline
PPO
PPO + Forecasting
PPO + Forecasting + Rule-Based Auditor
PPO + Forecasting + LLM Auditor (always-on)
PPO + Forecasting + Selective LLM Auditor      <- the proposed system
```

Comparing across this ladder isolates exactly which component — forecasting, RL,
or LLM auditing — is responsible for any observed improvement.

---

## 8. Evaluation Metrics

| Category | Metrics |
|---|---|
| Forecasting | MAE, RMSE, sMAPE, peak precision/recall, forecast lead time |
| Resource allocation | CPU/memory utilization, allocation failures, queueing delay, job slowdown |
| SLA/Performance | SLA/SLO violations, response/queue delay |
| Cost | Infrastructure cost, cost per workload, cost of unnecessary capacity |
| Efficiency | Resource waste, over-provisioning, scaling churn |
| LLM Auditor | Number of LLM calls, latency, inference cost, correct/missed degradation detection, false alarms, recommendation accuracy |

---

## 9. Technology Stack

| Purpose | Tools |
|---|---|
| Core language | Python |
| Data handling | NumPy, Pandas |
| Deep learning | PyTorch |
| RL environment interface | Gymnasium |
| RL algorithm | Stable-Baselines3 (PPO) |
| Forecasting | Statistical baselines, LSTM/GRU, Transformer (whichever is justified by experiments) |
| LLM auditor | LLM API with structured JSON output; optionally LangGraph for orchestration |
| Visualization | Matplotlib / Seaborn |
| Experimentation | Jupyter Notebook |
| *(Stretch goal)* Real execution | Docker, Kubernetes/K3s, Prometheus |

---

## 10. Development Roadmap

```text
Phase 1 — Simulator & Data           [IN PROGRESS — synthetic telemetry generator built]
Phase 2 — RL (Gymnasium + PPO)       [NEXT]
Phase 3 — Forecasting model
Phase 4 — Connect Forecast + RL
Phase 5 — LLM Auditor + audit logging
Phase 6 — Full ablation experiments
─────────────────────────────────────────────────
Phase 7 — Kubernetes/K3s integration     (stretch goal)
Phase 8 — Public trace validation        (stretch goal)
```

Phases 1–6 are the core deliverable for the paper and portfolio project. Phases 7–8
are documented as future work rather than required scope.

---

## 11. Project Principles

1. Don't use an LLM where a deterministic method works just as well.
2. The LLM is never the final authority — all interventions pass through deterministic
   safety checks.
3. Every major component must be experimentally justified, not assumed superior.
4. Synthetic data is clearly labeled as synthetic; public traces are used to test
   generalization, not presented as equivalent to synthetic results.
5. Forecasting, RL, and LLM auditing are evaluated both independently and together.
6. Experiments, configs, seeds, and results are documented for reproducibility.

---

## 12. Research Foundation

- **DeepRM** (Mao et al.) — foundation for framing resource management as an RL problem;
  used as conceptual inspiration, not reproduced directly, since our workload model is
  continuous telemetry rather than discrete jobs.
- **Borg** (Tirmazi et al.) — motivates realistic workload characteristics
  (heavy-tailed resource demand, priority tiers) and will be used for later
  generalization testing.
- **PASM (auto-scaling paper)** — inspiration for adaptive scaling, utilization, and
  QoS framing.
- **Agentic AI Cloud Management survey (Oladele & Idowu)** — motivates the agentic
  auditing layer and highlights the lack of standardized benchmarks for evaluating such
  systems, which this project's ablation ladder directly addresses.

---

## 13. Limitations

This Project is a research prototype, not a production autoscaler. Known limitations to
report explicitly rather than hide:
- Synthetic workload realism, however carefully modeled, is not real production traffic
- Forecasting and RL training stability are not guaranteed and will be evaluated, not assumed
- LLM latency, cost, and occasional recommendation errors are open risks the
  deterministic safety layer is specifically designed to contain
- Kubernetes-scale validation is a stretch goal, not core scope

---

## Status

🚧 **Research and development — Phase 1 in progress**

- [x] Architecture finalized (forecast → PPO → selective LLM auditor → safety layer)
- [x] Data schema defined (continuous telemetry)
- [x] Synthetic data generator built and validated (90-day sample; full-year version pending)
- [ ] Gymnasium RL environment
- [ ] PPO baseline training
- [ ] Forecasting model
- [ ] LLM auditor + audit log
- [ ] Full ablation experiments

All performance claims will be made only after experimental validation.

---

## References

1. Mao et al., *Resource Management with Deep Reinforcement Learning (DeepRM)*
2. Tirmazi et al., *Borg: the Next Generation*
3. Bodra & Khairnar, *Machine learning-based cloud resource allocation algorithms: a comprehensive comparative review*
4. Oladele & Idowu, *Agentic AI Frameworks for Autonomous Cloud Resource Management*
5. Rajasekar & Santhi, *Pervasive Auto-Scaling Method for Improving the Quality of Resource Allocation in Cloud Platforms*

## License

Apache License 2.0
