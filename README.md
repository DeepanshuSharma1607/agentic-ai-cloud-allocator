# AegisCloud
### Predictive, Reinforcement-Learning-Based Cloud Resource Allocation with an Agentic Decision Gate

AegisCloud is an experimental cloud resource management system designed to answer a practical question:

> **Can a cloud scheduler predict an upcoming workload peak, prepare resources before the peak arrives, and still avoid wasting money and infrastructure when the predicted peak does not materialize?**

The project combines **time-series demand forecasting**, **reinforcement learning (RL)**, **Kubernetes-based execution**, **telemetry**, and a **conditional agentic reasoning layer**.

The goal is not to put an LLM in every scheduling decision. The fast path remains numerical and automated. The agentic layer is invoked only when a high-impact scaling decision needs additional contextual reasoning.

---

## 1. The Real-World Problem

Modern cloud applications rarely experience constant workloads.

A service can be relatively quiet at 8:00 AM and suddenly receive much more traffic at 9:00 AM. Similar patterns can appear around:

- commuting hours,
- breakfast/lunch/dinner periods,
- office start/end times,
- weekends,
- promotions,
- product launches,
- scheduled batch workloads,
- seasonal events,
- unexpected traffic spikes.

For a ride-hailing or food-delivery style workload, a simplified pattern could look like:

```text
08:30   ────────  1,000 requests/min
08:40   ───────── 1,200
08:50   ───────────── 1,700
08:55   ───────────────── 2,200
09:00   ─────────────────────── 2,800  ← peak
09:10   ───────────────────────── 3,000
```

A purely reactive autoscaler waits until resource pressure is already visible.

That creates two opposite problems:

### Under-provisioning

Resources are added too late.

Possible consequences include:

- increased latency,
- queued work,
- failed requests,
- SLA/SLO violations,
- poor user experience.

### Over-provisioning

Resources are added too early or in excessive quantities.

Possible consequences include:

- unused compute capacity,
- unnecessary infrastructure cost,
- lower resource efficiency.

Cloud resource allocation is therefore a multi-objective problem involving performance, resource utilization, cost, availability, and QoS. The supplied cloud-resource-allocation review identifies these as central evaluation dimensions and describes the shift from reactive allocation toward predictive and adaptive allocation. 

---

# 2. The Core Idea

AegisCloud separates the problem into four responsibilities:

```text
                    HISTORICAL WORKLOAD DATA
                              │
                              ▼
                    ┌───────────────────┐
                    │ Demand Forecast   │
                    │    Transformer    │
                    └─────────┬─────────┘
                              │
                    "What is likely next?"
                              │
                              ▼
                    ┌───────────────────┐
                    │ PPO / Deep RL     │
                    │ Resource Manager  │
                    └─────────┬─────────┘
                              │
                    "What should we do?"
                              │
                              ▼
                ┌────────────────────────────┐
                │ CONDITIONAL AGENTIC GATE   │
                │                            │
                │ Recent telemetry           │
                │ Cost                       │
                │ SLA/SLO                    │
                │ Historical context         │
                │ Safety constraints         │
                └─────────────┬──────────────┘
                              │
                     Approve / Modify / Reject
                              │
                              ▼
                         Kubernetes
                              │
                              ▼
                         Actual Outcome
                              │
                              ▼
                         RL Reward
```

The three intelligent components therefore have different jobs:

| Component | Main question |
|---|---|
| **Transformer** | What is likely to happen next? |
| **RL/PPO** | What action should the system take? |
| **Agentic layer** | Is this high-impact action sensible given the wider context? |

Kubernetes is the execution layer.

---

# 3. Example: A Morning Demand Peak

Assume the system is managing a service whose demand regularly rises around 9:00 AM.

At **8:55 AM**, the system observes recent telemetry and historical patterns.

### Forecasting model

The Transformer receives a recent time window such as:

```text
timestamp
request rate
CPU utilization
memory utilization
active pods
queue length
previous demand
time-of-day
day-of-week
```

It produces something such as:

```text
Predicted demand:       2,500 requests/min
Peak probability:       0.91
Forecast horizon:       15 minutes
```

The model is answering:

> "A significant increase is likely."

### RL system

The RL agent sees the predicted demand together with the current cluster state:

```text
Current demand:        1,800
Current CPU:           68%
Available capacity:    18%
Predicted peak:        2,500
Current cost:          ...
```

Its action space might include:

```text
DO NOTHING
ADD 1 RESOURCE UNIT
ADD 2 RESOURCE UNITS
ADD 3 RESOURCE UNITS
SCALE DOWN
```

