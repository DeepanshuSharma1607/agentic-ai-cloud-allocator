# Project Rating and Prometheus/Grafana Integration

## 1. Unbiased Project Assessment

The repository review rated the project **6.0/10 overall** as an ambitious intermediate prototype. The scores were engineering judgments, not official certification grades.

| Area | Rating |
|---|---:|
| Problem definition and architecture | 7.5/10 |
| ML methodology | 6/10 |
| Reported ML results | 5.5/10 |
| Agent architecture | 7/10 |
| Code quality and maintainability | 5.5/10 |
| Testing and reliability | 5/10 |
| Reproducibility | 5/10 |
| Documentation | 7/10 |
| Research novelty/evidence | 4.5/10 |
| Deployment/production readiness | 2/10 |
| Portfolio/interview value | 6.5/10 |

Strengths included the forecasting experiments and baselines, chronological split, modular LangGraph workflow, guardrails, fallback behaviour, logging and relatively candid documentation.

## 2. Main Weaknesses Identified

- `set_replicas()` was a no-op: the agent updated simulated state but did not scale Docker or Kubernetes workloads.
- There was no completed closed-loop simulator with startup delay, queues and realistic overload consequences.
- There was no convincing policy comparison showing cost or SLO improvement.
- The LSTM's overall advantage over simpler forecasting methods was small, and one difficult application (`app_185`) had WAPE around 98.4%.
- The notebook selected a model using test-set WAPE, compromising the independence of the test set; model selection should use validation data.
- Gemini runs showed false alerts, inaccurate explanations and conflicting scale-up/scale-down actions.
- The review also flagged `llm_failures` missing from `AgentState`, weak behavioural assertions, a documented-but-unimplemented SMTP STARTTLS fallback, a misleading overload summary, stale documentation and a test artifact containing an email address that should be redacted.

A separate notebook table in the same review conversation reported LSTM WAPE 0.158, moving average 0.167, GBM 0.172 and naive 0.184. The review also cited aggregate results of 0.189 for LSTM and 0.191 for GBM. These are reported figures from different referenced summaries/runs and should not be treated as one reconciled experiment.

The recommendation was to describe the project as a **replay-based predictive autoscaling prototype**, not a functioning autonomous cloud allocator.

## 3. Recommended Improvements

The highest-priority work was:
1. Build a simulator with replica start-up delay, capacity, queues and overload/SLO behaviour.
2. Compare static, threshold/reactive, forecast-only and LLM-assisted policies using replica-minutes, SLO-miss minutes, scaling oscillations, LLM calls, latency and API cost.
3. Re-evaluate forecasting with validation-based model selection, multiple seeds or rolling splits, and per-application results.
4. Add behavioural tests for false alerts, oscillations and LLM failures.
5. Add a real Docker/Kubernetes adapter only after the simulated policy is validated.
6. Improve reproducibility, CI, documentation and redaction of personal data.

The research idea proposed was to measure **when an LLM governor pays off** compared with a deterministic formula, and whether forecast-accuracy rankings predict closed-loop scaling quality. The conversation said the work was not yet ready for a research paper because experimental evidence, baselines, statistics, a second trace and time-compression justification were missing. A 2.5-day technical report was considered possible only with a reduced scope; a more credible minimum benchmark was estimated at 6–8 weeks part-time.

## 4. First Prometheus/Grafana Integration

The first monitoring ZIP added seven files:
- `agent/metrics.py`
- `docker-compose.monitoring.yml`
- `monitoring/prometheus.yml`
- Grafana datasource and dashboard provisioning files
- `MONITORING.md`

Three files were modified: `agent/run.py`, `requirements.txt` (adding `prometheus-client`) and `README.md`.

It exposed replay-derived metrics for traffic, forecasts, replicas, capacity, scaling actions, LLM activity/failures, alerts and graph duration. This first version instrumented the historical replay; it did not create real replicas or measure deployed application CPU/RAM.

The user was advised to use a nonzero replay tick (for example `--tick 1`) because `--tick 0` completed too quickly for Prometheus to scrape intermediate states. Docker Compose started Prometheus and Grafana, while the Python agent/exporter had to run separately.

## 5. Corrected Monitoring Patch and User Verification

A later monitoring patch was prepared to add:
- Python process and host CPU/RAM metrics.
- Workflow, forecast, replica and alert metrics.
- Email success/failure/saved-only counters.
- A forced `--test-alert` path.
- An option to keep the exporter alive after replay (`--serve-after-replay`).
- Updated Prometheus/Grafana configuration and a dashboard described as having 21 panels.

The conversation reports that Python syntax, the local metrics endpoint, monitoring YAML and dashboard JSON were checked. Docker could not be run end-to-end in the assistant's environment.

On the user's Windows machine, Docker Compose successfully started Prometheus and Grafana. The Python exporter later became reachable at `localhost:8000/metrics`; Prometheus showed the `cloud-allocator` target; Grafana displayed populated panels. A clarification was made that `host.docker.internal` is for Docker-to-host access, while the Windows browser should use `localhost`.

The user then reported that the combined final checks “all worked.” The test procedure included compilation, graph tests with the fake provider, metrics endpoint, Prometheus query/target, Grafana health, and optional real Gemini and email prompts. The transcript does not explicitly record whether the optional live Gemini call and real email were selected and received, so those should remain unconfirmed unless their outputs are separately retained.

## 6. Meaning of Dashboard Values and Actual Scaling Status

The example screenshot showed 166 replicas, 9 requests/minute, a forecast of 2.45 requests/minute and calculated post-decision utilization of about 0.104%, using 52 requests/minute per simulated replica.

These were replay-derived and simulated values. They did not represent real containers or cloud instances. Prometheus and Grafana provided observability, not actuation.

The remaining live-scaling work was described as:
- Deploy a real stateless test application.
- Send real HTTP requests to it.
- Connect agent decisions to Docker/Kubernetes through an adapter.
- Read back actual desired, running and ready replicas.
- Collect real application/infrastructure metrics.
- Add safe limits, cooldowns, stabilization and failure handling.
- Benchmark against a threshold-based scaler.

## 7. Repository Hygiene and Documentation

A `.gitignore` was supplied for Python caches, virtual environments, `.env` secrets, datasets, generated data, model checkpoints, logs, notebook checkpoints, editor files, test outputs and local monitoring storage. The instructions noted that `.gitignore` does not untrack already committed secrets; exposed credentials should be rotated. Model checkpoints ignored by Git need a separate distribution method such as Git LFS or model releases.

A complete README replacement was prepared to cover project architecture, installation, dataset/model setup, agent commands, tests, Prometheus/Grafana setup, metrics, forecasting results, limitations and roadmap. It explicitly retained the caveat that replica scaling was not implemented and documented the `llm_failures` state issue as requiring attention.
