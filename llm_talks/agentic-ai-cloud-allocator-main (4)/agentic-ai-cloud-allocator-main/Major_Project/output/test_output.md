# AegisCloud: test results (Day 1)

Date: 24 Oct 2026. App: `app_62`. Machine: your Windows PC. Replay starts at minute 14112 (70% point of the data).

## Summary

| # | Command | Result |
|---|---|---|
| 1 | `python test/llm_tester.py --provider fake` | OK (both tests) |
| 2 | `python test/llm_tester.py --provider gemini` | OK (both tests) |
| 3 | `python test/graph_tester.py` | **28 passed, 0 failed** |
| 4 | `python test/graph_tester.py --provider gemini` | **29 passed, 0 failed** |
| 5 | `python test/graph_tester.py --provider gemini --send-email` | **30 passed, 0 failed**, real email received |
| 6 | `python agent/run.py --minutes 120 --tick 0` | 120 minutes, no crash, 0 alerts, 0 minutes above capacity |
| 7 | `python agent/run.py --provider gemini --timer 3 --minutes 60 --quiet` | 54 minutes (stopped with Ctrl+C), 17 Gemini calls, no LLM errors, **1 false alert** |

**Verdict:** the pipeline works end to end with the real LSTM, real data, real Gemini and real Gmail. The tests prove the wiring. They do not prove that the LLM's decisions are good, and run 7 showed three quality problems (see `fixes_to_do.md`).

---

## 1. LLM layer, fake provider

Provider `fake`, no internet.

| Test | Result |
|---|---|
| Replica decision (traffic 1500/min, 5 replicas of 223/min) | `scale_up` to 8 replicas, answered in 0.0 s. `RESULT: OK` |
| Alert email text | Plain-code email built. `RESULT: OK` |

## 2. LLM layer, Gemini

| Item | Value |
|---|---|
| Model | `gemini-3.5-flash-lite` |
| Fallback model | `gemini-3.8-flash` |
| API key | found in `.env` |

| Test | Result |
|---|---|
| Replica decision | `scale_up` to 8 replicas in 2.4 s. Reason: traffic exceeds capacity and approaches the 1560 forecast. `RESULT: OK` |
| Alert email text | Written by Gemini in 3.0 s. Subject: `[URGENT] Autoscaler at maximum replicas with traffic exceeding capacity for app_62`. `RESULT: OK` |

## 3. Whole graph, fake LLM (28 / 28)

12 minutes, minutes 14112 to 14123.

| Minute | Mode | Replicas | Note |
|---|---|---|---|
| 14112, 14113 | auto | 6 -> 6 | |
| 14114 | **unusual** | 6 -> 6 | forced: "near capacity: 1144/min against 1340/min capacity" |
| 14115, 14116 | auto | 6 -> 6 | |
| 14117 | timer | 6 -> 6 | |
| 14118, 14119 | auto | 6 -> 6 | |
| 14120 | timer | **6 -> 7** | forced alert (`alert_human` ran) |
| 14121, 14122 | auto | 7 -> 7 | |
| 14123 | timer | 7 -> 7 | |

Nodes: `store_prediction`, `trigger_check`, `script_creator`, `apply_and_log` ran 12 times each. `llm_unusual` 1, `llm_timer` 3, `auto_scale` 8, `alert_human` 1.
`actions.csv` had 4 rows (4 LLM calls), as expected. Alert saved as `alert_14120.txt`.

## 4. Whole graph, Gemini (29 / 29)

Same path as run 3, with real Gemini. All 4 LLM calls succeeded and Gemini wrote the email text.

> **Unplanned alert:** `alert_human` ran **2 times**, at minute 14117 **and** at the forced minute 14120. Nobody forced the alert at 14117. Most likely Gemini set `escalate: true` on a normal minute. The test still passed because it only checks that an alert happened where one was forced. Read `test/output/alerts/alert_14117.txt` (if it still exists) to confirm. This did not repeat in run 5, so Gemini's answers vary between runs even at temperature 0.

## 5. Whole graph, Gemini, real email (30 / 30)

