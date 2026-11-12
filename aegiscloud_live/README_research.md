# AegisCloud: research notes

Companion to `README.md`. This file collects what is needed to write the paper: the problem, the design, the experimental setup, **every result measured so far**, what can and cannot be claimed, and what is still missing.

> **Status: preliminary.** The system is built and has run end to end with real containers and a real LLM. The planned four-policy comparison (static / reactive / HPA-rule / AegisCloud) has **not** been run yet, so no comparative claim is supported by data today.

---

## 1. Problem and idea

Reactive autoscalers (such as the Kubernetes HPA rule) add capacity only after load has risen, so users see latency while new replicas start. AegisCloud tests a **predictive + LLM-governed** alternative:

1. An **LSTM** forecasts request volume 10 ticks (simulated minutes) ahead from recent metrics.
2. A **LangGraph agent** decides the replica count. A rule handles normal ticks. An **LLM** is consulted for unusual ticks and on a timer, and a guardrail clamps every proposal to device limits.
3. Decisions are applied to **real Docker containers** with enforced CPU and memory limits, so start-up delay, overload, and latency are measured.

**Research question:** Does forecast-driven, LLM-governed scaling reduce SLO violations and/or cost compared with reactive and rule-based scaling when replicas take real time to start?

## 2. Contributions you can claim (supported by the system as built)

- An open prototype that closes the loop **forecast → agent → real container scaling**, with the LLM in a guarded, fault-tolerant role (the agent holds and the rule-based scaler continues when the LLM fails).
- A measurement harness that records **real replica start-up times**, per-tick latency and errors at a gateway, and per-replica CPU and memory.
- A reproducible experiment runner for four policies on one spike scenario (`infra/experiments/run_experiment.py`).
- Measured observations about the failure modes of this design (Section 6). These are useful as an honest "experience" or negative-result contribution.

## 3. System summary (for the Method section)

| Part | Detail |
|---|---|
| Forecaster | LSTM (hidden size 64) plus static features, head Linear(64+static → 64) → ReLU → Linear(64 → 1); 8 input features; z-score normalisation with clipping; H = 10 model shipped |
| Training data | `metrics_combined.csv`: 20,160 one-minute rows (14 days): requests, p50/p95/p99 latency, achieved rps, app CPU, host CPU, app memory. **State the data source and how it was produced in the paper.** |
| Agent | LangGraph, 8 nodes: `store_prediction`, `trigger_check`, `script_creator`, `llm_unusual`, `llm_timer`, `auto_scale`, `apply_and_log`, `alert_human` |
| LLM | Gemini (Mistral supported); timer every 12 ticks plus anomaly-triggered calls |
| Replicas | Docker containers, 0.5 core and 192 MB each, 1 to 10 replicas, least-busy routing at a gateway |
| SLO | p95 latency ≤ 500 ms |
| Tick | 5 real seconds = 1 simulated minute |
| Hardware | Single Windows PC with Docker Desktop (state CPU model, cores, RAM in the paper) |

## 4. Experimental protocol (to run)

Scenario per repetition: **quiet → sudden spike → quiet** (defaults: 20 / 30 / 30 ticks; base 25% and spike 80% of machine capacity unless `--base` / `--spike` is given).

Policies: `static` (fixed N), `reactive` (latest tick plus margin), `hpa` (CPU-utilisation rule re-implemented: target 60%, 15 s period, 5 min scale-down window, 10% tolerance), `aegis` (this system). 3 repetitions each.

Metrics: SLO-miss ticks and percentage, failed requests (including 503 when no replica is Ready), replica-seconds (cost proxy), start-up times, scaling reaction time.

```bash
python run_live.py --no-agent --no-frontend
python -m infra.experiments.run_experiment --policy static --static-n 3 --reps 3
python -m infra.experiments.run_experiment --policy reactive --reps 3
python -m infra.experiments.run_experiment --policy hpa --reps 3
# restart with the agent:
python run_live.py --no-frontend --provider gemini
python -m infra.experiments.run_experiment --policy aegis --reps 3
python -m infra.experiments.plot
```

**Recommended extra run (ablation):** forecaster plus rules **without** the LLM, versus the full agent. Without it the paper cannot claim the LLM helps.

### Results table to fill (not yet measured)

| Policy | SLO-miss % (mean ± std) | Failed requests | Replica-seconds | Notes |
|---|---|---|---|---|
| static (N=3) | not run | not run | not run | |
| reactive | not run | not run | not run | |
| HPA rule | not run | not run | not run | |
| AegisCloud | not run | not run | not run | |
| Forecast + rules, no LLM (ablation) | not run | not run | not run | |

