# Synthetic Traffic Dataset Generation and Forecasting Workflow

## Objective and research framing

The conversation designed and operated a controlled application workload for AegisCloud after the user concluded that real external users were not available for the demo. The agreed framing was a **synthetic workload driving a real FastAPI service**: request timing and traffic patterns are generated, while server CPU use, queueing, latency, and failures are measured on the running application. The workload should not be presented as human-generated production traffic.

The intended pipeline was:

`Traffic generator → FastAPI application / Prometheus metrics → CSV trace → LSTM forecast → agent → scaling action`

For a production application, only the traffic source would change; the rest of the metric/forecast/agent pipeline was intended to remain the same.

## Workload design and time compression

The initial proposal mapped every five seconds of real time to one simulated minute. The resulting time-compressed trace was designed to provide more sequential samples in a limited wall-clock collection window.

The generator was not intended to produce white noise. Its proposed request rate combined structured patterns and randomness:

`rate(t) = base × daily_cycle(t) × weekly_factor(t) × trend(t) + bursts(t)`

Requests per five-second tick were sampled from a Poisson distribution. Components included:

- A smooth daily cycle with morning ramp, daytime/evening peak, and night trough.
- Weekend traffic at approximately 60–70% of weekday traffic.
- Slow trend growth (the example function used 2% per simulated day).
- Random burst events with approximately 1.5–3.5× multipliers and exponential decay over several ticks.
- Poisson variation in requests per tick.
- Rare dips to mimic upstream outages were discussed as a desirable pattern.
- A fixed/random seed was retained for reproducibility; separate seeds were planned for train and test phases.

With one five-second tick labelled as one simulated minute:

- 1,440 ticks represent one simulated day, or two real hours.
- A 15-hour run produces 10,800 rows, representing 10,800 simulated minutes = 7.5 simulated days.
- The same 15 real hours at true one-minute sampling would yield only 900 observations.
- Twelve five-second rows can be aggregated into one real minute if true wall-clock minute buckets are required; the conversation gave `groupby(tick // 12).requests.sum()` as an example.
- A 10-minute forecast horizon in simulated time corresponds to 50 seconds in real time under this compression. This is a limitation to state when interpreting or comparing the forecasting results.

The recorded `minute` field is a sequential simulated-minute index. The separate `wallclock` field preserves actual timestamps. The `requests` column is the number of requests issued during a five-second tick (including those that fail); `ok` records successful responses. `true_rps` is the generator's intended request rate and is ground-truth context, not the observed successful throughput.

## Application and collection implementation

A new `~/traffic_lab` folder was created on EC2. The implemented files were:

### `app.py`

A small FastAPI workload application using:

- `WORK_MS` environment variable (default 10 ms) to control CPU work per request.
- `/work` endpoint that performs a CPU busy-loop and returns `{"ok": true}`.
- `/health` endpoint returning `{"status": "up"}`.
- Prometheus instrumentation with a request counter, latency histogram, and in-flight gauge, exported through `/metrics`.

The example workload used `WORK_MS=10`.

### `loadgen.py`

An asynchronous Python generator built with `asyncio`, `httpx`, `numpy`, and `psutil`. It:

- Computes the daily/weekly/trend/burst request rate.
- Samples the number of requests for each five-second window using Poisson sampling.
- Sends requests with randomized offsets within the tick.
- Captures successful responses, timeouts (default timeout 2 seconds), other errors, p50/p95/p99 latency, achieved RPS, app CPU, host CPU, and app memory.
- Writes one CSV row per tick and flushes rows to disk as the run proceeds.
- Stores the generated burst schedule in a matching `.bursts.json` file.

The schema was:

`tick, minute, wallclock, sim_day, sim_hour, true_rps, requests, ok, timeouts, errors, p50_ms, p95_ms, p99_ms, achieved_rps, app_cpu_pct, host_cpu_pct, app_mem_mb`

### `analyze.py`

The analysis script grouped offered load into 10-RPS bins and required at least five ticks in a bin. It used median p95 latency and mean failure rate to classify a bin as healthy when p95 was below 300 ms and failure rate below 1%. It estimated a per-replica capacity boundary and used:

- `scale_up_rps = 0.7 × capacity`
- `scale_down_rps = 0.3 × capacity`
- Suggested replica formula: `ceil(forecast_rps / scale_up_rps)`

It wrote `capacity.json` and optionally `capacity.png` (the latter required `matplotlib`).

## EC2 setup and execution history

The user had already connected to EC2. The first setup attempt showed `pip` was not installed. The solution was to install `python3-venv` and `python3-pip`, create `~/traffic_lab/venv`, activate it, and install FastAPI, Uvicorn, `prometheus-client`, `httpx`, `psutil`, NumPy, and pandas (Matplotlib was installed later as an optional dependency).