Suppose PPO recommends:

```text
ACTION = ADD 2
```

### Agentic decision gate

Only now does the agentic layer become relevant.

It checks:

```text
Forecast confidence
+
RL recommendation
+
Last 5 minutes of demand
+
Current resource pressure
+
Expected cost
+
SLA/SLO risk
+
Scaling limits
```

For example, if demand has been rising continuously:

```text
8:50   1,700
8:51   1,780
8:52   1,850
8:53   1,930
8:54   2,050
8:55   2,180
```

the agent may approve:

```text
APPROVE → ADD 2
```

If the forecast says "peak" but the latest measurements show demand rapidly falling, it can instead:

```text
REJECT / WAIT
```

This makes the agentic layer a **high-impact decision gate**, not a replacement for the scheduler.

---

# 4. Why Reinforcement Learning?

Cloud resource management is a sequential decision problem.

An action taken now changes the state of the system later.

For example:

```text
Scale now
    ↓
more capacity
    ↓
higher cost
    ↓
possibly lower latency
    ↓
possibly fewer failures during peak
```

The opposite decision also has consequences:

```text
Do not scale
    ↓
lower cost
    ↓
but potentially insufficient capacity
    ↓
higher queueing / latency
```

This trade-off makes RL a natural fit.

DeepRM is an important foundation for this part of AegisCloud. Its work formulates dynamic resource scheduling as an RL problem, uses rewards to optimize scheduling objectives, and evaluates the approach in simulation on synthetic workloads against traditional heuristics such as SJF and packing-based scheduling. 

AegisCloud extends that idea toward a more cloud-oriented setting in which the objective can include not only scheduling efficiency but also cost, resource waste, and service quality.

---

# 5. Why a Transformer?

RL decides **what action to take**, but it is useful for the RL system to know what the near future may look like.

Historical telemetry contains temporal structure:

```text
hour of day
day of week
recent demand
recent growth rate
previous peaks
resource utilization
queue behavior
```

A forecasting model can learn those dependencies and estimate future demand.

This enables:

```text
Reactive:
"CPU is high → scale now"

Predictive:
"Demand is rising and historical behavior indicates
a high probability of a peak within the next 15 minutes
→ prepare capacity before pressure becomes critical"
```

The supplied cloud-resource-allocation review specifically discusses neural models that learn from historical data to predict workload demand and enable proactive allocation, including hybrid prediction/optimization approaches evaluated with Google workload traces. 

The Transformer is therefore not the scheduler. It is the **look-ahead component**.

---

# 6. Why the Agentic Layer?

An LLM is not the most appropriate component for every numerical scheduling decision.

Calling an LLM for every pod/container would add:

- latency,
- inference cost,
- unnecessary complexity,
- another failure mode.

Instead, AegisCloud uses the agentic layer selectively.

### Normal case

```text
Workload
   ↓
PPO
   ↓
Kubernetes
```

### High-impact case

```text
Forecast predicts peak
        +
RL recommends scaling
        ↓
Agentic decision gate
        ↓
Approve / modify / reject
        ↓
Kubernetes
```

This design keeps the fast path fast while still allowing contextual reasoning for decisions with meaningful cost or reliability implications.

The supplied Agentic AI cloud-management paper describes agentic systems as combining perception, reasoning, action, memory, and governance in a closed loop. It also describes multi-timescale reasoning and the use of telemetry, operational history, policies, and cloud control-plane actions. 

AegisCloud applies that idea specifically to predictive resource-management decisions.

---

# 7. What the Agent Can Check

The agentic gate can receive structured information from tools rather than raw infrastructure logs.

Example:

```json
{
  "forecast": {
    "peak_probability": 0.91,
    "predicted_demand": 2500
  },
  "rl_action": {
    "action": "scale_up",
    "amount": 2
  },
  "recent_metrics": {
    "cpu": 0.68,
    "memory": 0.62,
    "demand_growth": 0.21
  },
  "cost": {
    "additional_hourly_cost": 12.5
  },
  "policy": {
    "max_scale_step": 3,
    "sla_priority": "high"
  }
}
```

It can then produce a structured decision:

```text
Decision: APPROVE

Reason:
- Forecast confidence is high
- Demand has increased for the last 5 minutes
- Current capacity is insufficient for predicted demand
- Proposed scaling remains within policy limits
- Expected SLA risk is higher than the additional resource cost

Action:
Scale by 2 units
Re-evaluate after 5 minutes
```

