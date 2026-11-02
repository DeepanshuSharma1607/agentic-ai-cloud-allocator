# Prometheus and Grafana Metrics Connection Fix

## 1. Problem

Grafana and Prometheus were reachable through the EC2 SSH tunnel, but Grafana displayed **No data** and Prometheus showed the `cloud-allocator` target as **DOWN**. The reported scrape failure was a connection refusal to the Python agent's metrics endpoint on port `8000`.

## 2. Agent Status

The user confirmed that the Gemini agent was already running on EC2:

```bash
.venv-ec2/bin/python -u agent/run.py \
  --minutes 10 --tick 60 --app app_62 --provider gemini
```

The output confirmed:
- Metrics endpoint announced at `http://localhost:8000/metrics`.
- App: `app_62`.
- Gemini provider enabled.
- Timer interval: 5 minutes.
- Capacity: 223 requests/minute per replica.
- Replica range: 1–21.
- Alert emails disabled; alerts were saved as files.
- The 10-minute replay was a connectivity trial, not the planned 48-hour run.

The agent's startup message did not prove that Prometheus could reach the endpoint. The proposed diagnosis therefore checked local HTTP response, listening interface, Docker host mapping and Prometheus target state separately.

## 3. Suspected Root Cause

The Prometheus target was attempting to connect to `192.168.65.254:8000`, an address associated with a Docker Desktop host mapping rather than the EC2 host. The target configuration also contained stale host references. The problem was likely container-to-host routing, not the browser tunnel or Grafana itself.

The uploaded `traffic_lab` ZIP did not include the main agent source or the complete Prometheus configuration, so the fix was designed around the observed endpoint and EC2 environment rather than a full source-code patch.

## 4. Repair Proposed

The corrective procedure was designed to:

1. Leave the running Gemini agent and SSH tunnel untouched.
2. Test `http://127.0.0.1:8000/metrics` locally and check for HTTP 200.
3. Inspect the port-8000 listener with `ss -lntp`.
4. Determine the EC2 private IP from the instance routing table.
5. Back up `monitoring/prometheus.yml`.
6. Replace stale `host.docker.internal` / `192.168.65.254` target references with the EC2 private IP while retaining the metrics port.
7. Validate the Prometheus configuration with `promtool`.
8. Restart only the Prometheus container, preserving its data volumes.
9. Query the Prometheus Targets API and check whether the port-8000 target becomes `UP`.

If the metrics server listens only on loopback, the Python server must be configured to bind to `0.0.0.0:8000`. For `prometheus_client`, the suggested form was `start_http_server(8000, addr="0.0.0.0")`.

## 5. Verification Status

The conversation provides a corrected, paste-ready repair script and the verification commands, but it does **not** show the result of running that script or confirm that the target ultimately became `UP`.

The final guidance was to preserve the active agent, back up configuration before editing, restart only Prometheus, and verify the target health before changing any other services.
