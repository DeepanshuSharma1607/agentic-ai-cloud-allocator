# Weekly Progress and Live-System Troubleshooting

## 1. Weekly Project Report

**Project title:** AegisCloud – Agentic AI-Based Predictive Cloud Resource Management  
**Reporting period:** 26 October–1 November 2026

The weekly report described the work as:
- Finalizing the end-to-end architecture.
- Integrating traffic generation, application monitoring and metric collection.
- Connecting LSTM forecasting with the LangGraph agent.
- Implementing unusual-event, timer-based and automatic decision paths with action logging.
- Developing the Streamlit dashboard and tests.

**Challenges recorded:** connecting the LSTM to live metrics, validating forecasts under changing traffic, and the fact that cloud resource provisioning was still simulated.

**Next-week plan:** validate the trained LSTM on live traffic, improve forecasts and thresholds, refine agent decisions and alerts, connect actual infrastructure scaling, and run end-to-end tests.

A shorter version of the report was also prepared with the same points.

## 2. Forecast Warm-up and Seed Data

The system uses:
- 1 tick = 5 seconds of real time.
- 1 tick = 1 simulated minute.
- A 60-row sequence window plus same-time-yesterday information.
- 1,441 consecutive rows before a forecast can be produced.

Without historical seed data, the system needs about 1,441 ticks (roughly two real hours) to warm up. The proposed shortcut is to place the historical file at `data/seed/metrics_combined.csv` and the trained checkpoint at `prediction/models/lstm_requests_forecaster.pt`.

The seed CSV needs a `minute` column and these eight metrics: `requests`, `p50_ms`, `p95_ms`, `p99_ms`, `achieved_rps`, `app_cpu_pct`, `host_cpu_pct`, and `app_mem_mb`. Minute values must be consecutive and ordered.

For a clean test, old live, prediction and agent runtime CSVs were to be archived or cleared, without deleting the training dataset or model. The recommendation was to use Daily Pattern traffic first, because it resembles the training data. `DAY = 1440` should not be reduced just to avoid warm-up; the checkpoint expects that daily feature construction.

The uploaded ZIP was reported to contain placeholder folders rather than the real checkpoint and seed CSV, so both assets had to be supplied separately. The real checkpoint had not yet been verified in the live implementation.

## 3. Startup and Agent Troubleshooting

Screenshots initially indicated:
- Target app: UP.
- Collector: UP.
- Prediction service: UP and producing forecasts, but with high error/drift.
- Request sender: DOWN.
- Agent: no visible logs.

The suggested standalone commands were to start the load generator on port 8002 and run the agent with the fake provider and a short timer. However, the subsequent `python run_all.py --provider gemini` output showed that the launcher had already started all six components: target app (8001), prediction (8004), collector (8003), load generator (8002), agent and dashboard (8501).

A later attempt to start Uvicorn separately on port 8002 failed with Windows error 10048 because the port was already occupied by the load generator started by `run_all.py`. The instruction was therefore not to start a second copy.

The next diagnostic step was to inspect `data/logs/agent.log`. The final visible log excerpt showed the history warming up from 764 to 776 rows out of 1,441. The conversation ended before this warm-up issue was resolved.

## 4. Current Evidence and Open Items

- The combined launcher reported all six components as started.
- The load-generator port conflict was explained as a duplicate-start attempt, not proof that the service was broken.
- The latest captured history was still below 1,441 rows.
- The agent's actual decision output and successful end-to-end operation were not established by the final log excerpt.
- The reason the seed history was not already complete was not confirmed in this conversation.
