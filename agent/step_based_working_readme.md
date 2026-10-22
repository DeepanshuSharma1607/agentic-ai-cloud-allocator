# AegisCloud agent (LangGraph)

Every "minute" the graph runs once:

1. `store_prediction`: LSTM forecast for +10 min, one row appended to `data/predictions.csv`
2. `trigger_check`: picks the mode, priority **unusual > timer > auto**
3. `script_creator`: text report of the last 10 minutes (actual vs predicted)
4. one branch: `llm_unusual` | `llm_timer` | `auto_scale`
5. `apply_and_log`: guardrail, set replicas (placeholder), log to `data/actions.csv`
6. `alert_human`: only if something is wrong; the LLM writes an urgent email (saved in `data/alerts/`, sent if enabled)

## Folder

```
Major_Project/
  notebook/   predict.py, models/*.pt, dataset.csv     (already there)
  agent/
    config.py   all settings
    state.py    the dictionary passed between nodes
    llm.py      fake / Gemini / Mistral + alert email writer
    mailer.py   SMTP email
    nodes.py    the 8 nodes
    graph.py    wiring
    run.py      start here
    .env        your keys (copy from .env.example)
    data/       created automatically
```

## Setup and run

```
uv pip install -r agent/requirements.txt
python agent/run.py --minutes 120 --tick 0       # quick test with the fake LLM, no keys needed
python agent/run.py --provider gemini --timer 3  # real LLM
python agent/run.py --email                      # also send alert emails
```

## Where to change things

Everything is in `config.py`: timer, thresholds for "unusual", guardrail limits, alert rules, LLM model names.
`set_replicas()` in `nodes.py` is the one place to connect Docker / Kubernetes later.