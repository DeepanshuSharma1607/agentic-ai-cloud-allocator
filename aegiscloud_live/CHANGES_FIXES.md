# AegisCloud - fixes of 17 Nov 2026 (architecture unchanged)

Every service, port, CSV column, API route and graph node is the same. Only the points below changed.

| # | Problem found | Fix | File(s) |
|---|---|---|---|
| 1 | Starting the agent deleted `agent_ticks.csv`, `actions.csv` and all saved alerts | Default is now APPEND. `python -m agent.run --fresh` clears (old behaviour). `--keep-files` still accepted (no-op). Rows of an older run never count as "recent" for the new run | agent/run.py, agent/nodes.py |
| 2 | Raw console logs `data/logs/<part>.log` were opened with `"w"`: every start AND every restart wiped them | Opened with append, a `===== name started time =====` line marks each start, moved aside only above 10 MB | run_live.py |
| 3 | JSON logs rotated at 5 MB x 2 copies, so old agent logs vanished within hours | 20 MB x 5 copies (`AEGIS_LOG_MAX_MB`, `AEGIS_LOG_BACKUPS` change it) | obs/log.py |
| 4 | Agent re-read the WHOLE `agent_ticks.csv` 5 times per tick (gets slower as the file grows, worse with append) | Reads only the last 300 rows from the end of the file | agent/nodes.py |
| 5 | Gateway froze for the whole Docker create/stop/remove (seconds) because the routing lock was held during it | Slow Docker calls run after the lock is released (measured: routing waited 0.80 s before, 0.00 s now) | infra/manager.py |
| 6 | Dashboard redrew 5 panels every 2-3 s (also hidden tabs); Agent/Data tabs re-parsed and re-read big files each time | Default refresh 5 s (`AEGIS_REFRESH_SECONDS`), row counts and download bytes cached until the file changes | frontend/*.py |
| 7 | `agent/.env` was documented as "wins" but the root `.env` (read first) actually won | `agent/.env` now really overrides | agent/config.py |
| 8 | An LLM subject containing a line break made the email fail; app passwords with spaces; several recipients | Subject forced to one line, spaces removed, comma/semicolon recipients, plain-English failure reasons, every result logged | agent/mailer.py |
| 9 | No way to test mail without waiting for an alert | `python -m agent.mailer --check` (shows settings) and `--test` (sends a test mail) | agent/mailer.py |
| 10 | Alerts depended ONLY on capacity maths. With a wrong capacity the service could be slow or failing and no alert ever fired (your data: 0 alerts, p95 up to 9.5 s) | New rule on the REAL gateway numbers: p95 above 500 ms for 6 busy ticks, or over 5% errors for 3 busy ticks. Tunable in agent/config.py, `HEALTH_ALERTS = False` turns it off | agent/health.py, agent/nodes.py, agent/state.py, agent/config.py |
| 11 | Saved alert files were named by minute and could overwrite each other | `alert_<minute>_<time>.txt`, dashboard shows the newest by time | agent/nodes.py, frontend/app.py |
| 12 | Agent ignored the gateway's answer to a scale request (404/500 looked like success) | Status checked, clamping logged | infra/agent_real.py |
| 13 | Agent used ESTIMATED capacity after a calibration was measured (850 vs about 255 per tick in your data) | Loud warning at agent start; calibration message says "press Apply" | infra/agent_real.py, infra/gateway.py |

New tests: `tests/test_fixes.py` (18). Whole suite: 91 passed (prediction tests need torch and were not run here).

NOT changed on purpose: the LSTM, the 8-node graph logic, capacity formula, guardrail, Docker backend, CSV columns.
Not included in this zip: `.env` (never share it: your Gemini key and Gmail app password were inside the zip you sent, rotate them) and old run data.
