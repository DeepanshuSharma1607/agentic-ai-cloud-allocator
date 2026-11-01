# Prometheus + Grafana monitoring

This adds metrics to the existing historical replay in `agent/run.py`. It does not change the autoscaling policy or make it scale a real Docker/Kubernetes service. The exporter exposes simulated replay values plus LangGraph execution timing.

## 1. Install the Python dependency

From the project root, in the same virtual environment you use for the allocator:

```powershell
pip install -r requirements.txt
```

The new dependency is `prometheus-client`.

## 2. Start Prometheus and Grafana

Make sure Docker Desktop is running. From the project root:

```powershell
docker compose -f docker-compose.monitoring.yml up -d
```

The compose file starts Prometheus on `http://localhost:9090` and Grafana on `http://localhost:3000`. Prometheus is configured to scrape `host.docker.internal:8000`, where the Python process exposes `/metrics`. The Grafana Prometheus data source and dashboard are provisioned automatically.

First-time Grafana login: `admin` / `admin`. Change the password in Grafana before exposing the service beyond your own machine. Keep the monitoring ports local/private; do not publish this setup directly to the public internet.

## 3. Run the allocator with metrics enabled

Open a second PowerShell window, activate the same virtual environment and move to the project root:

```powershell
python agent/run.py --minutes 100 --provider fake --tick 1 --app app_185
```

`--tick 1` means one second between replay minutes, allowing a time-series scrape to see changing values. Do not use `--tick 0` for a live dashboard: the replay runs and exits too quickly for Prometheus to collect the intermediate states. Use `--provider gemini` only when you specifically need the real provider and have configured its API key; fake mode is enough to test monitoring without API costs or rate limits.

Open `http://localhost:8000/metrics` to verify the raw metrics endpoint. The output should include metrics such as `cloud_allocator_replicas`, `cloud_allocator_traffic_requests_per_minute`, and counters ending in `_total`.

## 4. Check Prometheus and Grafana

1. Open `http://localhost:9090/targets` and verify the `cloud-allocator` target is **UP**.
2. Open `http://localhost:3000`, sign in, then open **Dashboards → Cloud Allocator → Agentic Cloud Allocator Overview**.
3. The dashboard's **App** dropdown filters by the `--app` used for the current run. While a replay is running, panels should show changing traffic, forecast, replicas, utilization, scaling actions, LLM attempts, alerts and LLM failures.

The time series stored by Prometheus stays available after a replay exits, but the target will become `DOWN` and its final metric values will stop updating until another run starts. Metrics counters reset when the Python process restarts; historical samples are still retained in Prometheus.

## 5. Useful PromQL queries

Paste these into Prometheus at `http://localhost:9090/graph` or Grafana Explore:

```promql
# Is the Python metrics endpoint reachable?
up{job="cloud-allocator"}

# Current simulated replicas
cloud_allocator_replicas{app="app_185"}

# Actual trace traffic and the model's forward forecast
cloud_allocator_traffic_requests_per_minute{app="app_185"}
cloud_allocator_forecast_requests_per_minute{app="app_185"}

# Traffic / capacity after the simulated decision; 1.0 means 100%
cloud_allocator_traffic_utilization_ratio{app="app_185"}

# Scaling changes in the last 15 minutes
increase(cloud_allocator_replica_changes_total{app="app_185"}[15m])

# Alerts in the last hour
increase(cloud_allocator_alerts_total{app="app_185"}[1h])

# LLM failures in the last hour
increase(cloud_allocator_llm_failures_total{app="app_185"}[1h])

# Average graph execution duration over the last 5 minutes
rate(cloud_allocator_graph_invocation_duration_seconds_sum{app="app_185"}[5m])
/
clamp_min(rate(cloud_allocator_graph_invocation_duration_seconds_count{app="app_185"}[5m]), 1e-9)
```

## Metric semantics / limitations

- `cloud_allocator_replicas` is the **simulated** replica count after the decision, not a count queried from a real orchestrator.
- `cloud_allocator_minutes_over_capacity_total` counts trace minutes where traffic exceeded the capacity represented by the replica count **before** the scaling decision. The existing replay assumes replicas start instantly, so it is not an end-to-end SLO measurement.
- Traffic is requests/minute from the supplied historical dataset, not live HTTP request volume.
- This currently does not export real container CPU or memory, because the replay does not deploy a workload. Add a Docker/Kubernetes metrics source later if you want real infrastructure measurements.
- The exporter binds to `0.0.0.0` so Docker Desktop can scrape it through `host.docker.internal`; avoid opening port 8000 to untrusted networks.

## Stop the monitoring stack

```powershell
docker compose -f docker-compose.monitoring.yml down
```

Prometheus and Grafana data are kept in named Docker volumes. To delete those stored data volumes too, use `docker compose -f docker-compose.monitoring.yml down -v` (this permanently deletes the saved metrics and Grafana state).
