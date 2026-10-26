# AegisCloud: Notebook Notes in Simple English

Made 26 Oct 2026 from the project zip. Short points, so you can copy them into your notebook.

## 1. What is AegisCloud?

- AegisCloud is a smart **autoscaler**. It decides how many copies of an app should run, every minute.
- A copy of the app is called a **replica**.
- Analogy: a restaurant. Customers = traffic. Cooks = replicas. Each cook can serve a fixed number of customers per minute = **capacity**.
- Too few cooks: customers wait (app is slow). Too many cooks: you pay for people doing nothing (waste of money).
- Normal autoscalers react late (for example: CPU above 70%). A new replica needs about **2 minutes** to start, so AegisCloud **predicts 10 minutes ahead**.
- Main idea to write down: cheap plain code does most of the work, the LLM helps only sometimes, and a safety rule (guardrail) checks every decision.

### Words to remember

| Word | Simple meaning |
| --- | --- |
| Replica | One running copy of the app (one cook) |
| Capacity | Requests per minute one replica can handle |
| Traffic | Requests coming in per minute |
| Forecast | Traffic predicted for 10 minutes later |
| LSTM | A small neural network that learns patterns in a time series |
| WAPE | Total error divided by total traffic. Lower is better |
| LLM | The AI (Gemini or Mistral) that reads a report and decides |
| Guardrail | Plain code that limits every decision |
| Node | One step (one Python function) in the LangGraph |
| State | The shared dictionary passed from node to node |
| Hold | Keep the same number of replicas |
| Escalate | Ask a human for help |

## 2. Folder map

The project has these folders. Draw the tree in your notebook.

| Folder or file | One-line job |
| --- | --- |
| README.md | Overview of the whole project |
| agent/ | The LangGraph agent (the brain) |
| notebook/ | Forecaster work: the notebook, predict.py, notes |
| models/ | 6 saved LSTM models (one per app) |
| test/ | Two test scripts |
| learning/ | A beginner guide to the agent |
| fixes/ | List of 14 fixes to do |
| output/ | Results of the Day 1 test runs |
| Reaserch\_Papers/ | 6 research PDFs |
| requirements.txt | List of libraries to install |
| .gitignore | Files Git must not upload |
| LICENSE | The project licence |

&#91;embedded content: folder tree · 8 folders + top-level files\]

Draw this tree first. The highlighted folder, agent/, holds all the code that runs.

Not in the zip: the dataset (it is downloaded automatically on the first run), agent/data/ (created on every run), and agent/.env (you create it).

## 3. Big picture: how data moves

- The **dataset** has traffic per minute for 318 apps (Azure Functions, 14 days = 20,160 minutes).
- We pick one app (app\_62). The **LSTM model** for that app predicts traffic 10 minutes ahead.
- **run.py** replays the data one row per minute. Each row = one pass through the **graph**.
- The graph writes **CSV files**, may call the **LLM**, and may send an **email**.

&#91;embedded content: data flow · inputs, agent, outputs\]

The agent is the middle box. It reads the forecast, sometimes asks the LLM, and writes files.

## 4. One minute inside the graph

One pass through the graph = one minute. There are 8 nodes.

| # | Node | What it does | LLM? |
| --- | --- | --- | --- |
| 1 | store\_prediction | Gets this minute's traffic, runs the LSTM, saves one row in predictions.csv | No |
| 2 | trigger\_check | Chooses the mode: unusual, timer or auto | No |
| 3 | script\_creator | Writes a text report of the last 10 minutes | No |
| 4 | llm\_unusual | LLM decides, because something unusual happened | Yes |
| 5 | llm\_timer | LLM decides, because the timer is due | Yes |
| 6 | auto\_scale | Plain formula decides | No |
| 7 | apply\_and\_log | Guardrail, set replicas, write actions.csv, check if an alert is needed | No |
| 8 | alert\_human | Only if something is wrong: LLM writes an urgent email | Yes |

Only **two forks** exist in the graph: route\_mode (which of the 3 branches) and route\_alert (alert or end).

&#91;embedded content: graph flow · 8 nodes, 2 forks\]

Read it top to bottom: three steps, one of three branches, then the guardrail, then an alert only if needed.

## 5. The three modes

- Priority: **unusual > timer > auto**.
- **unusual** (LLM called) happens when any one of these is true:
  - the forecast jumps more than 30% compared with the last forecast (and is above 50% of capacity), or
  - the forecast or traffic is above 95% of capacity, or
  - the forecast error over the last 5 minutes is above 50%.
  - After an unusual call, wait 3 minutes (cooldown) before the next one.
