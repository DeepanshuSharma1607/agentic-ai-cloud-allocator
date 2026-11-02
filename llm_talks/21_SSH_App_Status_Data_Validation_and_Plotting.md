# SSH App Status, Dataset Validation, and Plotting

## Objective and context

The conversation checked whether the FastAPI application and traffic generator were still running on EC2 after the user downloaded an initial CSV snapshot. It then covered how to inspect the server-side data, refresh the local VS Code copy, plot the workload and resource metrics, and interpret the observed overload behaviour.

## Application and generator status

The suggested live checks were run from `~/traffic_lab`:

- List `uvicorn` and `loadgen.py` processes with `ps`.
- Query `http://127.0.0.1:8000/health`.
- Inspect CSV file size and row count, latest rows, and `data/loadgen.log`.

The user supplied a successful snapshot at approximately 02:03 on 28 October 2026:

- FastAPI process: PID `16730`, running `uvicorn app:app --host 127.0.0.1 --port 8000`.
- Traffic generator: PID `16843`, running `loadgen.py --hours 15 --base 50 --out data/metrics_20261027_1649.csv`.
- Health endpoint returned `{"status":"up"}`.
- The main CSV had 2,689 lines, i.e. 2,688 data rows plus a header.
- Its latest displayed tick was `2687`; the latest five rows recorded 141–172 requests per five-second tick, matching successful counts, zero timeouts/errors, app CPU around 31.6–38.2%, and p95 latency around 27–34 ms.
- The generator log had advanced through tick 2640 of 10,800.

This was a point-in-time check, not proof that the processes remained active after that snapshot. The 15-hour run was expected to produce 10,800 data rows (10,801 CSV lines including the header), with the generator stopping automatically. The FastAPI app could continue running after the generator finished.

## Local CSV inspection and plotting

The user's VS Code folder contained an earlier downloaded snapshot. The assistant explained that EC2's growing CSV and a local downloaded CSV are separate files: `scp` creates a snapshot and does not keep the local file synchronized. A fresh copy was downloaded under a `_latest.csv` name to avoid overwriting the earlier copy.

A `plot_data.py` script was provided using `pandas` and `matplotlib`. It selected the latest CSV when present, otherwise the main CSV or `trial.csv`, checked required columns, converted metrics to numeric values, and generated four PNGs in `plots/`:

1. `traffic_rate.png` – target `true_rps` and achieved RPS over the simulated-minute index.
2. `cpu_usage.png` – application and host CPU, with a 70% reference line.
3. `latency.png` – p50, p95, and p99 latency.
4. `failures.png` – timeouts and errors.

The user ran the script successfully against a 2,269-row local snapshot. The printed summary was:

| Metric | Result |
|---|---:|
| Mean `true_rps` | 29.48 |
| Mean `achieved_rps` | 26.10 |
| Mean app CPU | 30.91% |
| Mean host CPU | 21.77% |
| Mean p95 latency (2,240 non-null rows) | 94.76 ms |
| Maximum app CPU | 101.9% |
| Maximum host CPU | 97.7% |
| Maximum p95 latency | 3,505.9 ms |
| Total successful requests | 296,072 |
| Total timeouts | 39,376 |
| Total errors | 26 |

The partial local file also had a maximum of 988 timeouts in one tick. These metrics describe that 2,269-row local snapshot; they must not be conflated with the separate EC2 status snapshot showing 2,688 rows. The local file was identified as stale relative to the server and the user was instructed to refresh it before final analysis.

## Interpretation and limitations

The plots showed meaningful stress-test behaviour in the displayed data: offered traffic could exceed achieved throughput, app CPU approached one fully utilized core, p95 latency developed a long tail, and timeouts increased during peaks. The assistant interpreted these as overload evidence, not proof that autoscaling worked.

Important distinctions recorded in the conversation:

- `requests` represents requests issued during the tick; `ok` is the successful subset.
- The generator writes one row every five real seconds, but assigns one sequential simulated minute to each row. Therefore 2,269 rows represent about 3 hours 9 minutes of real collection and about 2,269 simulated minutes (roughly 37.8 simulated hours).
- A 15-hour collection at five seconds per row yields 10,800 rows, corresponding to 7.5 simulated days under this time-compression convention.
- The plots use the simulated-minute axis, not actual elapsed minutes.
- The load generator and application share the EC2 machine, so their CPU use can interfere with capacity measurements. This was explicitly identified as a source of measurement distortion.
- High-latency and low-CPU anomalies during overload were discussed as possibly related to client timeouts, server work continuing after clients give up, and generator scheduling lag; these causes were hypotheses, not confirmed findings.
- Plotting and capacity curves alone do not establish that Docker containers or Kubernetes replicas were actually created.

## Tools and files

- Server folder: `~/traffic_lab/`
- Main CSV: `data/metrics_20261027_1649.csv`
- Trial CSV: `data/trial.csv`
- Related files: `.bursts.json` schedules, `loadgen.log`, and `trial.log`
- Local plotting script: `plot_data.py`
- Generated image files: `plots/traffic_rate.png`, `plots/cpu_usage.png`, `plots/latency.png`, and `plots/failures.png`
- Python libraries: `pandas`, `matplotlib`

## Decisions and pending work

- Use the full main CSV, not `trial.csv`, for project evaluation.
- Refresh local data from EC2 before analysing or publishing plots.
- Run `analyze.py` after collection completes to estimate capacity; the short trial's capacity estimate was explicitly considered unreliable because it covered too little load range.
- Verify scaling separately by observing actual replica counts and scale actions.
- The expected 15-hour stop time was estimated as about 1:19 PM IST on 28 October 2026, based on an approximately 10:19 PM IST start on 27 October. This was a forecast in this conversation, not a completion confirmation.
