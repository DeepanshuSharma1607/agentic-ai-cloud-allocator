# Pre-deployment hardening (no architecture, schema or data changes)

| # | File | Change |
|---|------|--------|
| 1 | `infra/docker/Dockerfile.replica` | Copies `obs/` and `ui/`. A freshly built replica image used to crash with `ModuleNotFoundError: obs`. **Rebuild the replica image once.** |
| 2 | `traffic/collector/app.py` | One failing tick (bad snapshot, CSV locked by Excel) is logged and skipped; the collector loop no longer dies silently. |
| 3 | `agent/run.py` | One failing tick is logged and skipped; the agent no longer exits. |
| 4 | `infra/agent_real.py`, `agent/nodes.py` | The scale command is retried 3 times (6 s timeout). If the gateway still does not confirm, the agent keeps its old replica count and asks again next tick (it used to believe the scale had happened). |
| 5 | `agent/llm.py`, `agent/config.py` | New `LLM_MIN_GAP_SECONDS = 20` (real seconds between online LLM calls, independent of tick length). When skipped, the plain formula decides. |
| 6 | `agent/llm.py`, `agent/config.py` | `Retry-After` honoured, jitter added, and a 429 that survives the retries pauses the online LLM for `LLM_BREAKER_SECONDS = 120`. Alert e-mails still go out (plain-code text) during the pause. |
| 7 | `infra/calibrate.py` | The slow Docker create no longer holds the gateway's routing lock, so the gateway does not freeze during calibration. |
| 8 | `infra/manager.py` | A container adopted from an earlier run no longer records its age as a "startup time". |
| 9 | `infra/gateway.py` | Per-window latency list is bounded (200,000). |
| 10 | `frontend/data_access.py` | A read-only call to a service that just failed is skipped for 6 s, so a stalled backend does not make every dashboard refresh wait for the full timeout. |
| 13 | `obs/store.py` | The log viewer reads only the files of the requested app (was re-parsing every file once per file). |
| 14 | `traffic/loadgen/app.py`, `frontend/app.py` | Hide two harmless noise sources (Windows WinError 10054 tracebacks, plotly nanosecond warning). |
| - | `agent/nodes.py`, `prediction/engine.py`, `traffic/loadgen/engine.py` | CSV appends retry and then drop only that one row with a warning if the file is locked. |
| - | `tests/test_hardening.py` | 10 new tests for the items above. |

Cleanup: removed only generated files (`__pycache__/`, `.pytest_cache/`) and the empty `package-lock.json`. `data/`, `data.zip`, both READMEs and every source file are kept.
