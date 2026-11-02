# AegisCloud Code Review, Testing and Deployment Plan

## 1. Initial Project Review

The project was reviewed for architecture, implementation quality, ML evaluation and practical reliability.

Initial assessment:
- Overall project: approximately 6.5/10.
- Architecture: 8/10.
- Evaluation practices: 9/10.
- Working system: 4/10.
- Evidence of practical value: 3/10.

These were qualitative portfolio assessments, not formal industry benchmarks.

The main problems identified were:
- Import error involving `notebook.predict`.
- Documentation not matching the actual repository.
- Scaling was simulated rather than real.
- Repeated CSV reads could affect live performance.
- Models existed for only 6 of 318 applications.

## 2. Six-Day Development Plan

| Day | Objective |
|---|---|
| 1 | Connect the model, dataset, LLM and agent; understand the code |
| 2 | Integrate Prometheus and Grafana |
| 3 | Connect live traffic and implement real scaling |
| 4 | Perform testing and compare scaling policies |
| 5 | Prepare Docker/Kubernetes deployment and secrets |
| 6 | Fresh deployment verification, demo video and final documentation |

The simulator comparison was identified as the most important evidence of whether the proposed agent adds value.

## 3. Agent Architecture

The LangGraph agent contains eight main nodes:

1. `store_prediction`
2. `trigger_check`
3. `script_creator`
4. `llm_unusual`
5. `llm_timer`
6. `auto_scale`
7. `apply_and_log`
8. `alert_human`

The system uses three operating modes:

- Unusual: triggered by unusual traffic or forecast conditions.
- Timer: periodically invokes the LLM.
- Auto: uses a normal rule-based scaling formula.

The LLM is not called every minute. Plain code handles most decisions, and a guardrail limits replica changes.

## 4. Initial Testing Results

The following tests were completed:

| Test | Result |
|---|---|
| Fake LLM | Passed |
| Gemini LLM | Passed |
| Graph with fake LLM | 28/28 |
| Graph with Gemini | 29/29 |
| Graph with Gemini and email | 30/30 |
| 120-minute fake-agent run | Completed |
| 54-minute Gemini run | Completed |

Gmail SMTP integration was successfully configured using a Gmail app password. The alert email arrived with two CSV attachments.

The tests demonstrated that the model, dataset, LLM, graph and email components could work together.

## 5. Observed Problems

The real Gemini run exposed several decision-quality problems:

**False escalation:** Gemini requested human intervention even when the current replica capacity was sufficient.

**Incorrect explanations:** Some LLM-generated reasons contained incorrect arithmetic or unnecessary calculation text.

**Scaling instability:** Gemini scaled up, but the automatic scaler reduced replicas again in the next minute.

These issues showed that successful execution does not automatically mean good autoscaling decisions.

## 6. Recorded Experimental Results

A 120-minute fake LLM replay completed with:
- Zero alerts.
- Zero minutes above capacity.
- Replicas between 6 and 8.

A 54-minute Gemini replay showed:
- 17 LLM calls.
- No LLM execution errors.
- One false alert.
- Five replica changes versus three in the comparable fake-agent run.

The saved 134-minute Gemini run also showed that the LLM added limited value on the relatively smooth app_62.

## 7. Required Fixes and Improvements

The review proposed:
- Declare `llm_failures` in LangGraph state.
- Restrict false LLM escalations.
- Prevent immediate scale-down after scaling up.
- Improve LLM-generated explanations.
- Add formula-versus-LLM decision logging.
- Improve unit and integration tests.
- Test Mistral.
- Replace repeated CSV reads with in-memory recent data.
- Add GitHub Actions CI.
- Test on burstier applications such as app_185.

## 8. Remaining Development Work

The major planned additions were:

- Prometheus metrics and Grafana dashboards.
- Live traffic integration.
- Actual Docker/Kubernetes replica scaling.
- Replica startup delay simulation.
- Comparison against threshold and target-tracking policies.
- Cost and missed-SLO evaluation.
- Reproducible deployment and final documentation.

The conversation distinguishes between a working student portfolio system and a production-ready autoscaler. Real infrastructure scaling, broader evaluation and reliability testing remain essential before making production-level claims.