The app and generator were launched detached from SSH using `nohup setsid`. Closing SSH was safe; stopping/rebooting the EC2 instance was not. The transcript cautioned that running the generator and app on one EC2 instance makes them compete for CPU and can distort capacity estimates. It also noted possible T-instance CPU-credit exhaustion over a long run.

A 20-minute trial was run. Its `analyze.py` result reported capacity 20 RPS, scale-up 14 RPS, scale-down 6 RPS, and no observed timeouts, but this was explicitly rejected as a reliable capacity estimate because the trial only covered a low load range. The full 15-hour run was then started.

## Part 1: 15-hour run and capacity analysis

The first main run used:

- Output: `data/metrics_20261027_1649.csv`
- Duration: 15 hours
- Tick: five seconds
- Base rate: 50
- Seed: 42 (default in the initial command)
- Expected: 10,800 rows, minutes 0–10,799, plus a CSV header.

The conversation records a successful completion check on 28 October 2026: the server CSV had 10,801 lines, and `pgrep` showed no `loadgen` process. The user downloaded the dataset and the Python scripts (`app.py`, `loadgen.py`, and `analyze.py`) from EC2 to:

`C:\Users\Deepanshu sharma\Desktop\traffic_lab\`

The main CSV was in `Desktop\traffic_lab\data\metrics_20261027_1649.csv`. The downloaded data directory also contained trial data, logs, and burst-schedule JSON files.

The full-run `analyze.py` result supplied by the user was:

| Offered RPS bin | Ticks | Mean app CPU | Median p95 ms | Mean fail rate | Healthy |
|---:|---:|---:|---:|---:|---|
| 0 | 2,525 | 8.3% | 20.1 | 0.0 | Yes |
| 10 | 1,800 | 17.4% | 24.5 | 0.0 | Yes |
| 20 | 1,606 | 28.2% | 28.4 | 0.0 | Yes |
| 30 | 1,826 | 39.1% | 33.8 | 0.0 | Yes |
| 40 | 1,481 | 48.9% | 38.4 | 0.0 | Yes |
| 50 | 1,102 | 56.7% | 43.8 | 0.0 | Yes |
| 60 | 114 | 65.4% | 53.9 | 0.0 | No |
| 70 | 62 | 72.4% | 67.0 | 0.1 | No |
| 80 | 55 | 73.1% | 93.7 | 0.1 | No |
| 90 | 41 | 84.6% | 356.0 | 0.2 | No |
| 100 | 39 | 90.7% | 1,220.6 | 0.3 | No |
| 110 | 32 | 92.2% | 1,952.4 | 0.6 | No |
| 120 | 23 | 100.0% | 1,346.0 | 0.6 | No |
| 130 | 20 | 100.8% | 846.2 | 0.7 | No |
| 140 | 18 | 100.9% | 680.5 | 0.7 | No |
| 150 | 14 | 100.8% | 1,982.8 | 0.8 | No |
| 160 | 10 | 99.8% | 1,373.3 | 0.9 | No |
| 170 | 12 | 85.7% | 2,002.0 | 0.7 | No |
| 180 | 10 | 75.3% | 1,957.7 | 0.8 | No |
| 190 | 6 | 86.9% | 1,925.6 | 0.5 | No |

The generated `capacity.json` reported:

- `capacity_rps_per_replica`: 60.0
- `scale_up_rps`: 42.0
- `scale_down_rps`: 18.0
- `cpu_pct_at_capacity`: 56.7
- `scale_up_cpu_pct`: 39.7
- `ticks_app_dead`: 0
- `ticks_with_timeouts`: 195
- `slo_p95_ms`: 300
- Replica formula: `ceil(forecast_rps / scale_up_rps)`

The assistant noted that 60 RPS was a conservative selected capacity boundary: 60–80 RPS bins still had median p95 below 100 ms but failed the configured failure-rate condition; p95 exceeded 300 ms around the 90-RPS bin, and severe saturation occurred at higher loads. The top bins had few ticks, so their estimates were less reliable. The 195 ticks with timeouts represented about 1.8% of the run; the app did not die.

The largest bursts were about 190 RPS, implying around five replicas at a 42-RPS scale-up threshold (`ceil(190/42) = 5`). The assistant recommended a maximum of at least five replicas as a planning value, not as a measured Kubernetes deployment result.

## Extension to 14 simulated days: Part 2

The Azure reference data was described as 20,160 minutes (14 days). Since part 1 yielded 10,800 simulated minutes (7.5 days), the proposed extension was 9,360 additional rows over 13 real hours.

`loadgen.py` was patched to accept `--start-tick`, offset the tick/minute fields and simulated day/hour, and continue the daily/weekly pattern from tick 10,800. A new seed (`43`) was used for different burst timings. A backup was made as `loadgen_part1_backup.py` in the later command sequence.

A 40-second dry run was actually executed and verified. Its first row began with:

`10800,10800,...,7,12.0,...`

This confirmed the offset and continuation point. The proposed full command was:

`nohup setsid python loadgen.py --hours 13 --base 50 --seed 43 --start-tick 10800 --out data/metrics_part2.csv > data/loadgen_part2.log 2>&1 &`

A later user check showed 152 of 9,360 rows and a running generator; the first progress pace was consistent with one row per five seconds. The expected finish was estimated around 3:48 AM IST on 29 October. **The conversation does not contain confirmation that part 2 completed or that the two files were merged into a 20,160-row dataset.**

## Project-folder and notebook work discussed

An earlier `aegiscloud_major.zip` project pack was described as having been created. It contained a README, `requirements.txt`, raw/processed data folders, figures/results folders, `notebooks/colab_lstm.ipynb`, and source scripts (`common.py`, `make_figures.py`, `prepare_dataset.py`, `plot_forecast.py`). Its planned outputs included 12 publication-style figures. The scripts were tested on stand-in data shaped like the user's data, not on the real CSV; the fake test data was removed before the ZIP was produced. The Colab notebook had not been run.

After reviewing the user's original Azure training notebook, the conversation recorded these properties:

- Azure dataset: 20,160 minutes × 318 applications.
- Six sampled apps/models in the experiment.
- Forecast target: traffic 10 minutes ahead, using `log1p` values.
- LSTM: 60-minute window, hidden size 64, yesterday's target/change and time-of-day features.
- Gradient Boosting and PyTorch LSTM were compared with a 70/30 chronological split.
- Reported original WAPE: LSTM 0.189, GBM 0.191, naive baseline 0.361.
- `aegiscloud_best_lstm.zip` was described as containing six `.pt` files, one per sampled app, each with its own normalization statistics. The original export discussion did not establish that corresponding GBM artifacts were saved.

The user required the old notebook's cells 0–23 to remain byte-for-byte unchanged, with all additions appended after the final existing cell. The user said they would rerun the old notebook fresh and wanted a concise plan before code or ZIP creation, followed by explicit approval.

The proposed appended workflow was:

1. Load part 1 now and allow part 2 to be added later through a `DATA_FILES` configuration; stitch by `minute`, check gaps, and use new variable names so old notebook variables are not overwritten.
2. Perform data validation and visualizations before model fitting: trace overview/split, daily profile, burstiness compared with Azure apps, intended vs observed load, generator pacing from `wallclock`, CPU/latency/failure vs load, memory/host CPU, heatmaps, and burst-schedule vs detector checks. Add sanity checks for perfect-forecast score, alignment, split leakage, and an oracle/noise-floor reference (`true_rps * 5` at the target horizon).
3. Test all six saved Azure LSTMs on the new test data without training, in both original scaling and matched scaling; report WAPE, under-10%, over-10%, and burst-window WAPE.
4. Retrain GBM, GBM q90, LSTM, and LSTM q90 using the original notebook's modelling recipe on the new series.
5. Compare the Azure models, retrained models, baselines, and oracle in one table and figures, and identify the best result.
6. Save result CSVs and model artifacts; optional Azure-model fine-tuning could be kept separate.

The assistant stated that it had begun drafting this extension but stopped after six of approximately fifteen new cells because the conversation was running out of tokens. No completed expanded notebook was delivered in this conversation. The final response supplied a prompt for a new chat and asked the user to attach:

- `lstm_model.ipynb` (original notebook),
- `metrics_20261027_1649.csv` (part 1),
- `metrics_part2.csv` only after that run completed.

The note also said the `.log` and `.json` files were not required just to build the first notebook draft; they would be relevant for the additional workload diagnostics when available.

## Research limitations and interpretation points

- The trace is a synthetic workload by design, not real human traffic. The backend work performed by FastAPI is real, and the generated requests cause real measured CPU, latency, queueing, and failures.
- Time compression changes the temporal meaning of spikes and scaling delays. In particular, a 10-simulated-minute forecast is 50 real seconds, and real container startup times do not scale automatically with the compressed clock.
- The load generator and app shared one EC2 host; host CPU may reflect both processes, which limits the purity of one-replica capacity measurements.
- Capacity thresholds depend on the chosen p95 SLO (300 ms), failure tolerance (1%), 10-RPS bins, and minimum five ticks per bin.
- The suggested 42-RPS scale-up threshold is based on the measured single-app run and selected 60-RPS capacity boundary; it is a starting heuristic for later deployment validation.
- The random burst schedule is known to the experimenter and stored in `.bursts.json`; the workload should use separate seeds for reproducible train/test separation.
- Random, sudden bursts are difficult for a history-only forecast to anticipate. The conversation therefore motivated a hybrid control design: slower predictive scaling for the recurring pattern and a faster reactive path based on current CPU/request-rate signals for abrupt bursts.
- The planned comparison of Azure zero-shot, matched-scaling, fine-tuned, and retrained models remained a plan, not a completed experiment in this conversation.