## 5. Results measured so far

All numbers below come from the data files produced by this project. Nothing is estimated.

### 5.1 Forecasting

**Simple baselines on the seed data** (predict the request count 10 ticks ahead, WAPE = Σ|error| / Σ actual):

| Predictor | WAPE |
|---|---|
| Same as now (naive) | about 29% |
| Same time yesterday | about 29% |
| 10-minute moving average | about 22.7% (21.4% on the last 30% of the data) |

**LSTM on live traffic** (2,730 live ticks, forecast made at tick t compared with the actual at t+10):

| Predictor | WAPE |
|---|---|
| LSTM (H = 10) | **46.4%** |
| Same as now | 45.0% |
| 10-minute moving average | **38.6%** |

Reading: on the live traffic collected so far the LSTM was **not better than the naive baseline and clearly worse than the moving average**. Live traffic differs from the training data (many idle ticks, mean about 113 versus about 158 in training). The LSTM's hold-out WAPE on the training data was not recorded here; run `train_horizon.py --train-fraction 0.7` and report it.

No +20 minute model exists, so no +20 results.

### 5.2 Real replica behaviour

- **Replica start-up time (real containers):** n = 22 starts, mean **6.7 s**, std 1.5 s, min 4.3 s, max 10.5 s. At 5 s per tick this is about 1.3 ticks.
- **Real scale-out was demonstrated:** the agent raised the real replica count from 1 up to 5 in the recorded cluster data (`desired` and `ready` both reached 5), and up to 9 in a later session.
- **Requests and errors in the recorded agent session** (`data/infra/cluster_ticks.csv`, session after 21:20): 10,908 requests, **0 failed requests**, 0 "no replica ready" errors.
- **Latency:** in that session p95 exceeded the 500 ms target in 22 of 70 ticks that had a measurement (31%), with a worst case of about 6.9 s. Most of these occurred while `ready` was lower than `desired` (replicas still starting) or when bursts arrived at a single replica.

### 5.3 Capacity calibration

Calibration sends increasing request rates to one replica and records the highest step that meets p95 ≤ 500 ms.

| Run | Result (requests/s per replica) |
|---|---|
| 9 Nov 19:49 | 128.68 |
| 11 Nov 21:06 | 128.68 |
| 11 Nov 21:08 | **55.15** (step 2 at 91.9 rps already had p95 about 885 ms) |

Two runs two minutes apart differed by 2.3×. The stored value is the highest *passing step*, not an exact capacity (true capacity lies between the last passing and first failing step). Calibration is **sensitive to machine load**. The 55.15 value set the agent's capacity to 234 requests per tick instead of 547, which caused over-provisioning in the following session (for example 9 replicas for a traffic reading of 586).

### 5.4 The LLM agent

From the final recorded run (`summary` printed on exit):

| Item | Value |
|---|---|
| Ticks processed | 291 (45 skipped because the agent was slower than the data) |
| LLM calls | 44 (Gemini) |
| Replica changes | 51 |
| Alerts | 2 |
| Replica-ticks (cost proxy) | 797 |
| Ticks above capacity | 10 (new replicas are assumed to start instantly in this internal count) |

- Of the 30 decisions logged in the data snapshot, 17 were in `unusual` mode (LLM) and 13 in `auto` mode; 3 of the logged decisions were LLM-error "holds".
- **Fault tolerance observed:** when the PC lost DNS/internet, the LLM failed 16 times in a row. The agent held position on those ticks, the rule-based scaler kept scaling, and an alert was written to file (the email could not be sent for the same reason).
- **LLM latency:** about 15 to 25 s per call (3 to 5 ticks at a 5 s tick).
- Earlier runs with the key missing used a "fake LLM"; those must not be reported as LLM results.

### 5.5 Load generation

In the fixed-load phase of the final session the sender **planned 18,262 requests but sent 9,373 (51%)**, and about 60% of ticks recorded zero requests with occasional bursts of 600 to 800. Scale calls to the gateway also timed out several times. A plausible cause is that the gateway blocks while containers start, so requests queue and then arrive in bursts; this has **not** been confirmed. This affects every latency and forecast number above and must be disclosed.

## 6. Threats to validity (put these in the paper)

