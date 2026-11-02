# AegisCloud Project Context and Research Handoff — Summary 24

**Source:** `AegisCloud Project Context and Handoff Brief (1).md`  
**Source date:** 19 October 2026  
**Record type:** Project context, architecture decisions, research plan and handoff brief

## 1. Purpose and project direction

The brief was written to let a future assistant or collaborator continue AegisCloud without rereading the original discussion. At the time it was written, the user was an undergraduate computer science student with basic Python and Docker knowledge and limited cloud/Kubernetes experience. The requested working style was simple, direct English, real-world analogies, honest feedback and explanations of cloud terms from first principles.

AegisCloud's direction was narrowed from a broad idea involving an LSTM, an agentic LLM and Kubernetes into a **customer-side agentic autoscaler for containerized applications**. The intended user is an application owner, not a cloud provider. The first implementation was to be a simulator evaluated on a traffic trace.

The brief explicitly records that the earlier project used a fake dataset and that reinforcement learning was considered too risky and difficult to justify for the available scope. It also notes that a forecaster alone is not novel because AWS EC2 Auto Scaling already provides target-tracking and predictive-scaling capabilities. The proposed differentiating contribution is therefore the agent governance layer: explaining unusual traffic, controlling scaling risk and escalating uncertain situations to a human.

## 2. Final decisions recorded

| Decision | Recorded status | Rationale |
|---|---|---|
| Reinforcement learning | Dropped; optional final ablation only | Training risk, reward-design burden and no clear expected benefit |
| Dataset | Use real data only | The earlier dataset was fake |
| Forecaster | Start with a simple model; LSTM optional | Retain LSTM only if it clearly outperforms simpler alternatives |
| Product direction | Customer-side autoscaler for containerized apps | Matches the intended use by application owners |
| LLM invocation | Rare, never per request | Control token cost and reliability risk |
| Continuous scaling | Plain-code fast path | Normal operation must continue when the LLM is not invoked |
| Action safety | Code-based guardrail between LLM and actions | A system prompt alone is not a safety mechanism |
| Agent permissions | No autonomous code editing | Too risky; pull-request-only editing was mentioned as a possible much-later option |
| Development order | Simulator and evaluation first | Results must precede agent complexity |
| Provider-side VM overcommit | Parked | Possible alternative direction, not the selected project |

## 3. Research findings and unresolved verification

### Findings described as checked in the brief

- Provider-side prediction-guided VM overcommit was described as established research, with Azure Resource Central and Coach cited as examples.
- The brief identifies memory contention and noisy-neighbor effects on tail latency as difficult provider-side constraints outside the project's manageable scope.
- The Azure Public Dataset was identified as containing sanitized real-workload subsets from one region. The brief describes the V1 VM trace as CPU observations per five-minute window and an Azure Functions trace as invocation counts per minute.
- AWS EC2 Auto Scaling was described as already supporting target tracking and predictive scaling, with predictive scaling forecasting roughly two days ahead and requiring sufficient history.

### Checks explicitly left unverified

- Exact Azure trace column names and file layout, and whether the Functions trace is suitable for request-rate simulation.
- Whether newer trace versions include memory data.
- Claims about Datadog and Dynatrace AI capabilities mentioned in the earlier discussion.
- Whether the Microsoft Cloud Monitoring Dataset and other named datasets are suitable for this project.

These are recorded as statements and open checks from the source brief, not as newly revalidated facts.

## 4. Problem statement and hypotheses

**Problem:** Conventional autoscaling follows comparatively simple rules. It may not distinguish a sale from an attack, can scale excessively in response to a bug and increase costs, and often does not explain its decisions or request human assistance.

**Proposed approach:** A forecaster and deterministic autoscaler handle routine work. An LLM governor is invoked only on defined triggers; it may adjust a bounded safety setting, explain a situation and escalate when uncertain.

Two claims were proposed for evaluation:

- **Claim A:** Forecast-based scaling uses fewer replicas than a threshold policy while achieving the same or lower SLO-miss time.
- **Claim B:** Under changing conditions, an agent that adjusts headroom and escalates can keep SLO misses within a budget, compared with a simple rule-based controller.

The brief requires an honest result if the agent only matches the controller rather than outperforming it.

## 5. Architecture and decision flow

The proposed pipeline is:

```text
Application request counts (per minute)
    -> Prometheus
    -> Forecaster (next 10–60 minutes)
    -> Deterministic autoscaler (replica count)
         -> short JSON summary on trigger
         -> LLM governor
         -> code-based guardrail
         -> apply an allowed setting or notify a human
    -> SQLite audit log, dashboard and evaluation
```

The replica calculation is:

```text
replicas_needed = predicted_traffic / (capacity_per_replica * target_utilization)
```

The brief's example uses capacity of 100 requests/second per replica, target utilization of 60%, and forecast traffic of 600 requests/second, yielding 10 replicas.

**Headroom** is represented by the target-utilization setting. A lower target leaves more spare capacity and is safer but more expensive; a higher target is cheaper but riskier.

| Component | Responsibility | LLM use |
|---|---|---|
| Forecaster | Predict future traffic | No; simple model first |
| Autoscaler | Convert predicted demand into replica count | No |
| LLM governor | Adjust headroom, explain spikes, prevent runaway scaling and escalate | Rarely |
| Guardrail | Validate every proposed decision against fixed rules | No |
| Audit log | Record decisions, reasons and before/after metrics | No |

The LLM was to be triggered by sustained capacity shortfall, a sudden increase in forecast error, or a routine six-hour check. It receives a compact JSON summary, not raw logs.

