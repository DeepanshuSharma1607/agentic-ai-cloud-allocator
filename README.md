# AegisCloud: Agentic AI Cloud Resource Allocator

> **An end-to-end AI systems project that replays real cloud workloads, forecasts future resource demand, learns scheduling policies with reinforcement learning, and uses an agentic control layer for unusual operational situations.**

## Overview

AegisCloud is a cloud resource allocation and scheduling system built around a simple idea:

> **Use historical workload data to recreate a realistic scheduling environment, predict what demand may come next, and learn better allocation decisions over time.**

The project uses Google cluster workload traces as the source of historical workload behaviour.

Instead of training a model to blindly copy Google's historical scheduling decisions, AegisCloud separates the problem into four layers:

```text
Historical Google Cluster Data
            │
            ▼
   Workload Processing + Replay
            │
            ▼
      Cluster Simulator
            │
     ┌──────┴──────┐
     ▼             ▼
GRU/LSTM       PPO Scheduler
Forecasting   Allocation Policy
     │             │
     └──────┬──────┘
            ▼
      Scheduling Decision
            │
            ▼
   Agentic Control Layer
   (only for unusual cases)
```

---

# Why this project?

Cloud schedulers must make decisions continuously:

- Which workload should run now?
- Which workload should wait?
- How much CPU and memory are currently available?
- What happens when many workloads arrive together?
- Should resources be preserved because future demand is expected to increase?
- What should happen when the workload pattern changes unexpectedly?

Traditional scheduling policies such as FIFO or simple greedy allocation provide useful baselines, but they do not explicitly optimize long-term outcomes from interaction with the environment.

AegisCloud explores whether a combination of:

```text
Forecasting + Reinforcement Learning + Agentic Orchestration
```

can make better resource allocation decisions in a simulated cloud environment.

---

# Core Idea

The system has three different "brains", each with a different responsibility.

## 1. Forecasting Model — "What may happen next?"

A GRU or LSTM learns workload patterns from historical data.

Example:

```text
Past workload:

CPU demand:
30 → 35 → 40 → 55

Memory demand:
40 → 42 → 45 → 60

Job arrivals:
5 → 7 → 10 → 16
```

The model predicts something like:

```text
Next interval:

Predicted CPU demand = high
Predicted memory demand = increasing
Predicted workload arrivals = increasing
```

The forecasting model does **not** schedule workloads.

Its only responsibility is:

> **Estimate future workload/resource demand.**

---

## 2. PPO Scheduler — "What should I do now?"

The PPO reinforcement-learning agent receives the current cluster state.

Example state:

```text
Available CPU:        45%
Available Memory:     60%

Waiting Queue:
Job A → CPU 20, Memory 10
Job B → CPU 10, Memory 30
Job C → CPU 35, Memory 20

Running Jobs:
4

Forecast:
CPU demand likely to increase soon
```

The PPO policy then chooses an action.

Early versions may use simple actions such as:

```text
0 → Schedule the next eligible job
1 → Wait / advance simulation time
```

Later versions may support richer actions:

```text
Choose job
Choose node
Wait
Reject invalid allocation
Request additional capacity
```

The PPO model learns through reward.

---

## 3. Agentic Layer — "Something unusual is happening. Investigate."

The agentic layer is **not called for every workload**.

Calling an LLM for every scheduling decision would increase cost and latency.

Normal scheduling remains:

```text
Replay/Environment → Forecast → PPO → Action
```

The agent is activated only when the system detects unusual conditions such as:

- queue growth beyond a threshold
- repeated scheduling failures
- unexpected workload spikes
- large forecast errors
- workload distribution drift
- persistent resource starvation

The agent can use tools such as:

```text
check_cluster_state()
check_queue()
check_forecast()
check_failures()
inspect_metrics()
recommend_recovery()
```

The long-term goal is:

```text
Fast decisions → PPO

Complex diagnosis and multi-step reasoning → Agent
```

---

# Real-World Data

The project is based on historical Google cluster workload data.

The raw dataset contains information such as:

```text
time
instance events
collection identifiers
priority
machine assignment
resource requests
resource usage
start time
end time
CPU usage distributions
cluster identifiers
event
failure status
```

Example events include:

