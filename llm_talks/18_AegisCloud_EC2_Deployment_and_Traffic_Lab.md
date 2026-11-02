# AegisCloud EC2 Deployment and Traffic Lab Development

**Source conversation:** `Create EC2 Instance`  
**Conversation dates:** 26–27 October 2026  
**Scope:** EC2 setup, project transfer and environment preparation, agent and monitoring validation, and creation/local testing of a separate controlled traffic-generation application.

## Objective

The conversation began with a step-by-step deployment of the AegisCloud project on AWS EC2. It then moved through Python environment setup, dataset recovery/automatic downloading, real Gemini agent testing, Prometheus/Grafana integration, and planning a controlled application workload for collecting new traffic data.

## 1. EC2 instance and secure access

The proposed instance configuration was:

- Name: `aegiscloud-server`.
- OS image: Ubuntu Server 24.04 LTS, 64-bit x86.
- Instance type recommendation: `t3.small` if eligible/covered by credits; otherwise check cost before choosing a paid type. The conversation also considered memory constraints, but the transcript does not conclusively establish the selected EC2 instance type.
- SSH key pair: RSA `.pem`, named `aegiscloud-key` in the initial setup instructions.
- Public IPv4 enabled; SSH inbound source restricted to **My IP**.
- Root storage recommendation: encrypted 20 GiB gp3.
- No Elastic IP or NAT Gateway was recommended during initial setup.

The instance was later accessed at public IPv4 `16.16.253.3`; its Ubuntu prompt showed private host address `ip-172-31-6-113`. An initial SSH failure came from using a malformed PowerShell environment-variable expression and then guessing a key filename that was not in Downloads. The user later found the correct key and confirmed connection. The private key was repeatedly treated as confidential.

## 2. Project transfer and server environment

Docker Engine and Docker Compose were installed from Docker's official Ubuntu package repository. The `hello-world` container test succeeded. The server reported about **1.9 GiB RAM** and a 19 GiB root filesystem; later checks showed approximately 15 GiB free disk, then 11 GiB free after additional project/dependency setup.

The complete project archive `Major_Project.zip` (reported size **311 MB**) was transferred from Windows Desktop to `/home/ubuntu/` and extracted under:

```text
~/aegiscloud/Major_Project
```

The extracted project contained, among other items, `README.md`, `requirements.txt`, `agent/`, `models/`, `notebook/`, `monitoring/`, `docker-compose.monitoring.yml`, and `monitoring-requirements.txt`.

A fresh Linux environment was created rather than reusing the environment copied in the archive:

- `uv 0.13.5`
- Managed Python `3.12.15`
- Environment: `.venv-ec2`

A root `.env` file was created with a random `GRAFANA_ADMIN_PASSWORD`; `agent/.env` was created or retained for Gemini/Mistral and email settings. The conversation later corrected the permissions with `chmod 600 .env agent/.env`. The user was told not to paste secret values into chat.

Project/monitoring dependencies were installed using `uv pip install --torch-backend cpu -r monitoring-requirements.txt`, to avoid GPU-oriented packages on the CPU-only EC2 instance. The user reported completing installation, but the transcript does not include a full successful output of the subsequent import-verification block.

## 3. Dataset and model availability

The user had deleted the dataset folder and initially considered manually uploading the CSV. Inspection of `notebook/predict.py` showed that the existing script could download the missing dataset when `gdown` was installed:

- Google Drive ID in source: `1KLtkWrC96XvBm9JVJKpzjrHHfix7wW1K`.
- Expected fallback path: `notebook/dataset.csv`.
- The loader used `gdown.download(...)` if the CSV was absent.

The proposed commands installed `gdown` into `.venv-ec2` and ran:

```bash
.venv-ec2/bin/python notebook/predict.py --app app_62 --backtest
```

The user confirmed that both the download and backtest worked. This was a backtest, not a training run.

## 4. Agent execution and Gemini validation

The initial smoke-test plan used the `fake` provider for a short five-minute replay, with metrics disabled, to test the agent workflow without API usage. The user then clarified that a real Gemini run had already succeeded, so the conversation shifted to validating the live provider and monitoring rather than repeating fake-provider tests.