| Item | Result |
|---|---|
| Checks | 30 passed, 0 failed |
| Email status | `sent to meunderworldkaraja@gmail.com` |
| Subject received | `[URGENT] Autoscaler Alert: App app_62 Test Alert Triggered` |
| Sender account | the account in `EMAIL_SENDER` |
| Attachments | `last_hour_predictions.csv`, `last_actions.csv` (both arrived) |
| Alert count | 1 (only the forced one) |

**Email content check** (minute 14120):

| Statement in the email | Correct? |
|---|---|
| Traffic 1180, forecast 1240, utilisation 75% | Yes (1180 / (7 x 223) = 75.6%) |
| Last 9 minutes: min 1042, max 1180 | Yes |
| Capacity 223/min per replica, 7 replicas, limits 1-21 | Yes |
| Scaled up 6 -> 7 at minute 14120, held at 6 at 14114 and 14117 | Yes |

The email followed the 4-part structure (what is wrong, evidence, what was done, next steps) and used only numbers from the report.

## 6. Agent run, fake LLM, 120 minutes

Minutes 14112 to 14231.

| Metric | Value |
|---|---|
| LLM calls (fake, timer mode) | 23 |
| Replica changes | 9 |
| Alerts | 0 |
| Replica-minutes (cost) | 817 |
| Minutes above capacity | 0 (new replicas assumed instant) |
| Replicas range | 6 to 8 |
| Peak traffic | 1444/min at minute 14220 (needed 8 replicas) |

Replica changes: 14120 (6->7), 14140 (7->6), 14149 (6->7), 14170 (7->6), 14175 (6->7), 14200 (7->6), 14209 (6->7), 14220 (7->8), 14230 (8->6).

Checks that behaved correctly:
- Scale-up happened the same minute demand rose. Scale-down waited until the last 10 minutes were all lower.
- The drop 8 -> 6 at minute 14230 is exactly the guardrail limit (at most 25% removed).
- The "unusual" mode never fired, because traffic stayed below 95% of capacity.

## 7. Agent run, Gemini, timer every 3 minutes (stopped at 54 minutes)

| Metric | Value |
|---|---|
| Minutes replayed | 54 (stopped with Ctrl+C) |
| LLM calls (Gemini, timer mode) | 17 |
| LLM errors | 0 |
| Replica changes | 5 |
| Alerts | **1 (false alert)** |
| Replica-minutes (cost) | 361 |
| Minutes above capacity | 0 |

Replica changes: 14120 (6->7, auto), 14140 (7->6, auto), 14145 (6->7, Gemini), 14146 (7->6, auto), 14149 (6->7, auto).

### What went wrong in this run

| # | Minute | What happened | Why it matters |
|---|---|---|---|
| A | 14130 | Gemini set `escalate: true`, but its own reason said "current replicas are sufficient for now". Traffic 1288 vs capacity 1561 (82%). An alert was raised. | A false alert wakes a human for nothing |
| B | 14115 | Reason says traffic "exceeds safe capacity for 6 replicas", but 1174 x 1.1 = 1291 fits in 6 x 223 = 1338. It held at 6 (the right action, wrong reason). | The explanations cannot be trusted yet |
| C | 14118 | Reason begins "Wait, let's calculate:", so the model is thinking out loud in the reason field. | Messy audit log |
| D | 14145 -> 14146 | Gemini scaled 6 -> 7. The next minute `auto_scale` scaled 7 -> 6. | Flapping: the LLM and the formula undo each other |

### Fake LLM vs Gemini, same first 54 minutes

| | Fake LLM | Gemini |
|---|---|---|
| Replica changes | 3 | 5 |
| Alerts | 0 | 1 |

The two extra changes in the Gemini run are the flapping pair in D. On this smooth app the real LLM added noise, not value. Whether it helps on harder traffic (for example `app_185`) is not measured yet.

---

## Saved real run in the zip (`agent/data/`, earlier run)

134 minutes (14112 to 14245), real Gemini: 40 logged decisions (26 timer, 14 auto), no unusual events. The LLM held 22 times and scaled up 4 times. It never scaled down. The formula made all 8 scale-downs. Replicas stayed between 6 and 8.

## What is still not tested

- Mistral with the real API
- The "LLM failed 2 times in a row" alert (needs `llm_failures` declared in `state.py`)
- A real traffic spike or an app that really overloads (`app_185`)
- Real scaling of containers (`set_replicas()` is a placeholder)
- Anything under load, in Docker, or with Prometheus and Grafana