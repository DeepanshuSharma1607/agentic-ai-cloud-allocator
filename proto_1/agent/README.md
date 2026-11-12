# agent/

The LangGraph autoscaler from your earlier project, now live. The graph (`graph.py`, `nodes.py`), the LLM layer
(`llm.py`), alerts (`mailer.py`) and Prometheus metrics (`metrics.py`) are unchanged in logic.

What changed:
* `feed.py` (new) replaces the dataset replay: it asks the prediction service for the newest tick, with +10 and +20 forecasts.
* `run.py` runs the graph once per new tick and waits for the prediction service to be ready.
* `nodes.py`: node 1 stores the incoming tick instead of reading a dataset; the LLM report also mentions the +20 forecast.
* `config.py`: paths come from `settings.py`; time settings are in ticks (12 ticks = 1 real minute).

Run: `python -m agent.run --help` (from the project root).
