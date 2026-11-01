# data/

| Folder | File | Written by | Content |
|---|---|---|---|
| `seed/` | `metrics_combined.csv` | you | your training data (needs `minute` + the 8 metric columns) |
| `live/` | `live_metrics.csv` | collector | one row per tick: tick, minute, wallclock, load_mode, planned, ok, errors, requests, p50/p95/p99, achieved_rps, app_cpu_pct, host_cpu_pct, app_mem_mb |
| `predictions/` | `predictions.csv` | prediction service | minute, requests_now, forecast_h10 (+ the minute it is for), forecast_h20 (+ minute), history_source (seed/live), drift_z, drift_metric |
| `agent/` | `agent_ticks.csv`, `actions.csv`, `alerts/` | agent | per-tick log with replicas, every decision, saved alert emails (cleared on each agent start unless `--keep-files`) |
| `loadgen/` | `load_ticks.csv`, `events.csv` | request sender | what was planned/sent/failed per tick; start/stop/schedule events |
| `logs/` | `*.log` | run_all.py | output of each part |

`minute` continues from the seed file, so the model's time-of-day features stay correct across restarts.
