# AegisCloud - real replicas (final phase)

Until now the agent only wrote a replica number into a CSV. Now `set_replicas(n)` starts and stops **real containers** (or
Kubernetes Pods), each with a real CPU and memory limit. When a spike comes, the agent asks for more replicas, the replicas
really start (that takes real seconds), become Ready, and share the traffic.

Nothing in `agent/`, `prediction/`, `traffic/`, `settings.py` or `run_all.py` was changed. New code lives here, plus
`run_live.py`, and three small edits in `frontend/` (see the end).

```
loadgen --/work--> GATEWAY :8001 --> replica 1 (container, 0.5 core, 192 MB)
                      |         --> replica 2
collector --/snapshot-+         --> replica N      <- started / drained by the ClusterManager
                      ^
agent --set_replicas(n)--> POST /infra/scale        dashboard --> /infra/state, /apply, calibration
```

* **Gateway** (`gateway.py`) takes the old target app's port. It forwards every request to the least busy *Ready* replica and builds the same
  `/snapshot` the collector already reads. Latency is measured at the gateway (end to end), `app_cpu_pct` / `app_mem_mb` are the real mean per replica.
  If no replica is Ready, requests fail with 503: that is a real failure and it is counted.
* **ClusterManager** (`manager.py`) keeps the real count equal to what the agent asked for, clamped to the device limit. Scale-down drains first.
  It measures the real startup time of every replica and samples real CPU / memory (`data/infra/resources.csv`).
* **Backends** (`backends/`): `docker` (real containers, limits enforced), `k8s` (Pods of a Deployment), `process` (local processes, no limits; for machines without Docker).
* **Replica app** (`replica_app.py`) is your demo target app unchanged, except that the per-request CPU burn is measured in CPU time, so a smaller CPU share really makes a replica slower.
* **Device profile** (`device.py`): enter cores / RAM, per-replica share. Gives max replicas, and "auto-fit" picks the app weight (CPU ms per request) so the machine just carries the training peak.
* **Calibration** (`calibrate.py`): measures the real requests/s of one replica; the agent's capacity per replica then comes from this measurement.

## Run on your PC

```
pip install -r requirements.txt -r requirements-infra.txt
# Docker Desktop must be running. First start builds the replica image (about a minute).
python run_live.py                         # Docker containers
python run_live.py --backend process       # no Docker: local processes, limits not enforced
python run_live.py --tick 10               # 10 real seconds per simulated minute
python run_live.py --provider gemini       # real LLM in the agent
```
Open http://localhost:8501:
1. **Device & Timer**: check the machine numbers (Docker Desktop's VM may have less RAM than your PC), press **Apply**.
2. Stop the traffic, press **Run calibration** (about a minute), then **Apply** again so the agent uses the measured capacity.
3. **Cluster**: watch tiles appear (Starting -> Ready), per-replica CPU / memory, the CPU / RAM split, "wanted vs really ready", real latency and errors.

### Kubernetes (PC)
```
k3d cluster create aegis -p "30080:30080@server:0"      # or enable Kubernetes in Docker Desktop
docker build -t aegiscloud-replica:latest -f infra/docker/Dockerfile.replica .
k3d image import aegiscloud-replica:latest -c aegis       # not needed for Docker Desktop Kubernetes
python run_live.py --backend k8s
```
Pod CPU / memory come from metrics-server (refresh every 15-60 s), so those charts are slower than with Docker. Calibrate with the docker backend first
(calibration needs direct replica URLs); the result is reused because it depends only on CPU share, memory and app weight.
`infra/k8s/*.yaml` show the same objects for reference; the HPA file is an optional baseline.

## Experiments for the paper
```
python run_live.py --no-agent --no-frontend                     # baselines need the agent off
python -m infra.experiments.run_experiment --policy static --static-n 3 --reps 3
python -m infra.experiments.run_experiment --policy reactive --reps 3
python -m infra.experiments.run_experiment --policy hpa --reps 3
# stop, restart WITH the agent:  python run_live.py --no-frontend
python -m infra.experiments.run_experiment --policy aegis --reps 3
python -m infra.experiments.plot       # data/experiments/summary_table.csv + 2 figures
```
Each run: quiet traffic -> spike -> quiet, same for every policy. Measured from real requests: SLO-miss ticks, failed requests, replica-seconds (cost),
real startup time, overloaded ticks. Calibrate first, otherwise the capacity is only an estimate (the runner says so).

## Files written (data/infra/)
`device_profile.json`, `runtime.json` (tick length, capacity, backend: shared by all parts), `calibration.json`, `resources.csv` (per-replica CPU / memory),
`replica_events.csv` (create / ready / drain / remove, startup seconds), `cluster_ticks.csv` (one row per tick: wanted / ready / starting, latency, errors).

## Things to know (honest limits)
* The agent still thinks a new replica is instant (its state holds the *wanted* count). The real delay shows up as "wanted vs ready" and as real latency / errors.
* The process backend measures real CPU and memory but cannot limit them. Use docker or k8s for results about splitting resources.
* Changing the tick length keeps your CSV history, but the load per second changes (same requests per tick over a longer tick), so capacity per tick is recomputed.
* The gateway is a Python proxy and uses CPU too: that is why a share of cores is reserved on the Device tab.

## What was edited outside infra/
`frontend/app.py` (two new tabs, tick length read from runtime.json, only recent CSV rows are read), `frontend/data_access.py` (cached tail reader, parallel health checks,
capacity from runtime.json), `frontend/charts.py` (x-axis label uses the real tick length).