- **timer** (LLM called): every 5 minutes since the last LLM check. An unusual call resets the timer.
- **auto** (no LLM): all other minutes.

&#91;embedded content: mode choice · 2 decisions, 3 outcomes\]

The tinted boxes are the only two modes that call the LLM.

### The auto formula

- demand = the highest of (traffic, forecast) in the last 10 rows
- replicas = ceil( demand x 1.10 / capacity ), kept between min and max
- The 1.10 means 10% spare room.
- Scale **up** is immediate. Scale **down** happens only when all last 10 minutes needed fewer replicas. This stops the count from jumping up and down.

## 6. The guardrail

The guardrail limits **every** decision (LLM or formula). Three steps:

1. Keep replicas between min and max.
2. At most **double** in one step (but +2 is always allowed).
3. At most remove **25%** in one step (but -1 is always allowed).

Examples to write:

- 5 replicas, wants 20, max 11 -> answer **10**
- 8 replicas, wants 1 -> answer **6**
- 4 replicas, wants 30, max 11 -> answer **8**

## 7. Alerts

An urgent email is sent when any one of these is true:

1. The LLM sets escalate = true (scaling cannot fix the problem).
2. The LLM failed 2 times in a row.
3. Traffic was above capacity for 5 minutes in a row.
4. Replicas are at the maximum and traffic is still above capacity.

Extra points:

- 30 minutes cooldown between two alerts (no spam).
- The LLM writes the email using only numbers from the last hour report.
- If the LLM fails, a plain-code email is used, so an alert is never lost.
- Two CSV files are attached: last\_hour\_predictions.csv and last\_actions.csv.
- The email is always saved in agent/data/alerts/ even if sending is off.

## 8. The agent/ folder, file by file

### config.py (the control panel)

- Holds every setting. No logic. Change a number here and the whole agent changes.
- Reads secrets from agent/.env with dotenv.
- Important settings: APP = app\_62, START\_FRACTION = 0.7, TIMER\_EVERY = 5, MARGIN = 0.10, SPIKE\_RATIO = 1.3, NEAR\_CAPACITY = 0.95, ERROR\_LIMIT = 0.5, UNUSUAL\_COOLDOWN = 3, DOWN\_WAIT = 10, ALERT\_COOLDOWN = 30, LLM\_PROVIDER = fake, LLM\_TIMEOUT = 30, LLM\_RETRIES = 2.
- Also holds the three mode names, so a spelling mistake gives an error instead of failing silently.

### state.py (the shared notebook)

- AgentState is a TypedDict: the list of keys allowed in the state.
- Two groups of keys. **Carried keys** stay from minute to minute (replicas, capacity, max\_replicas, the timers). **Per-minute keys** are written again every minute (forecast, mode, decision and so on).
- new\_state() builds the first state.
- **Golden rule:** a node can only save keys that are declared here. LangGraph silently drops other keys.

### graph.py (the wiring)

- Adds the 8 nodes and joins them with arrows. No calculations.
- add\_edge = always go to the same next box. add\_conditional\_edges = a fork, a small function chooses the road.
- compile() makes the graph runnable.

### nodes.py (the heart)

- Helpers: replicas\_for (the formula), reset\_files (empty CSVs at start), append\_row (add a CSV row), read\_predictions.
- **Feed class:** loads the dataset and the LSTM once. It works out the starting numbers:
  - start position = 70% of the data = minute 14112
  - capacity = average training traffic divided by 5
  - max replicas = the larger of 10 and (highest training traffic x 1.5 / capacity)
  - starting replicas = enough for the first traffic value
- The 8 nodes listed in section 4, plus guardrail(), set\_replicas() and alert\_reason\_for().
- **set\_replicas() is an empty placeholder.** Later, Docker or Kubernetes will be connected here.
- store\_prediction is built by make\_store\_prediction(feed), a function that returns a function (a closure), so the node can remember the feed.

### llm.py (the only file that talks to an AI)

- Two public functions: ask\_llm() for a replica decision and write\_alert\_email() for the urgent email.
- Three providers: **fake** (a free formula, for testing), **gemini**, **mistral**.
- The system prompt tells the LLM its job and rules (keep 10% spare room, trust actual traffic when forecasts are bad, prefer hold, escalate only when scaling cannot help). It must answer with one JSON object.
- post\_json: sends the request. Busy errors (429, 500, 502, 503, 504) are retried twice, waiting 2 s then 4 s. Real errors (wrong key, wrong model) stop at once.
- call\_gemini: tries the main model, then a fallback model.
- parse\_reply: cuts the JSON out of the text, rejects bad values, clamps replicas to min and max, and works out the action from the numbers.
- If anything fails, the answer is **hold** with an error flag. The agent never crashes.