The exact final execution should still pass through deterministic safety checks.

---

# 8. Why the Reward Matters

The system should not reward the RL agent simply for "scaling successfully."

The objective is a trade-off.

A possible reward design is:

```text
Reward =
    performance benefit
  + SLA benefit
  - infrastructure cost
  - unused capacity
  - scaling churn
  - scheduling failures
```

The exact weights should be evaluated experimentally rather than assumed.

For example:

### Correct proactive decision

```text
Peak predicted
      ↓
2 units added
      ↓
Peak occurs
      ↓
SLA maintained
      ↓
high utilization
      ↓
moderate cost
      ↓
HIGH REWARD
```

### False alarm

```text
Peak predicted
      ↓
2 units added
      ↓
Peak does not happen
      ↓
resources mostly idle
      ↓
unnecessary cost
      ↓
LOW REWARD
```

### Missed peak

```text
Peak predicted poorly
      ↓
No scaling
      ↓
peak arrives
      ↓
latency / failures increase
      ↓
LARGE NEGATIVE REWARD
```

Over many episodes, the RL system learns the long-term trade-off rather than following a simple "CPU > threshold" rule.

DeepRM provides direct precedent for using different reward formulations to optimize different resource-management objectives. 

---

# 9. Why Kubernetes?

Kubernetes provides the execution environment in which the learned policy can eventually be evaluated.

The research system can move through increasingly realistic stages:

```text
Stage 1
Synthetic simulator
       ↓
Stage 2
Trace-driven simulator
       ↓
Stage 3
Local K3s cluster
       ↓
Stage 4
Prometheus telemetry
       ↓
Stage 5
Custom scheduling / scaling integration
```

This separation is important because the learning problem can be developed and tested before introducing the operational complexity of a real cluster.

Kubernetes is therefore not the "AI." It is the **environment and execution layer**.

---

# 10. Why Prometheus?

The learning and decision layers need observations.

Prometheus can provide metrics such as:

```text
CPU utilization
Memory utilization
Pod count
Pending pods
Request rate
Latency
Error rate
Resource availability
```

These become the system's current state.

The agentic-cloud literature also emphasizes telemetry as the perception layer of autonomous cloud-management systems.

---

# 11. What Makes This Different from Simple Autoscaling?

A normal threshold-based system might look like:

```text
if CPU > 80%:
    scale_up()
```

AegisCloud instead attempts:

```text
Historical behavior
      +
Current telemetry
      +
Future demand forecast
      +
RL policy
      +
Cost/SLA context
      ↓
Final action
```

The difference is **prediction + sequential optimization + contextual decision validation**.

This is particularly important for workloads where waiting for CPU utilization to become critical is already too late.

The supplied agentic-resource-management paper similarly describes predictive autoscaling as using historical patterns and leading indicators before resource pressure fully materializes, combined with reactive adjustments. 

---

# 12. Why Not Use the LLM for Everything?

Because that would make the system unnecessarily expensive and slow.

AegisCloud deliberately uses a hierarchy:

```text
                 FAST PATH
Telemetry → Forecast → PPO
                 │
         routine decisions
                 │
                 ▼
             Kubernetes


                 SLOW PATH
Forecast + PPO disagreement/high-impact action
                 │
                 ▼
          Agentic reasoning
                 │
                 ▼
     policy / cost / SLA checks
                 │
                 ▼
             Kubernetes
```

This makes it possible to measure whether the agentic layer actually adds value.

Important evaluation questions include:

```text
Does the agent reduce unnecessary scaling?

Does it reduce LLM calls compared with always-on LLM scheduling?

Does it improve SLA outcomes?

Does it reduce infrastructure cost?

Does it reduce resource waste?

Does it improve decision quality during unusual workload conditions?
```

---

# 13. Why Synthetic Data First?

Real production datasets from companies such as Swiggy, Zomato, or Rapido are generally not available for unrestricted research use.

Therefore, the initial experiments can use synthetic workload traces designed to reproduce realistic temporal behavior:

```text
Morning peaks
Lunch peaks
Evening peaks
Weekday/weekend differences
Gradual trends
Sudden spikes
False peaks
Low-demand periods
Unusual events
```

Synthetic data gives precise control over the experimental conditions.

Later, the project can validate generalization using public cluster/workload traces where licensing and data availability permit.

The Borg research is useful here because its public traces demonstrate that production cluster workloads are highly variable, heavy-tailed, and differ substantially across clusters. The 2019 Borg trace also reports strong differences in workload mix and very large variation in job resource consumption. 

