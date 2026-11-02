# AegisCloud Learning Notes and Agent Improvements

## 1. Project Study

The project ZIP was reviewed to prepare understandable technical notes for independent learning.

The review covered:
- README and configuration files.
- Agent code and LangGraph structure.
- LLM integration and email functionality.
- Predictor and training notebook.
- Test scripts and existing documentation.
- Research PDF titles and abstracts.

The six research PDFs were reviewed only at the abstract/title-page level.

The dataset was missing from the ZIP and required downloading through gdown or supplying it manually. API keys and email credentials had to be configured locally.

## 2. Learning Documentation

A study document called **AegisCloud: Notebook Notes and Run Guide** was prepared.

It included five diagrams:
1. Project folder structure.
2. Complete system data flow.
3. Eight-node LangGraph architecture.
4. Agent operating-mode selection.
5. Forecasting pipeline.

The purpose was to explain every folder, file, input, output and major decision in simple English.

## 3. Seven Priority Fixes

A fixed project ZIP, `agentic-ai-cloud-allocator-fixed.zip`, was prepared with seven P1 fixes:

| # | Improvement | Main Files |
|---|---|---|
| 1 | Added `llm_failures` to the state | state.py |
| 2 | Restricted false escalations using a load threshold | llm.py, nodes.py, config.py |
| 3 | Added a 10-minute scale-down waiting period after scale-up | state.py, nodes.py |
| 4 | Improved LLM reasons and supplied the formula's replica recommendation | llm.py, nodes.py |
| 5 | Removed duplicate `force_alert` logic | nodes.py |
| 6 | Added SMTP port 587 STARTTLS fallback | mailer.py |
| 7 | Corrected `.gitignore` and excluded generated outputs | .gitignore |

The logic-level checks passed 12/12.

However, the LSTM, Gemini, mailer fallback and complete graph tester were not executed in that environment.

## 4. Understanding Agent Modes and Alerts

An important distinction was established:

**Unusual events do not automatically send emails.**

Unusual mode triggers an LLM evaluation. Email alerts are generated only under separate conditions:

- The LLM requests escalation and the load condition permits it.
- The LLM fails repeatedly.
- Traffic remains above capacity for the configured number of consecutive minutes.
- The system reaches maximum replicas while remaining overloaded.

A 30-minute alert cooldown was also present.

For testing all agent paths quickly, `test/graph_tester.py --provider gemini --send-email` forces unusual, timer, automatic and alert events over a short replay.

For natural unusual events, app_185 was recommended because of its bursty traffic behaviour.

## 5. app_185 Investigation

The app_185 replay exposed an important problem:
- Forecast error frequently exceeded 50%.
- Unusual mode was triggered repeatedly.
- Several overload minutes occurred, but spikes lasted only 1–4 minutes.
- The agent did not reach its maximum replica limit.
- Consequently, the existing alert rules did not generate emails naturally.

The scaling algorithm also reacted excessively after spikes because it used the maximum demand over the previous 10 minutes for scale-up decisions.

This caused unnecessary replica increases even after traffic had returned to low levels.

The LLM and automatic scaling formula also sometimes worked against each other.

## 6. Proposed Further Changes

The final discussion proposed:
- Reducing the consecutive overload threshold using `ALERT_MISS_MINUTES`.
- Scaling up using current and forecast demand rather than historical maximum demand.
- Keeping the historical 10-minute window for scale-down decisions.
- Correcting misleading scaling explanations.

These final proposed changes were not confirmed as implemented in this conversation.

## 7. Main Conclusion

The project has an operational agent structure with forecasting, decision-making, safety controls and email alerts.

However, app_185 demonstrated that forecasting errors, sudden bursts and inappropriate scaling logic can affect resource efficiency.

Further improvements should focus on scaling stability, forecasting reliability and alert conditions.