### mailer.py (the post office)

- send\_email(subject, body, attachments) uses SMTP over SSL on port 465 (Gmail).
- Needs a Gmail **app password**, written without spaces.
- It never raises an error. It returns (True, message) or (False, reason).
- Known gap: config.py has a second port (587) but mailer.py does not use it yet.

### run.py (the start button)

- Reads options, checks the setup, loads the data and model, builds the graph, then loops: set pos, call app.invoke(state), print one line, wait for the tick.
- Ctrl+C stops safely and still prints the summary.
- Imports graph inside main() so a wrong option fails fast, before the slow torch import.

| Option | Meaning |
| --- | --- |
| --minutes N | Replay N minutes |
| --tick S | Seconds between minutes (0 = as fast as possible) |
| --timer N | Minutes between normal LLM checks |
| --app app\_1 | Which app to replay |
| --provider | fake, gemini or mistral |
| --email | Really send alert emails |
| --quiet | Print only important minutes |

### Small files in agent/

- .env.example: a template of the secret settings (Gemini key, Mistral key, email sender, password, receiver). Copy it to .env.
- step\_based\_working\_readme.md: the agent explained step by step, with the test list.
- **init**.py: empty file.

## 9. The other folders

### notebook/

- **lstm\_model.ipynb** (written for Google Colab). It checks the data, draws 5 pictures, splits 70/30 by time, compares 7 methods, trains the LSTMs and saves them.
- **predict.py:** loads a saved LSTM and predicts 10 minutes ahead. Main parts:
  - find\_csv / find\_model / list\_apps: find the files by themselves
  - LSTMForecaster: the model class (must match the notebook)
  - load\_data: reads the CSV (downloads it with gdown if missing)
  - load\_model: loads the .pt file
  - predict\_at: does the real prediction
  - backtest: scores the model on the 30% test part
- **notebook\_readme.md:** the forecaster results in words.

### models/

- 6 files: app\_1.pt, app\_62.pt, app\_123.pt, app\_185.pt, app\_248.pt, app\_318.pt, plus meta.json (method lstm, H = 10, W = 60).
- Each .pt file has the weights plus mu, sd, dsd (scaling numbers), n\_static, W and H.
- One model per app. A new app needs new training.

### test/

- **llm\_tester.py:** tests llm.py alone. Test 1: replica decision for an overloaded app. Test 2: alert email text. Saves nothing and sends nothing.
- **graph\_tester.py:** runs the real graph for 12 minutes and prints PASS or FAIL for about 28 to 30 checks. It forces an unusual event at position 2, timer calls every 3 minutes and a forced alert at position 8. It writes only to test/output/.
- Checks cover: every node ran, correct node order, the three modes, predictions.csv shape, the report text, replicas carry over and obey the guardrail, actions.csv rows, LLM answers valid, alert saved and (optionally) sent.

### learning/, fixes/, output/

- **learning/learn\_agent.md:** the agent explained for beginners, with a worked example and 8 questions.
- **fixes/fix\_to\_do.md:** 14 fixes. P1 (7 fixes) before Prometheus, P2 later, P3 is the plan for Days 2 to 6.
- **output/test\_output.md:** the Day 1 test results (7 runs).

### Reaserch\_Papers/ (6 PDFs)

- DeepRM: resource management with deep reinforcement learning (MIT and Microsoft, 2016)
- Borg: the Next Generation (Google cluster)
- Pervasive Auto-Scaling Method (deep RL for cloud auto-scaling)
- Agentic AI Frameworks for Autonomous Cloud Resource Management (SSRN, 2026)
- MOYA: LLM multi-agent framework for autonomous CloudOps (ICSE 2025)
- ML-based cloud resource allocation: a comparative review (Frontiers, 2025)

## 10. The forecaster in simple words

- Task: at minute t, predict traffic at minute t + 10.
- Data is split by time: first 70% to train, last 30% to test. No shuffling.
- LSTM input: the last 60 minutes (log scale) plus 4 extra numbers: yesterday's value for the target minute, yesterday's change, and sin and cos of the time of day.
- The model predicts the **change** in log traffic. predict\_at turns it back into real requests with expm1 and clips at 0.
- It needs one full day (1440 minutes) of history, so the first usable position is 1440.

&#91;embedded content: forecaster pipeline · 6 steps\]

The model predicts how much traffic will change, then the last step turns that into a real forecast.

