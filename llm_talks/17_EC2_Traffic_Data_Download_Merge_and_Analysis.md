# EC2 Traffic Dataset Download, Merge, and Analysis

**Source conversation:** `Download SSH Folder`  
**Conversation date:** 28 October 2026  
**Scope:** Snapshotting and downloading the remote `traffic_lab` folder, combining two CSV data segments, and preparing a reusable traffic-analysis pack.

## Objective and remote collection state

The user was collecting a second traffic-data segment on an Ubuntu EC2 instance and wanted to download the complete `traffic_lab` folder to a Windows PC. At the first status check:

- `data/metrics_part2.csv` contained **5,205 of 9,360 expected data rows**.
- `loadgen.py` was still running with `--hours 13 --base 50 --seed 43 --start-tick 10800 --out data/metrics_part2.csv`.
- A Uvicorn application process was also running at `127.0.0.1:8000`.

A later check showed **5,392 / 9,360 rows** (57.6% complete, 3,968 remaining). The conversation estimated approximately 5 hours 31 minutes remaining at the observed five-second cadence. These were progress snapshots; the file was not yet complete at those points.

## Downloading the remote folder

Two packaging options were discussed.

### Complete archive after collection finishes

After verifying that the row count reaches `9,360 of 9,360` and that no `loadgen.py` process remains, the proposed Ubuntu command creates:

```bash
cd ~
tar \
  --exclude='traffic_lab/venv' \
  --exclude='traffic_lab/.venv' \
  -czf traffic_lab_complete.tar.gz traffic_lab
```

The Linux virtual environments were excluded because they are bulky and not directly reusable on Windows. The archive could then be copied from Windows PowerShell using `scp` and extracted on the Desktop.

### Current snapshot before collection finishes

The user also wanted to download the data collected so far. The suggested process installed `zip` if needed and created:

```bash
zip -r ~/traffic_lab_current.zip traffic_lab \
  -x "traffic_lab/venv/*" "traffic_lab/.venv/*" "traffic_lab/**/__pycache__/*"
```

The archive was then downloaded from Windows PowerShell into the PC's Downloads folder:

```powershell
$dest = "$env:USERPROFILE\Downloads\traffic_lab_current.zip"
scp -i "C:\Users\Deepanshu sharma\Downloads\cloud_allocator.pem" `
  ubuntu@16.16.253.3:~/traffic_lab_current.zip $dest
```

This is a **point-in-time snapshot**: the traffic generator can continue after packaging, but rows recorded later are not included in that ZIP. The original remote files remain on EC2 after download.

## Combining the two CSV segments

The two input files were identified as:

- `metrics_20261027_1649.csv` — expected **10,800** data rows.
- `metrics_part2.csv` — expected **9,360** data rows once collection completed.

The expected combined total was therefore **20,160 data rows**, plus one header row.

The intended output was `metrics_combined.csv`, retaining all original columns (including traffic, successful requests, timeouts, errors, latency, CPU, memory, and other measurements). The merge logic:

1. Opens both files with `csv.DictReader`.
2. Checks that their headers match.
3. Appends the data rows.
4. Sorts chronologically by `tick`, falling back to `minute` if `tick` is absent.
5. Writes one header and all rows to the combined output.

The first attempt failed because `combine_datasets.py` had not actually been created in the current PowerShell directory. A replacement PowerShell here-string was then supplied to create a script that searched both the project root and its `data` subfolder, wrote `metrics_combined.csv`, and reported row totals, duplicate ticks, detected gaps, and tick range. The user said the script was named `combined_dataset`; the conversation does not include a final successful merge output or a verified final row count.

The user had created a local `uv` environment (CPython 3.14.5) and installed NumPy, Pandas, and Matplotlib. The missing-script errors were not caused by those package installations.

## Traffic analysis toolkit

The user supplied representative columns and rows from the traffic dataset, including:

`tick`, `minute`, `wallclock`, `sim_day`, `sim_hour`, `true_rps`, `requests`, `ok`, `timeouts`, `errors`, `p50_ms`, `p95_ms`, `p99_ms`, `achieved_rps`, `app_cpu_pct`, `host_cpu_pct`, and `app_mem_mb`.

A reusable traffic-analysis pack was provided as `traffic_analysis_pack.zip`, with standalone `analyze_traffic.py` and `README_traffic_analysis.md` files. The described toolkit generated around 40 plots and tabular summaries covering:

- Offered/target load, achieved throughput, burst patterns, rolling trends, and simulated-day/hour heatmaps.
- p50, p95, and p99 latency trends and distributions.
- Successful, failed, timed-out, and error request counts/rates.
- Application and host CPU, application memory, and their relationships with load and latency.
- Load bins, threshold-based health flags, possible overload intervals, and metric correlations.
- Data-quality checks and derived metrics.

The proposed output directory was `analysis_output/`, containing:

| Output | Intended contents |
|---|---|
| `plots/` | Generated visualizations |
| `summary.md` / `summary.json` | Human-readable and machine-readable statistics |
| `derived_metrics.csv` | Input data plus calculated metrics |
| `daily_summary.csv` | Statistics grouped by simulated day |
| `load_bins_summary.csv` | Load-bin and reference-health summaries |
| `overload_intervals.csv` | Candidate periods of high CPU, latency, or failures |
| `metric_correlations.csv` | Numeric metric relationships |

Example commands were:

```powershell
uv run python analyze_traffic.py --csv data\metrics_combined.csv
```

or, if the combined CSV was in the project root:

```powershell
uv run python analyze_traffic.py --csv metrics_combined.csv
```

The user had shared example rows, not the full combined CSV. The conversation explicitly stated that no actual findings had been computed from the complete dataset. The toolkit's thresholds were described as diagnostics/candidate overload indicators, not proof of a production scaling limit.

## Important decisions and unresolved items

**Decisions**
- Preserve the full `traffic_lab` project and CSVs when packaging.
- Exclude only environment/cache folders that are not useful on Windows.
- Keep both source CSV segments and create a separate combined file.
- Sort merged data by `tick` where available.
- Retain detailed metrics for analysis rather than reducing the raw dataset to only request counts.

**Verified in the conversation**
- The remote generator was still running during the two reported progress checks.
- The second segment had not yet reached its expected 9,360 rows at those checks.
- The local Python packages installed successfully.

**Not verified in the conversation**
- Completion of `metrics_part2.csv`.
- A successful final merge yielding 20,160 rows.
- Execution of the complete analysis pack against the full dataset.
- Any measured conclusions about the complete workload or its true capacity limits.