### Allowed actions and safety boundary

The proposed action allowlist permits the governor to:

- Change target utilization only within defined bounds and in small increments.
- Cap replicas to a budget.
- Switch to a safe static policy.
- Message an engineer with options and a recommendation.

It must not execute terminal commands, delete resources or modify application code. The deterministic guardrail must sit between the LLM output and any action.

## 6. Agent acceptance scenarios

Five scenarios were defined as both test cases and agent acceptance tests:

1. **Routine drift:** capacity shortfalls gradually increase; the agent raises headroom slightly.
2. **Flash sale:** scale within a budget and explain the decision.
3. **Attack-like burst:** avoid blindly scaling and escalate to a human.
4. **Memory-leak crash loop:** prevent runaway scaling and report the pattern.
5. **Forecast failure:** fall back to a safe static policy and ask the human.

## 7. Data and evaluation methodology

- **Initial data candidate:** a slice of Azure Functions invocation counts per minute, subject to checking the actual columns and suitability.
- **Temporal split:** first 70% for training and final 30% for testing; do not evaluate on training data.
- **Simulator:** Python-based, one-minute steps, replaying the selected trace.
- **Startup delay:** include approximately two minutes for a replica to become ready; otherwise reactive policies may be given an unrealistic advantage.
- **Policies to compare:**
  1. Threshold policy: CPU above 70% adds a replica.
  2. Target-tracking-style policy.
  3. Forecast plus scheduled scaling.
  4. Forecast plus agent.
  5. A simple rule-based controller as the direct comparison for the agent's incremental value.
- **Metrics:** replica-minutes (cost), minutes where capacity is below demand (SLO miss), scaling flaps, number of agent actions and number of LLM calls.
- **Reporting:** evaluate across several trace slices rather than presenting a single aggregate result.

The brief warns that replaying historical traffic does not allow scaling decisions to change user behavior; this limitation should be stated in the README.

## 8. Proposed technology stack and repository layout

**Initial stack:** Python 3.11, pandas, NumPy, scikit-learn, Matplotlib, Streamlit and pytest.

**Agent stage:** LangGraph, Pydantic action schemas, SQLite or JSONL audit logging, and an LLM that supports structured JSON output.

**Optional later additions:** PyTorch only if an LSTM demonstrates a benefit; Docker; K3s or kind; Prometheus; and k6 or Locust for load generation.

The brief says Kubernetes, Prometheus and Loki were not needed at the initial stage.

Suggested repository layout:

```text
aegiscloud/
  README.md
  data/            download script only
  src/             loader, forecaster, simulator, policies, controller, metrics
  src/agent/       governor, actions (allowlist), guardrail
  experiments/     one script per experiment
  app/             Streamlit app
  tests/           simulator tests and five scenarios
  results/         plots and tables
```

## 9. Original phase plan

### Phase 1 — working model without an agent (19–25 October 2026)

| Date | Planned task |
|---|---|
| Mon 19 Oct | Download a trace slice, explore it with pandas, write the loader and establish the chronological split |
| Tue 20 Oct | Build simulator with startup delay, SLO-miss and cost metrics; implement policies 1 and 2 |
| Wed 21 Oct | Build forecaster v1 and policy 3 |
| Thu 22 Oct | Produce results table and cost-versus-miss chart |
| Fri 23 Oct | Build Streamlit demo with headroom slider and initial README |
| Sat 24 Oct | Buffer, fixes and simulator/metric tests |
| Sun 25 Oct | Demo video and GitHub push |

### Phase 2 — agent (approximately two weeks afterward)

Build the rule-based controller first, then the LangGraph governor, code guardrail and audit log. Implement the five scenarios and compare the agent with the rule-based controller.

### Phase 3 — optional extension

Improve the forecaster only if it wins; add a small K3s live demo with Prometheus and k6; prepare a short write-up.

## 10. Risks, limitations and honest assessment

The source brief's assessment at the time was:

| Area | Score in the brief |
|---|---:|
| Brainstorming quality | 6/10 |
| Research depth | 4.5/10; mostly snippets, with no papers read deeply |
| Plan quality | 6.5/10; nothing built or tested yet |
| Novelty at industry scale | 2.5/10 |
| Student portfolio value | 7/10 with honest evaluation; 4/10 if only a demo |
| Product value | 1/10 |

Main risks identified:

- The extra value of the agent is difficult to measure; it may only match a simple controller while adding explanations and escalation.
- The user was still learning cloud infrastructure; inability to explain each module would reduce the project's portfolio value.
- The six-day initial deadline was tight, so scope should be cut before evaluation quality.
- Historical replay does not model feedback from scaling decisions to user behavior.

## 11. Open items and next task at the time of writing

The earlier document **AegisCloud: First Showable Project Blueprint** described the provider-side design and was considered outdated for the product direction. Its simulator, chronological-split and evaluation structure were still considered reusable.

Open checks:

- Inspect the Azure trace's real columns and file layout.
- Confirm whether the Azure Functions trace suits the intended request-rate simulation.
- Establish a defensible per-replica capacity assumption for the simulator.

**Immediate next task (Phase 1, Day 1):** create `loader.py` to download a slice of the chosen trace, load it with pandas, print its columns and dimensions, convert it to requests per minute, and split it chronologically 70/30. Summarize the dataset before building the simulator or forecaster.

## 12. Status boundary

This source is a planning and handoff brief dated **19 October 2026**. It explicitly says that nothing had yet been built or tested at that point. Its architecture, policies, tests and phase plan should therefore be treated as proposed decisions and planned work as of that date—not evidence that those components were implemented or experimentally validated.
