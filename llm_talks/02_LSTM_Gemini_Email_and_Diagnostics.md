# LSTM Integration, Gemini, Email and Diagnostics Plan

## 1. Live System Architecture

The ZIP was reviewed as a live version of the earlier replay-based allocator. Its intended data flow is:

`loadgen → target_app → collector → prediction (LSTM) → LangGraph agent (Gemini) → alerts/email`

The dashboard reads the CSV outputs. One tick represents 5 real seconds and 1 simulated minute.

Main components:
- `run_all.py`: starts the services and stops them on Ctrl+C.
- `settings.py` and `seed.py`: central configuration and historical warm-up data.
- `prediction/`: model definition, preprocessing/inference, rolling history, FastAPI endpoints, and training scripts.
- `traffic/`: target application, controllable request sender and 5-second collector.
- `agent/`: LangGraph state, eight nodes, LLM provider layer, email sender, configuration and Prometheus metrics.
- `frontend/`: Streamlit dashboard.
- `tests/`: 14 existing pytest tests using fake data.

## 2. Connecting the Trained LSTM

The predictor expects a checkpoint dictionary, not only a bare PyTorch `state_dict`. Required fields listed in the conversation were:

`state_dict`, `H`, `W`, `DAY`, `metric_cols`, `target_col`, `mu`, `sd`, `dsd`, `n_features`, and `n_static`.

The model layers are expected to be named `lstm` and `head`. The prescribed location is `prediction/models/`. The historical data file belongs at `data/seed/metrics_combined.csv`.

The predictor reproduces the notebook's preprocessing: `log1p`, saved scaling values, a 60-row window and four static features. The model in this conversation covered H=10 only; H=20 would remain empty until a second horizon model was trained.

A warning was raised about `prediction/models/demo/`: the predictor loads `.pt` files recursively, so fake demo checkpoints could be averaged with the real model. The demo folder should not be left alongside the production checkpoint. The seed CSV also needed to be checked because `--demo` could overwrite its path with synthetic data.

## 3. Gemini and Gmail Configuration

The conversation specified `GEMINI_API_KEY`, `EMAIL_SENDER`, `EMAIL_PASSWORD`, and `EMAIL_TO` in a local `.env` file. Gmail requires an App Password with 2-step verification, not the normal account password.

Email sending was disabled by default. At that time, `run_all.py` had no `--email` flag; the proposed choices were to enable `ALERT_SEND_EMAIL` in `agent/config.py` or run the agent separately with `--email`. A forced test alert was proposed to verify the email path without waiting for a natural overload.

Gemini model names configured in the project were not verified for the user's API key. The advice was to check `data/logs/agent.log` and substitute a model name supported by the account if calls failed. Mistral was explicitly excluded from future live testing in the handoff instructions because the user said it had become paid.

## 4. Approved Diagnostics Folder Specification

The user approved a separate `diagnostics/` folder that would inspect all project files without modifying project source code or real data. The requested command was:

`python -m diagnostics.run`

Planned capabilities:
- Isolated checks so one crash does not stop the rest.
- File-by-file Markdown and JSON reports, including file, check, status, exception, message, line, likely cause and suggested fix.
- Static checks (compile/import/dependencies), unit tests with normal and malformed inputs, FastAPI integration checks, real-asset checks and a short end-to-end test.
- Opt-in local checks for a real Gemini call and one Gmail test email.
- Temporary directories, temporary ports and `AEGIS_*` path overrides to protect real project data.
- No new dependencies beyond the existing project requirements.

Ten explicit risks were to be tested: checkpoint format, Gemini model names, email enablement, recursive loading of demo models, possible synthetic seed data/stale runtime CSVs, `.env` precedence, SMTP fallback behavior, absent H=20 model handling, drift detection and tick-versus-minute documentation.

**Status:** this file records an approved specification and handoff report. It does not show that the complete diagnostics folder was built or delivered.

## 5. Dashboard Traffic Controls and Stalled Live Data

Daily Pattern mode replays the typical daily curve from the seed data. `Size` multiplies the curve; the described baseline mean was 158 requests per tick. Burst chance controls how often a burst begins, and burst size multiplies traffic during the burst.

The settings shown in the conversation—burst chance 0.06 and burst size 6.5—were considered aggressive relative to suggested fair-evaluation values of 0.01 and 3.0. Aggressive bursts were expected to trigger unusual mode frequently and could put traffic outside the training distribution.

The final user question reported that live data appeared stuck at one position. The exported conversation ends before a diagnosis or fix is provided.
