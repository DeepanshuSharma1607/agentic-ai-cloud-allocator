# Traffic Lab Archiving, CSV Cleanup and Analysis

## 1. Objective and Environment

The conversation focused on transferring the complete `traffic_lab` directory from an AWS EC2 Ubuntu instance to a Windows PC, excluding unnecessary archives and eventually excluding the Ubuntu virtual environment. The EC2 directory was `~/traffic_lab`; the user's SSH connection used the `cloud_allocator.pem` key and public address `16.16.253.3`.

The user verified that `data/metrics_part2.csv` contained **9,360 data rows** after changing into the correct `~/traffic_lab` directory.

## 2. Creating and Downloading the ZIP

The recommended workflow was:
1. Create an archive on EC2 outside the source folder (`~/traffic_lab_fresh.zip`).
2. Exclude any older `.zip` files inside `traffic_lab` so they are not nested into the new archive.
3. Exit SSH and run `scp` from Windows PowerShell using the real key path and public IP.
4. Save the archive on the Windows Desktop or Downloads folder and verify it with PowerShell/File Explorer.

An early command was mistakenly run with placeholder values (`C:\path\to\your-key.pem` and `YOUR_PUBLIC_IP`), and once from the Ubuntu prompt. This caused a missing identity-file / hostname error. The corrected `scp` command was run from Windows PowerShell.

A transfer later completed at **100%**, with a reported size of about **129 MB** and transfer time of 5 minutes 39 seconds. The archive was saved as `traffic_lab.zip` on the Desktop. The two remote ZIP archives were subsequently removed with `rm -f`, and `ls` confirmed they no longer existed at those paths. The source `~/traffic_lab` directory and its data were not deleted.

## 3. Virtual Environment Handling

The initial ZIP command excluded old ZIP files but did **not** exclude the virtual environment. An archive listing confirmed that `traffic_lab/venv/` and its Python 3.14 `site-packages` contents were included.

A revised archive command was then provided with exclusion patterns for:
- `traffic_lab/venv/*`
- `traffic_lab/venv/**`
- `traffic_lab/*.zip`

The conversation recommended excluding the Ubuntu virtual environment because it is platform-specific and generally cannot be reused on Windows; the environment should instead be recreated locally from the requirements file. The transcript provides the revised command and a grep-based verification step, but does not show the final verification output after exclusion.

## 4. EC2 Resource Monitoring Commands

The following commands were provided for checking the server while load generation or analysis runs:

| Purpose | Command |
|---|---|
| RAM usage | `free -h` |
| CPU core count | `nproc` |
| CPU details | `lscpu` |
| Live CPU/process usage | `top` (press `q` to exit) |
| Disk capacity | `df -h` |
| Traffic lab directory size | `du -sh ~/traffic_lab` |
| Optional interactive monitor | install and run `htop` |

## 5. CSV Renaming and Analysis Script

The user requested renaming the two source CSVs without changing their contents:

```text
metrics_20261027_1649.csv  ->  metrics_part_1.csv
metrics_part2.csv          ->  metrics_part_2.csv
```

A safety check was included to stop if either original file was missing or either destination name already existed.

The uploaded `analyze_traffic.py` was reviewed and a cleaned version was provided. It was designed to read both renamed CSVs, combine them for analysis without modifying the source files, and retain useful validation, summaries, visualizations and reports. The analysis covered:
- offered/target/achieved request rates;
- p50, p95 and p99 latency;
- application and host CPU plus application memory;
- successes, errors, timeouts and failure rates;
- rolling, hourly and daily workload summaries;
- capacity and overload exploration;
- missing values, duplicate ticks, gaps and timing consistency;
- metric correlations and load-versus-latency/CPU relationships.

Outputs were specified under `data/analysis_output/`, including plots, `summary.md`, `summary.json`, `derived_metrics.csv`, `daily_summary.csv`, `overload_intervals.csv` and `metric_correlations.csv`.

## 6. Combined Dataset Output

After a follow-up request, the script was updated to also create:

```text
data/metrics_combined.csv
```

The intended combined file contains the original columns and records from Part 1 followed by Part 2. The source CSVs remain unchanged; the actual combined file is generated on EC2 when `python analyze_traffic.py` is run. The two real source CSVs were not attached to the chat, so the assistant did not create the combined data file in the conversation itself.

## 7. Run and Transfer Workflow

The prescribed execution sequence was:

```bash
cd ~/traffic_lab
source venv/bin/activate
python analyze_traffic.py
```

The updated script was to be uploaded from Windows with `scp`. After analysis, `metrics_combined.csv` could be copied back to the Windows Desktop with another `scp` command.

A caution was recorded: the script sorts/combines records by tick and reports duplicate/gap diagnostics. Those checks matter if the two files are not actually consecutive parts of one continuous run. Capacity estimates in the script were described as exploratory, not a production scaling guarantee.