The user supplied output from a **20-minute Gemini replay** for `app_62`:

- Provider: `gemini`.
- LLM review timer: every 5 replay minutes.
- Per-replica capacity: 223 requests/minute.
- Configured replica range: 1–21.
- Initial replica count: 6; one change from 6 to 7 occurred.
- LLM calls: **3**.
- Replica changes: **1**.
- Alerts: **0**.
- Replica-minutes: **131**.
- Minutes above capacity: **0**, under the explicit assumption that new replicas start instantly.

This demonstrated that the agent could load its model, make Gemini calls, produce forecasts, and update its **simulated** replica count. It did not demonstrate that Docker containers or Kubernetes Pods were actually being created or removed.

## 5. Prometheus and Grafana setup

The monitoring stack used `docker-compose.monitoring.yml` with:

- `prom/prometheus:latest`
- `grafana/grafana:latest`
- Persistent Prometheus and Grafana volumes.
- Prometheus metrics path `/metrics`.
- Prometheus target `host.docker.internal:8000`, with Docker `host-gateway` mapping.
- A 5-second scrape/evaluation interval after configuration was adjusted from the original 1-second interval.

The Compose file validated successfully. Both containers started and reported `Up`.

### Metrics connection debugging

Grafana initially opened but showed no data; Prometheus showed the agent target as `DOWN`. The troubleshooting established:

- The agent had been started with a finite replay and had exited, so nothing was listening on port 8000 after that run.
- No AWS inbound rule for port 8000 was needed for this host-to-container connection.
- A later agent process listened on `0.0.0.0:8000`.
- `curl` to `http://127.0.0.1:8000/metrics` returned HTTP **200**.
- Prometheus's target API then reported:
  - Job: `cloud-allocator`
  - Health: **`up`**
  - Scrape URL: `http://host.docker.internal:8000/metrics`
  - Last error: none.

Grafana's saved dashboard initially selected `app_185`, whereas the running agent used `app_62`; selecting the correct app was identified as necessary to populate the dashboard.

### Dashboard access

Initially both Grafana and Prometheus were bound to EC2 localhost and accessed through an SSH tunnel. The user wanted direct access by public IP. The configuration was changed so Grafana mapped to `0.0.0.0:3000`, while Prometheus remained bound to `127.0.0.1:9090`. An inbound AWS Security Group rule was added for custom TCP port **3000**, with source **My IP**. Ports 8000 and 9090 were kept private.

The user later shared a screenshot showing Grafana data through the EC2 public IP. The values reported from that screenshot were approximately:

- Current replicas: 7.
- Observed traffic: ~1,150/min.
- Forecast traffic: ~1,180/min.
- Post-decision utilization: 73.5%.

These were dashboard values at that moment, not aggregate experimental results. Direct Grafana access used plain HTTP, and the browser indicated “Not secure”; HTTPS was not configured in this conversation.

## 6. Long replay plan and change of direction

A 48-hour historical replay was initially proposed using `tmux`, with:

```bash
--minutes 2880 --tick 60 --timer 5 --app app_62 --provider gemini
```

The previous agent logs were backed up to a timestamped archive before a longer run. The plan was later accelerated to `--tick 15`, theoretically compressing 2,880 replay minutes into about 12 hours, with `--email` and `--serve-after-replay` discussed. `agent/run.py --help` confirmed support for `--minutes`, `--tick`, `--timer`, `--app`, `--provider`, `--email`, `--metrics-port`, `--no-metrics`, `--test-alert`, and `--serve-after-replay`.

The 12-hour run was then explicitly reconsidered. The conversation concluded that simply running for 48 simulated hours was not the most valuable next step: a prolonged replay would not prove real autoscaling. The recommendation changed to a short monitored test, comparative evaluation of scaling policies, and realistic startup-delay modeling. No completed 2,880-minute run is recorded in this conversation.

The user then proposed creating a small application, generating known variable traffic, and collecting new application measurements for roughly 10–15 hours. This became the new direction.

## 7. Separate AegisCloud Traffic Lab package