```text
SCHEDULE
FINISH
FAIL
```

These historical events describe what happened in Google's environment.

However, the PPO agent should **not simply copy the historical `SCHEDULE` decision**.

Instead:

```text
Historical data
      │
      ▼
Extract workload behaviour
      │
      ▼
Replay workload arrivals and resource requirements
      │
      ▼
Our simulator recreates the scheduling problem
      │
      ▼
Our PPO policy makes its own decision
```

---

# Data Pipeline

The raw dataset is transformed into two useful representations.

## A. Replay Dataset

Used by the simulator.

Conceptually:

| instance_id | arrival_time | cpu_request | memory_request | duration | priority |
|---|---:|---:|---:|---:|---:|
| A | 0 | 20 | 10 | 5 | 200 |
| B | 1 | 30 | 20 | 8 | 360 |
| C | 2 | 40 | 15 | 4 | 103 |

The exact feature extraction will depend on the dataset schema and event semantics.

---

## B. Forecasting Dataset

Used to train the GRU/LSTM.

Historical workload information is aggregated into time windows.

Example:

| time_window | CPU demand | Memory demand | Job arrivals |
|---|---:|---:|---:|
| t1 | 30 | 40 | 5 |
| t2 | 35 | 42 | 7 |
| t3 | 45 | 50 | 10 |
| t4 | 60 | 65 | 15 |

The forecasting model learns:

```text
Past windows → Next workload/resource demand
```

---

# Workload Replay Simulator

Data replay means:

> **Take historical workloads and release them into our simulator according to historical time order.**

Example:

```text
Time 0 → Job A arrives
Time 1 → Job B arrives
Time 2 → Job C arrives
Time 4 → Job D arrives
```

The simulator maintains:

```text
Future Workloads
       │
       ▼
Waiting Queue
       │
       ▼
Running Workloads
       │
       ▼
Finished / Failed Workloads
```

A simplified simulation cycle:

```text
1. Advance simulated time
2. Release workloads arriving at this time
3. Add them to the waiting queue
4. Remove completed workloads
5. Release their resources
6. Build the current environment state
7. Get forecast information
8. PPO selects an action
9. Execute the action
10. Calculate reward
11. Repeat
```

---

# Phase 1: Minimal Cluster Simulator

The first implementation intentionally avoids unnecessary complexity.

Initial simulator:

```text
Single Cluster

Total CPU = fixed capacity
Total Memory = fixed capacity

Jobs:
- arrive
- wait
- start
- consume resources
- finish or fail
- release resources
```

Example:

```text
Cluster CPU = 100

Job A requires 20 CPU
Job B requires 30 CPU
Job C requires 40 CPU
```

After A and B start:

```text
Used CPU = 50
Free CPU = 50
```

If C starts:

```text
Used CPU = 90
Free CPU = 10
```

When A finishes:

```text
20 CPU is released
```

This simulator is the foundation of the project.

**No GRU, PPO, or LLM should be required before this phase works correctly.**

---

# Phase 2: Workload Forecasting

Once replay works, train a GRU or LSTM on historical workload sequences.

## Input

```text
Previous N time windows:

CPU demand history
Memory demand history
Workload arrival history
```

## Output

```text
Next time window:

Predicted CPU demand
Predicted memory demand
Predicted workload intensity / arrivals
```

The forecasting model becomes additional information available to the scheduler.

---

# Phase 3: Reinforcement Learning Scheduler

The replay simulator becomes a custom RL environment.

## State / Observation

Possible features:

```text
Available CPU
Available memory

Current queue size
Queue job features
Running workload features

Current simulated time

GRU/LSTM demand forecast
```

## Action

Initial action space:

```text
Schedule
Wait
```

Later:

```text
Select job
Select node
Wait
```

## Reward

The reward function should balance multiple objectives:

```text
+ Successful scheduling
+ Useful resource utilization
+ Job completion

- Excessive waiting time
- Resource starvation
- Invalid allocations
- Failed scheduling decisions
- Overload
```

The exact reward function will be experimentally designed and evaluated.

---

# Phase 4: Agentic Control Layer

The agentic layer is an escalation mechanism rather than the main scheduler.