The goal is therefore **not** to claim that synthetic data is "real Swiggy data." The goal is to create controlled experiments first and then test generalization against independent traces.

---

# 14. Technology Stack and Why Each Technology Exists

| Technology | Role | Why it is useful |
|---|---|---|
| **Python** | Core implementation | Fast experimentation and strong ML ecosystem |
| **NumPy** | Simulation/environment state | Efficient numerical resource-state representation |
| **PyTorch** | Neural models | Transformer and RL model implementation |
| **Stable-Baselines3** | PPO implementation | Faster and more reliable RL experimentation |
| **Transformer** | Demand forecasting | Learns temporal workload patterns |
| **PPO** | Resource-allocation policy | Learns sequential actions from reward |
| **Gymnasium** | RL environment interface | Standardizes states, actions and episode interaction |
| **K3s/Kubernetes** | Execution environment | Lets the learned policy interact with containerized workloads |
| **Prometheus** | Observability | Supplies real-time infrastructure/application telemetry |
| **LangGraph** | Agent workflow | Controls conditional reasoning/tool use |
| **LLM** | Contextual decision reasoning | Handles policy/context/cost/SLA reasoning on high-impact events |
| **Vector database / RAG** | Operational memory | Retrieves relevant policies, playbooks and historical context |
| **Deterministic guardrails** | Safety | Prevents the LLM from violating hard infrastructure constraints |

The stack is intentionally modular: each technology has one clearly defined responsibility.

---

# 15. Real-World Benefits

If the architecture works as intended, the potential benefits are:

### Lower infrastructure waste

Resources can be provisioned closer to actual demand rather than permanently over-provisioning for worst-case load.

### Better peak handling

Forecasting can create capacity before resource pressure becomes severe.

### Lower operational cost

RL can explicitly include infrastructure cost in its objective.

### Better SLA/SLO protection

The system can prefer actions that reduce the probability of expensive service degradation.

### Fewer unnecessary LLM calls

The LLM is only used for high-impact decisions rather than routine scheduling.

### Better explainability of major decisions

A high-impact decision can produce a structured record such as:

```text
Forecast → Peak likely
RL → Scale by 2
Agent → Approved
Reason → SLA risk > expected scaling cost
Outcome → Peak handled
Reward → ...
```

### Adaptation to changing workloads

The architecture can observe when historical patterns stop matching current behavior and use the resulting telemetry/forecasting signals to adjust decisions.

These benefits should be treated as **research hypotheses to test**, not guaranteed outcomes.

---

# 16. Research Questions

AegisCloud can be evaluated around several concrete research questions:

### RQ1 — Forecasting

Can historical workload information predict near-future resource demand and peak events accurately enough to enable proactive provisioning?

### RQ2 — Scheduling

Does PPO improve resource allocation compared with baseline heuristics such as FCFS, SJF, or packing-based approaches?

### RQ3 — Cost-performance trade-off

Can the RL reward balance service quality against infrastructure cost and unused resources?

### RQ4 — Agentic decision making

Does a conditional agentic gate improve high-impact scaling decisions compared with using the RL action directly?

### RQ5 — Efficiency of agentic reasoning

Can conditional invocation achieve comparable or better decision quality with substantially fewer LLM calls than an always-on LLM architecture?

---

# 17. Evaluation Metrics

The project should use cloud/scheduling-native metrics rather than text-generation metrics.

### Forecasting

```text
MAE
RMSE
MAPE / sMAPE
Peak detection precision/recall
Peak prediction lead time
```

### Resource allocation

```text
Average resource utilization
Allocation failures
Queueing delay
Job slowdown
Makespan
SLA/SLO violations
```

### Cost

```text
Total infrastructure cost
Cost per successfully processed workload
Cost of unnecessary capacity
```

### Waste

```text
Unused allocated CPU
Unused allocated memory
Over-provisioning ratio
Scaling churn
```

### Agentic layer

```text
LLM calls
Agent decision latency
Approved actions
Rejected actions
Modified actions
Decision accuracy
Cost impact
SLA impact
```

The supplied cloud-resource survey identifies response time, throughput, utilization, availability, cost efficiency, scalability, reliability, and energy efficiency as relevant evaluation dimensions for cloud-resource allocation systems. 

---

# 18. Baselines

The system should not only be compared with itself.

At minimum:

```text
FCFS
SJF
Packing heuristic
Reactive threshold autoscaling
Forecast-only scaling
PPO without forecasting
PPO + forecasting
PPO + forecasting + agentic gate
```

