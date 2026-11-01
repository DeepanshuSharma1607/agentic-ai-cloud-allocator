# Cloud Allocator: Prometheus + Grafana + email monitoring

This is a drop-in monitoring patch for the existing project. Copy the files to the same relative paths in the project root. It does not change the LSTM, LangGraph nodes, scaling policy, SMTP sender, or model checkpoints.

## What is measured

- **Replay/agent metrics:** observed traffic from the selected dataset app, LSTM forecast, simulated replica counts/capacity, utilization, policy changes, LangGraph duration, decision calls/failures and agent alert/email outcomes.
- **Live machine metrics:** CPU and RAM of the Python agent process, total CPU and RAM of the machine running Python, thread count and agent uptime.
- **Important limitation:** the current allocator replays a historical workload. Replica counts are simulated. Host CPU/RAM are real measurements of the machine running the agent; they are not CPU/RAM of actual cloud replicas. Monitoring does not provision Docker/Kubernetes workloads.

## 1. Copy/replace these paths

Replace `agent/run.py` and `agent/metrics.py` with the versions in this patch. Copy/replace the monitoring files and `docker-compose.monitoring.yml`. Keep the rest of your existing project, `.env`, datasets, checkpoints and output files.

## 2. Install dependencies

From the project root (the directory containing `requirements.txt`), with the same virtual environment you use for the project activated:

```powershell
pip install -r monitoring-requirements.txt
```

`monitoring-requirements.txt` includes your existing requirements plus `prometheus-client` and `psutil`.

## 3. Start Prometheus and Grafana

Make sure Docker Desktop is running:

```powershell
docker compose -f docker-compose.monitoring.yml up -d
```

Check container status and logs:

```powershell
docker compose -f docker-compose.monitoring.yml ps
docker compose -f docker-compose.monitoring.yml logs --tail 100 prometheus grafana
```

Open:

- Prometheus: http://localhost:9090
- Targets: http://localhost:9090/targets
- Grafana: http://localhost:3000

Initial Grafana username is `admin`; the Compose fallback password is `change-this-password`. Prefer creating a root-level `.env` file beside `docker-compose.monitoring.yml` containing `GRAFANA_ADMIN_PASSWORD=your_strong_local_password` before startup. This root `.env` is for Docker Compose; keep your Gemini/email secrets in `agent/.env`. Do not expose these ports to the public internet.

## 4. Test the complete pipeline without paid LLM calls

Start a 30-minute replay. `--tick 1` lets Prometheus scrape changing values. `--serve-after-replay` keeps the Python exporter alive after replay completes so Prometheus does not mark it DOWN immediately.

```powershell
python agent/run.py --minutes 30 --provider fake --tick 1 --app app_185 --serve-after-replay
```

In another browser tab, verify:

1. `http://localhost:8000/metrics` displays text metrics.
2. `http://localhost:9090/targets` shows `cloud-allocator` as **UP**.
3. In Grafana, open **Dashboards → Cloud Allocator → Agentic Cloud Allocator Overview**.

The first charts should fill during the replay. The process/host CPU and RAM panels continue to update while `--serve-after-replay` keeps the exporter alive.

## 5. Test the existing agent email path

The agent sends emails through the existing `agent/mailer.py` and settings in `agent/.env`. Make sure `agent/.env` contains these values (do not commit this file):

```dotenv
EMAIL_SENDER=your_gmail_address@gmail.com
EMAIL_PASSWORD=your_16_character_gmail_app_password
EMAIL_TO=the_recipient_address@example.com
```

For Gmail, use an App Password, not the regular account password. The `--email` flag enables sending. `--test-alert` forces exactly one test alert on the first replay minute and passes it through the **existing LangGraph alert node**. The test uses the `fake` provider's plain-code email template, so it does not need a Gemini API call, but it does send a real email if email credentials work.

First verify `EMAIL_TO` is an address you control. Then run this (it sends one real email):

```powershell
python agent/run.py --minutes 3 --provider fake --tick 1 --app app_185 --email --test-alert --serve-after-replay
```

Expected: the console prints `TEST ALERT enabled`, then an `ALERT` line and a status like `sent to ...`. The email is also written under `agent/data/alerts/`. The Grafana panels for **Agent emails sent**, **Email delivery failures**, and **Alerts saved without email** reflect the outcome.

If you do not want to send a real email yet, omit `--email`; the alert is saved to a file and the `Alerts saved without email` panel increases.

## 6. Use the real Gemini/Mistral agent

Once the fake-provider pipeline works and the email test succeeds, use your configured provider/API key:

```powershell
python agent/run.py --minutes 100 --provider gemini --email --tick 1 --app app_185 --serve-after-replay
```

`--test-alert` is not included here; real alert rules decide when emails are sent. You can add `--test-alert` only when intentionally sending a test message.

## Troubleshooting

- **Prometheus target DOWN:** make sure Python is running, the exporter says it is listening on port 8000, and Windows Firewall allows local Docker Desktop traffic to `python.exe`. Check `http://localhost:8000/metrics` from Windows first.
- **Port 8000 already used:** start the agent with `--metrics-port 8001` and change the Prometheus target to `host.docker.internal:8001`.
- **No traffic/forecast graph points:** use `--tick 1` (not `--tick 0`) and wait for at least one scrape after the first replay iteration.
- **Dashboard empty:** confirm the target is UP and use the last 15 minutes time range. Ensure the app dropdown matches the `--app` you used.
- **No email received:** read the console's `alert_status`, inspect `agent/data/alerts/alert_<minute>.txt`, and check the sender, recipient and Gmail App Password. Do not paste secrets into chat or commit `.env`.
- **Replay finishes and target goes DOWN:** include `--serve-after-replay`; press Ctrl+C to stop the exporter when done.
- **Old monitoring containers/config:** after changing Prometheus/Grafana configuration, run `docker compose -f docker-compose.monitoring.yml up -d --force-recreate`.

## Useful PromQL checks

```promql
cloud_allocator_replicas{app="app_185"}
cloud_allocator_traffic_requests_per_minute{app="app_185"}
cloud_allocator_forecast_requests_per_minute{app="app_185"}
cloud_allocator_agent_process_cpu_percent{app="app_185"}
cloud_allocator_agent_process_memory_bytes{app="app_185"}
increase(cloud_allocator_emails_sent_total{app="app_185"}[1h])
increase(cloud_allocator_email_failures_total{app="app_185"}[1h])
```