1. **Time compression.** A simulated minute is 5 real seconds but container start-up is real time, so start-up is large relative to a tick. This is a design choice, not a flaw, but it changes how the results map to real clusters.
2. **Single machine, single synthetic application,** one spike scenario, 3 repetitions. No claim about production clusters.
3. **Forecaster underperforms simple baselines on live traffic** (Section 5.1).
4. **Calibration instability** (Section 5.3) and **load-generator stalls** (Section 5.5) add noise to every measurement.
5. **Anomaly trigger.** The "forecast error %" test divides by near-zero actual traffic and produces absurd values (for example billions of percent) on idle ticks, which triggers LLM calls that are not needed.
6. **Agent slower than the data.** LLM calls take several ticks, so the agent skips ticks while it waits. The `ticks above capacity` count assumes instant replica start-up and understates real overload.
7. **HPA baseline is a re-implementation** of the rule, not the real Kubernetes HPA.
8. **Mixed sessions.** Several runs append to the same CSVs; analysis must filter by session timestamp.
9. **Data provenance.** The paper must state where the 20,160-row training series came from and which parts are measured versus synthetic.

## 7. Claims: what is and is not supported today

| Claim | Supported now? |
|---|---|
| The prototype scales real containers from forecasts and agent decisions | **Yes** (Section 5.2) |
| Real replica start-up takes about 4 to 10 s on this setup | **Yes** (n = 22) |
| The agent keeps working when the LLM is unavailable | **Yes** (observed, one incident) |
| The LSTM forecast is accurate | **No** (worse than a moving average on live traffic) |
| AegisCloud reduces SLO violations versus reactive / HPA | **No** (not run) |
| AegisCloud reduces cost versus static / reactive | **No** (not run) |
| The LLM improves decisions | **No** (no ablation) |

Until the four-policy experiment is run, the honest framing is a **system and measurement paper**: design, implementation, measured start-up behaviour, and an analysis of failure modes of forecast-driven LLM scaling. If you run the experiments later, update the table in Section 4 and revise the claims table above.

## 8. Suggested paper outline

1. **Abstract:** problem, system, what was measured, main finding, honest scope. Mention real containers and real start-up times.
2. **Introduction:** cost of latency during scale-out; reactive scaling delay; the predictive plus LLM idea; contributions (Section 2).
3. **Related work:** reactive and rule-based autoscaling (Kubernetes HPA), predictive autoscaling with forecasting models, LLM agents for operations. Cite and verify your own references; do not cite from memory.
4. **System design:** Section 3, with the architecture diagram from `README.md` redrawn.
5. **Experimental setup:** Section 4 (hardware, SLO, scenario, policies, repetitions).
6. **Results:** forecasting (5.1), real replica behaviour (5.2), calibration (5.3), agent behaviour (5.4), and policy comparison if run.
7. **Discussion and threats to validity:** Section 6.
8. **Conclusion and future work:** retrain the forecaster on live traffic; ablation without the LLM; fix anomaly metric; non-blocking gateway scaling; multi-node cluster; real HPA baseline.

### Figures and tables worth including

- Architecture diagram (forecast → agent → gateway → replicas).
- Timeline of one spike: traffic, forecast, desired vs ready replicas, p95 (from `cluster_ticks.csv` and `actions.csv`).
- Start-up time distribution (from `replica_events.csv`).
- Forecast WAPE table (LSTM vs naive vs moving average).
- Calibration steps (rps vs p95) from `calibration.json`.
- Policy comparison table (when available).

## 9. Reproducibility checklist before submission

- [ ] Record hardware (CPU, cores, RAM, OS, Docker version) and Python / library versions.
- [ ] State dataset source and how it was produced.
- [ ] Calibrate 3 times, with nothing else running; report the median and the spread.
- [ ] Check `data/loadgen/load_ticks.csv`: planned vs sent should match closely.
- [ ] Back up `data/` after each run; analyse by session timestamp.
- [ ] Report the LSTM hold-out WAPE from `train_horizon.py --train-fraction 0.7`.
- [ ] Run and report at least one policy comparison with 3 repetitions, mean ± std.
- [ ] Add the no-LLM ablation, or state clearly that it was not run.
- [ ] Say that time is compressed (1 tick = 5 s) and what that implies.
- [ ] Keep API keys out of the repository.

## 10. Citation (placeholder)

```
Sharma, D. AegisCloud: a forecast-driven, LLM-governed autoscaler for real container replicas. 2026.
Code: https://github.com/DeepanshuSharma1607/  (add the repository name)
```