This creates an important ablation structure.

For example:

```text
                     Cost     SLA     Waste
Reactive             ...      ...     ...
Forecast only        ...      ...     ...
PPO                   ...      ...     ...
Forecast + PPO        ...      ...     ...
Forecast + PPO
+ Agentic Gate        ...      ...     ...
```

That lets the project answer not just:

> "Does AegisCloud work?"

but:

> **"Which component actually contributes to the improvement?"**

---

# 19. Development Roadmap

AegisCloud should be developed incrementally.

```text
PHASE 1 — RL FOUNDATION
────────────────────────
DeepRM-style environment
Synthetic workload
PPO scheduler
Baseline heuristics
Reward design


PHASE 2 — DEMAND FORECASTING
────────────────────────────
Historical workload generation
Transformer forecasting
Peak prediction
Forecast evaluation


PHASE 3 — INTEGRATION
──────────────────────
Forecast → PPO
Proactive scaling actions
Cost/SLA-aware reward


PHASE 4 — AGENTIC GATE
───────────────────────
Conditional invocation
Telemetry tools
Cost tools
Policy tools
Deterministic guardrails


PHASE 5 — KUBERNETES
─────────────────────
K3s
Prometheus
Container workloads
Scaling/scheduling integration


PHASE 6 — GENERALIZATION
─────────────────────────
Public workload traces
Workload drift
Stress testing
Ablation studies
```

The project should not attempt all six phases simultaneously.

---

# 20. What AegisCloud Is — and Is Not

### AegisCloud is:

- a research prototype for predictive cloud resource allocation,
- an RL-based resource management system,
- a forecasting + decision-making architecture,
- an experiment in conditional agentic cloud operations,
- a system designed to study cost/performance/resource-waste trade-offs.

### AegisCloud is not:

- a claim that an LLM should replace a Kubernetes scheduler,
- a claim that synthetic workloads represent any specific company,
- a claim that an LLM can safely control infrastructure without guardrails,
- a production-ready autoscaler,
- a replacement for Kubernetes itself.

---

# 21. Expected Research Contribution

The project combines established ideas rather than claiming that every component is new.

The foundations are supported by prior work:

```text
DeepRM
    ↓
RL for resource scheduling

Cloud ML research
    ↓
workload forecasting + proactive allocation

Agentic CloudOps
    ↓
LLM-based reasoning + tools + governance

AegisCloud
    ↓
forecast → RL → conditional agentic gate → cloud action
```

The intended contribution is therefore the **integration and evaluation of these components around a specific two-stage resource-management workflow**, especially the question of whether a selective agentic gate can improve high-impact decisions while avoiding the cost and latency of invoking an LLM for routine scheduling.

---

# 22. Final Vision

The long-term vision is a cloud resource manager that does not simply ask:

> **"Are resources overloaded right now?"**

Instead, it asks:

> **"What is likely to happen next, what action is optimal over time, and is that action actually worth taking given cost, service quality, recent evidence, and operational constraints?"**

That leads to the following control loop:

```text
             ┌───────────────────────┐
             │ Historical Workloads  │
             └───────────┬───────────┘
                         ↓
                  Future Demand
                     Forecast
                         ↓
                  RL Decision
                         ↓
              Conditional Agent
                         ↓
              Safety / Policy Gate
                         ↓
                    Kubernetes
                         ↓
                  Actual Outcome
                         ↓
                 Cost / SLA / Waste
                         ↓
                     Reward
                         ↓
                    RL learns
```

The objective is not maximum resource usage.

The objective is:

> **Use enough resources to serve the workload reliably, spend as little as practical, minimize unnecessary capacity, and make better decisions as the system gains experience.**

---

## References

This README is grounded primarily in the project's supplied research sources:

1. Mao et al., **Resource Management with Deep Reinforcement Learning (DeepRM)**.
2. Tirmazi et al., **Borg: the Next Generation**.
3. Bodra & Khairnar, **Machine learning-based cloud resource allocation algorithms: a comprehensive comparative review**.
4. Oladele & Idowu, **Agentic AI Frameworks for Autonomous Cloud Resource Management**.
5. Rajasekar & Santhi, **Pervasive Auto-Scaling Method for Improving the Quality of Resource Allocation in Cloud Platforms**.

The project should distinguish clearly between:
- what these papers establish,
- what AegisCloud implements,
- and what AegisCloud proposes as a new experimental integration.