```text
                  NORMAL OPERATION

Workload → Simulator → Forecast → PPO → Decision


                  UNUSUAL OPERATION

Anomaly / Drift / Failure
            │
            ▼
      Agent Activated
            │
            ▼
     Inspect system tools
            │
            ▼
   Multi-step diagnosis
            │
            ▼
 Recommendation / recovery
            │
            ▼
      Safety validation
```

Possible agent responsibilities:

- inspect queue growth
- compare forecast with observed demand
- detect repeated failures
- investigate workload changes
- recommend recovery actions
- trigger predefined safe workflows

The exact agent framework may evolve, but the design principle remains:

> **Do not use an expensive reasoning system for decisions that a fast trained policy can make directly.**

---

# Project Architecture

```text
┌───────────────────────────────────────────────────────────────┐
│                    HISTORICAL WORKLOAD DATA                   │
│                    Google Cluster Traces                      │
└───────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│                   DATA PROCESSING PIPELINE                    │
│                                                               │
│  Cleaning → Event Analysis → Feature Extraction → Time Order │
└───────────────────┬───────────────────────────┬───────────────┘
                    │                           │
                    ▼                           ▼
        ┌──────────────────────┐    ┌──────────────────────────┐
        │  Replay Dataset      │    │ Forecasting Dataset      │
        │                      │    │                          │
        │ arrival              │    │ CPU history              │
        │ resources            │    │ memory history           │
        │ duration             │    │ workload arrivals        │
        │ priority             │    │                          │
        └───────────┬──────────┘    └────────────┬─────────────┘
                    │                            │
                    ▼                            ▼
        ┌──────────────────────┐    ┌──────────────────────────┐
        │ Cluster Simulator   │    │ GRU / LSTM               │
        │ Queue + Resources   │    │ Demand Forecast          │
        └───────────┬──────────┘    └────────────┬─────────────┘
                    │                            │
                    └────────────┬───────────────┘
                                 ▼
                      ┌──────────────────────┐
                      │ PPO RL Scheduler    │
                      └──────────┬───────────┘
                                 ▼
                          Scheduling Action
                                 │
                                 ▼
                      ┌──────────────────────┐
                      │ Environment Result   │
                      │ + Reward             │
                      └──────────┬───────────┘
                                 │
                                 ▼
                      ┌──────────────────────┐
                      │ Agentic Escalation   │
                      │ Only when required   │
                      └──────────────────────┘
```

---

# Development Roadmap

## v0.1 — Data Understanding

- [ ] Inspect raw dataset columns
- [ ] Understand event semantics
- [ ] Parse `resource_request`
- [ ] Inspect resource usage fields
- [ ] Identify workload lifecycle information
- [ ] Remove irrelevant columns

**Goal:** Understand the real data before building models.

---

## v0.2 — Data Processing

- [ ] Create stable workload identifiers
- [ ] Sort workloads/events chronologically
- [ ] Extract arrival information
- [ ] Extract CPU and memory requirements
- [ ] Calculate or derive workload duration
- [ ] Preserve useful priority information
- [ ] Create processed datasets

**Goal:** Produce a clean replay dataset and forecasting dataset.

---

## v0.3 — Replay Simulator

- [ ] Simulation clock
- [ ] Workload arrivals
- [ ] Waiting queue
- [ ] Running workloads
- [ ] Resource accounting
- [ ] Completion handling
- [ ] Failure handling

**Goal:**

```text
Job arrives
→ Queue
→ Run
→ Consume resources
→ Finish
→ Release resources
```

---

## v0.4 — Forecasting

- [ ] Build time-window features
- [ ] Train GRU baseline
- [ ] Optionally compare with LSTM
- [ ] Evaluate forecasting accuracy
- [ ] Export trained model

**Goal:** Predict future workload/resource demand.

---

## v0.5 — Reinforcement Learning

- [ ] Convert simulator into Gymnasium environment
- [ ] Define observations
- [ ] Define action space
- [ ] Design reward
- [ ] Train PPO
- [ ] Track training metrics

**Goal:** Learn scheduling decisions through interaction.

---

## v0.6 — Baselines and Evaluation

Compare PPO against simpler schedulers:

- [ ] FIFO
- [ ] Greedy scheduling
- [ ] Priority-based heuristic
- [ ] Other justified baselines