| Method | WAPE (lower is better) |
| --- | --- |
| lstm | 0.189 |
| gbm | 0.191 |
| gbm\_q90 | 0.308 |
| moving\_avg | 0.356 |
| yesterday | 0.359 |
| naive | 0.361 |
| lstm\_q90 | 0.472 |

- LSTM and GBM are a tie.
- On smooth apps a simple moving average can win.
- app\_185 is very bursty: every method has WAPE near 1.0.
- under\_10pct = share of minutes predicted more than 10% too low (risk: slow app). over\_10pct = share predicted more than 10% too high (risk: wasted money).

## 11. Output files and how to read them

| File | Columns | Meaning |
| --- | --- | --- |
| predictions.csv | minute, traffic\_now, forecast, forecast\_for, replicas | One row every minute |
| actions.csv | minute, mode, reason, traffic\_now, forecast, replicas\_before, proposed, applied, action, decision\_reason | One row for every LLM call or replica change. proposed = what was asked, applied = after guardrail |
| alerts/alert\_\<minute>.txt | Subject, Status, body | Every urgent email |

One printed line from run.py:

`minute | traffic | forecast | replicas before -> after | mode | reason`

Summary at the end: minutes replayed, LLM calls, replica changes, alerts, **replica-minutes** (cost: sum of replicas over all minutes) and **minutes above capacity** (too optimistic for now, because new replicas start instantly in the replay).

## 12. How to run (from the project root)

1. Install: `pip install -r requirements.txt`
2. Copy agent/.env.example to agent/.env and fill your keys.
3. Forecaster check: `python notebook/predict.py --app app_62 --backtest` (expect WAPE about 0.027)
4. LLM layer: `python test/llm_tester.py --provider fake`, then `--provider gemini`
5. Whole graph: `python test/graph_tester.py` (28 passed), with `--provider gemini` (29), with `--send-email` (30)
6. Run the agent: `python agent/run.py --minutes 120 --tick 0`
7. With Gemini: `python agent/run.py --provider gemini --timer 3 --minutes 60 --quiet`

## 13. Done till now and not done

| Part | Status |
| --- | --- |
| Data exploration, baselines, GBM and LSTM forecaster | Done |
| LangGraph agent with 8 nodes, guardrail, logging, alert email | Done |
| Real run with real LSTM, data, Gemini, retries and fallback model | Done (one app, one replay) |
| Test scripts for LLM layer and whole graph | Done |
| Real Gmail test email | Done |
| Mistral with the real API | Not run |
| 2-LLM-failures alert | Broken until a state.py fix |
| Real traffic spike or overloaded app test | Not done |
| Prometheus and Grafana | To do |
| Real set\_replicas() with Docker or Kubernetes | To do |
| Simulator and comparison with rule-based autoscalers | To do |
| Unit tests, CI, demo video | To do |

## 14. Known problems (write these too)

1. llm\_failures is not declared in state.py, so the 2-failures alert never fires. Fix: add one line.
2. Gemini sometimes sets escalate = true when nothing is wrong (a false alert at minute 14130).
3. Flapping: the LLM scales 6 -> 7 and the formula scales back 7 -> 6 the next minute.
4. The LLM reasons are sometimes messy or have wrong arithmetic.
5. nodes.py has the force\_alert check twice, and a comment names an option that does not exist.
6. The second email port (587) is not used.
7. .gitignore has a broken line and does not ignore agent/data/.
8. The graph reads predictions.csv many times per minute. Fine for a replay, not for a live loop.
9. On the smooth app\_62, Gemini added noise, not value. We still do not know if it helps on hard traffic.

## 15. Next step: Prometheus and Grafana

- Plan metrics: traffic, forecast, replicas, mode, LLM calls, LLM errors, alerts.
- Suggested place to add them: in run.py, right after app.invoke(state), where all values are in the state.
- Use gauges for traffic, forecast and replicas. Use counters for LLM calls, errors, alerts and scale events.
- Use --tick 1 or more, so Prometheus can see each minute.
- Do the P1 fixes first.

## 16. Quick revision sheet

- Replicas needed = ceil( demand x 1.10 / capacity )
- Capacity per replica = average training traffic / 5
- Max up in one step = max( current + 2, current x 2 )
- Max down in one step = max( 1, 25% of current )
- Unusual if: forecast jump over 30%, or above 95% of capacity, or 5-minute error over 50%
- Timer every 5 minutes. Unusual cooldown 3 minutes. Alert cooldown 30 minutes.
- Forecast looks 10 minutes ahead. Model reads the last 60 minutes. Needs 1440 minutes of history.
- Replay starts at minute 14112 (70% of 20,160).