A standalone Traffic Lab bundle was created for later EC2 use. It was designed to keep new workload-generation files separate from the existing AegisCloud core project and monitoring setup.

The described package included:

- `app.py`: lightweight HTTP application.
- `Dockerfile` and `compose.yaml`: containerized app deployment.
- `nginx.conf`: reverse proxy intended to route traffic across app containers.
- `traffic_generator.py`: configurable workload generator.
- CSV data collection and `convert_to_1min.py`.
- Prometheus metrics and a separate Grafana dashboard.
- EC2 installation and collection scripts, including `install_ec2.sh`, `start_collection.sh`, and `status.sh`.

The default ten-minute workload profile was described as:

| Phase | Duration |
|---|---:|
| Low traffic | 2 min |
| Normal traffic | 4 min |
| High traffic | 2 min |
| Peak traffic | 1 min |
| Cooldown | 1 min |

Default generator settings included a maximum of 12 requests/second and 2 ms of bounded work per request. The design separated planned/target traffic from observed requests and retained success/failure, latency, replica identity, and resource measurements. Ports 8100 and 8101 were intended for local/internal use; no AWS Security Group inbound rules for those ports were recommended.

### Data output formats

The package evolved to provide three distinct CSV representations:

1. Raw five-second observations with detailed traffic, response, latency, and resource fields.
2. Detailed actual-wall-clock one-minute aggregates.
3. An Azure-style accelerated sequence containing `minute` and `app_traffic_lab`, where **each five-second record becomes one sequential simulated-minute row** and its request count is preserved rather than summed.

The accelerated mapping is explicitly a simulated time index, not a real one-minute measurement. The original raw file was to be retained.

## 8. Local Windows smoke test and converter issue

The user chose to test the Traffic Lab locally before deploying it to EC2.

Observed local test evidence:

- Docker built `aegiscloud-traffic-app:local`.
- `traffic_lab-traffic-app-1` was healthy and `traffic_lab-traffic-proxy-1` was running.
- `curl.exe http://localhost:8100/health` returned `{"status":"ok", ... "replica_id": ...}`.
- A short traffic run produced **15 five-second CSV rows**, with **85 successful requests and 0 failed requests**.
- The displayed generator output showed the low phase and zero CPU/memory values on Windows. The conversation explained that the system-metric collector depended on Linux `/proc` data, so those resource readings might be zero on native Windows.

The first attempts to run `convert_to_1min.py` finished without output and created no converted files. The diagnosis was that the local converter file was stale/incomplete or did not contain the expected executable entry point. A replacement `convert_to_1min_accelerated.py` was provided, with instructions to replace the existing file and rerun the conversion. The transcript ends before a successful post-replacement conversion is confirmed.

## Decisions, limitations, and pending work

**Completed or verified**
- EC2 Docker installation and test container.
- Project archive upload and extraction.
- `uv`/Python 3.12 environment creation.
- Automatic dataset download and `app_62` backtest.
- Real Gemini replay with logged decisions.
- Prometheus target reached `UP`; Grafana displayed metrics.
- Traffic Lab container/app and short local traffic-generation smoke test.

**Important limitations**
- `set_replicas()` was identified in the project as a placeholder; the existing agent's replica count remained simulated.
- Zero capacity violations in the 20-minute test assumed instant replica startup.
- Direct Grafana access was HTTP, not HTTPS.
- The 48-hour/12-hour replay was discussed but not completed in the transcript.
- Local Windows CPU/memory collection returned zero in the sample run.
- The converter's corrected output was not verified after replacement.

**Pending work**
- Complete and inspect the converter outputs from the local smoke-test CSV.
- Exercise the full low/normal/high/peak/cooldown cycle, not only the brief low-phase smoke test.
- Deploy the standalone Traffic Lab to EC2 and validate its scrape targets.
- Run the planned 10–15-hour variable-traffic collection only after the full logging/monitoring pipeline is verified.
- Convert raw records while retaining both actual-time detail and accelerated Azure-style indexing.
- Implement and test an adapter from AegisCloud decisions to actual Docker replica operations before claiming real autoscaling.
- Account for shared CPU/memory when multiple containers run on one EC2 instance.