Possible metrics:

```text
Average waiting time
Job completion rate
Resource utilization
Queue length
Scheduling failures
Starvation
```

**Goal:** Demonstrate whether the learned policy actually improves outcomes.

---

## v0.7 — Agentic Layer

- [ ] Detect abnormal situations
- [ ] Add system-inspection tools
- [ ] Add agent workflow
- [ ] Add safety validation
- [ ] Log agent decisions
- [ ] Measure additional latency/cost

**Goal:** Add meaningful agentic behaviour without putting an LLM in the critical scheduling path.

---

# Technology Stack

| Area | Technology |
|---|---|
| Programming | Python |
| Data Processing | Pandas, NumPy |
| Visualization | Matplotlib / Plotly |
| Deep Learning | PyTorch |
| Forecasting | GRU / LSTM |
| Reinforcement Learning | Gymnasium + Stable-Baselines3 PPO |
| Agentic Workflow | LangGraph or equivalent |
| Data Storage | Parquet / CSV |
| Experiment Tracking | TensorBoard / MLflow (optional) |
| Containerization | Docker (later phase) |
| Deployment / Cluster | Kubernetes/K3s (future extension) |

---

# Repository Structure

```text
aegiscloud/
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── samples/
│
├── notebooks/
│   ├── 01_data_exploration.ipynb
│   ├── 02_data_processing.ipynb
│   ├── 03_replay_validation.ipynb
│   ├── 04_forecasting.ipynb
│   └── 05_rl_experiments.ipynb
│
├── src/
│   ├── data/
│   │   ├── preprocessing.py
│   │   └── feature_engineering.py
│   │
│   ├── simulator/
│   │   ├── cluster.py
│   │   ├── queue.py
│   │   ├── workload.py
│   │   └── replay.py
│   │
│   ├── forecasting/
│   │   ├── dataset.py
│   │   ├── gru.py
│   │   └── train.py
│   │
│   ├── rl/
│   │   ├── environment.py
│   │   ├── reward.py
│   │   ├── train.py
│   │   └── evaluate.py
│   │
│   └── agent/
│       ├── tools.py
│       ├── workflow.py
│       └── guardrails.py
│
├── tests/
├── requirements.txt
└── README.md
```

---

# Experimental Questions

The project should answer measurable questions rather than assuming AI is automatically better.

1. Can workload forecasting improve scheduling decisions?
2. Does PPO outperform FIFO or simple heuristics?
3. Does forecast information improve PPO performance?
4. What happens when workload patterns change?
5. When does the agentic layer provide value?
6. What latency and cost does the agentic layer add?
7. How robust is the policy to workload distributions not seen during training?

---

# Important Design Principles

## 1. Real data first

The simulator should be driven by real workload behaviour rather than purely random job generation.

## 2. Build the system incrementally

The project should work at every major stage.

```text
Data
→ Simulator
→ Forecasting
→ RL
→ Agentic layer
```

## 3. Baselines are mandatory

A complicated PPO model is not useful unless it is compared against simpler scheduling strategies.

## 4. Agentic AI is not the fast path

LLM reasoning should be reserved for situations where additional reasoning and multi-step investigation are useful.

## 5. Avoid buzzword stacking

Every component must have a measurable responsibility:

```text
GRU/LSTM → Prediction
PPO      → Fast decision making
Agent    → Investigation and recovery
Simulator → Environment and evaluation
```

---

# Current Status

🚧 **Under active development**

Current focus:

```text
Google Cluster Data
        ↓
Understand event semantics
        ↓
Extract workload lifecycle
        ↓
Create processed replay dataset
```

The immediate goal is to successfully reproduce:

```text
Workload arrives
        ↓
Waiting Queue
        ↓
Scheduling decision
        ↓
Running
        ↓
Finish / Fail
        ↓
Resources released
```

Only after this foundation is validated will forecasting and reinforcement learning be added.

---

# Future Extensions

Possible future versions include:

- multi-node scheduling
- heterogeneous CPU/memory capacities
- dynamic capacity scaling
- Kubernetes integration
- live telemetry
- workload drift detection
- policy switching between trained schedulers
- agent-assisted incident response
- dashboard and experiment visualization

---
## Author

**Deepanshu Sharma**

---