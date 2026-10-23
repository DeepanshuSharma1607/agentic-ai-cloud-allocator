# Explaining the AegisCloud agent, file by file

## The story first (read this before any code)

Imagine a **restaurant**. Customers arrive every minute. You have some **cooks** (these are *replicas*, copies of your app). Each cook can serve a fixed number of customers per minute (this is the *capacity*).

- Too few cooks: customers wait, which is bad (the app gets slow).
- Too many cooks: you pay for people standing around (wasted money).

Every minute, our program does this:

1. **Predicts** how many customers will arrive 10 minutes from now. This is the *forecast*, made by a small AI model called an LSTM that your teammate already trained.
2. **Writes** the prediction in a notebook (a CSV file).
3. **Decides** if anything unusual is happening.
4. **Decides** how many cooks we need. Usually a simple formula does this. Sometimes it asks an expert, the **LLM** (an AI like Gemini). The expert costs money, so we call it rarely.
5. **Checks the decision** with a safety rule ("never hire more than double at once").
6. If something is really wrong, **emails the owner** with a report.

Every file below is one part of this story.

---

## A mini dictionary of the libraries

You know Python. A **library** is code someone else wrote that you borrow with `import`.

| Library | What it is, in simple words | Where we use it |
|---|---|---|
| `os` | Talks to your computer. We use it to read secret settings. | config.py |
| `pathlib` | Handles file and folder locations without mistakes | config.py |
| `dotenv` | Reads a secret file (`.env`) so passwords are not inside the code | config.py |
| `typing` | Lets us describe what a dictionary should contain | state.py |
| `json` | Turns text like `{"a": 1}` into a Python dictionary, and back | llm.py |
| `math` | Maths helpers like `ceil` (round up) | llm.py, nodes.py |
| `requests` | Sends a message to a website or online service and reads the reply | llm.py |
| `csv` | Writes rows into a CSV file (a plain-text table) | nodes.py |
| `pandas` | Reads a CSV into a smart table (called a *DataFrame*) | nodes.py |
| `numpy` | Fast maths on many numbers at once | nodes.py |
| `sys` | Info about Python itself, for example where it looks for files | nodes.py, run.py |
| `smtplib` | Python's built-in "post office" that sends email | mailer.py |
| `email.message` | Builds an email: subject, body, attachments | mailer.py |
| `langgraph` | Lets us draw a flow of steps (boxes and arrows) and run it | graph.py |
| `argparse` | Lets you type options after the command, like `--minutes 120` | run.py |
| `time` | Waiting and clocks | run.py |
| `torch` | The AI library that runs the LSTM (used inside `predict.py`) | notebook/predict.py |

---

## 1. `config.py`: the control panel

**Job:** it holds every number and setting. It has no logic. Want the timer to be 3 minutes instead of 5? Change one line here and nothing else.

**Part 1: finding folders**

```python
AGENT_DIR = Path(__file__).resolve().parent
NOTEBOOK_DIR = AGENT_DIR.parent / "notebook"
```
- `__file__` is the location of this very file.
- `.parent` means "the folder that contains it".
- The `/` joins path pieces. `AGENT_DIR.parent / "notebook"` means "go up one folder, then into `notebook`".

This is why the `agent` folder must sit next to the `notebook` folder.

**Part 2: secrets**

```python
load_dotenv(AGENT_DIR / ".env")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
```
`load_dotenv` reads the `.env` file and loads its lines as hidden settings. `os.getenv` reads one of them, and `""` is the default if it is missing. This keeps passwords out of the code, so you can share the code safely.

**Part 3: the settings**

- **CAPITAL_LETTERS** is a Python habit meaning "this is a constant, don't change it while running".
- `None` here means "work it out automatically". For example `CAPACITY_PER_REPLICA = None` means "calculate it from the data".
- Examples: `MARGIN = 0.10` keeps 10% spare room. `TIMER_EVERY = 5` means ask the LLM every 5 minutes. `LLM_PROVIDER = "fake"` means use the pretend AI first.
- The three modes are stored as constants (`MODE_UNUSUAL = "unusual"`). If you mistype `cfg.MODE_UNUSAL` later, Python shouts at you. A mistyped plain string `"unusal"` would silently break things.

**Remember:** one file, all the dials.

---

## 2. `state.py`: the shared notebook

Think of a notebook passed from student to student along a row. Each student reads it, writes a few new lines, and passes it on. In our program the students are the **nodes** and the notebook is the **state**.

```python
class AgentState(TypedDict, total=False):
    replicas: int
    traffic_now: float
    forecast: float
    mode: str
    ...
```
- A **dictionary** is `{"replicas": 5, "forecast": 900.0}`: names with values.
- `TypedDict` says which names are allowed and what type each value has. LangGraph needs this list to know what the notebook can hold.
- `total=False` means "not every page must be filled at the start". `forecast` is empty until the first node fills it.

The keys come in two groups:
- **carried keys** like `replicas`, `capacity` and the timers. They survive from one minute to the next.
- **per-minute keys** like `forecast` and `mode`. They are rewritten every minute.

```python
def new_state(capacity, max_replicas, replicas, start_minute):
    return AgentState(replicas=int(replicas), ..., last_unusual_minute=-10 ** 9)
```
This builds the very first notebook. `-10 ** 9` is a huge negative number that means "this never happened". Without it, the cooldown would block the first alert. We set `last_timer_minute` to the start minute, so the first timer check comes 5 minutes after the start, not instantly.

---

## 3. `llm.py`: the only file that talks to an AI

**Job:** `ask_llm(...)` gives a replica decision. `write_alert_email(...)` gives an email. Everything else about AIs is hidden in here.

**Idea 1: three "AIs" behind one door.** `LLM_PROVIDER` in config picks one:
- `fake`: a pretend AI that uses a formula. It is free and perfect for testing.
- `gemini` and `mistral`: the real ones.

**Idea 2: the fake AI formula**

```python
need = math.ceil(demand * (1 + cfg.MARGIN) / facts["capacity"])
```
Example: demand 900, margin 0.1, capacity 200. Then 900 × 1.1 / 200 = 4.95, and `ceil` rounds **up** to 5 cooks. We round up because 4.95 cooks does not exist, and too few is worse than one extra.

**Idea 3: talking to a real AI over the internet.** A real AI lives on a server. We send it a message with `requests.post` and read the answer:

```python
r = requests.post(url, json=body, headers={...}, timeout=cfg.LLM_TIMEOUT)
r.raise_for_status()
return r.json()["candidates"][0]["content"]["parts"][0]["text"]
```
- `json=body` is the message (a dictionary).
- `headers` carries our secret key, like showing an ID card.
- `timeout` means "give up after 30 seconds".
- `raise_for_status()` turns a server error into a Python error.
- `r.json()` turns the reply into a dictionary. The long `["candidates"][0]...` chain is us digging down to the text.

**Idea 4: never trust the AI's answer.** AIs sometimes reply with extra words, wrong types or nonsense. `parse_reply` cleans it:

```python
start, end = text.find("{"), text.rfind("}")
data = json.loads(text[start:end + 1])
```
It finds the first `{` and last `}`, cuts out just that part, and converts it with `json.loads`. Then it checks:
- Is `replicas` a real number? We specially reject `True` because in Python `True` counts as the number 1.
- It forces the number between min and max replicas.
- It **recomputes** the action (`scale_up`, `scale_down` or `hold`) from the numbers, so the action can never contradict the number.

**Idea 5: fail safe.**

```python
except Exception as e:
    return {"action": "hold", "replicas": facts["replicas"], ...}
```
If anything goes wrong (no internet, bad key, junk reply), the program does the boring safe thing: **hold**, keep the same number of cooks. A broken AI never crashes the system.

**`write_alert_email`** does the same job for the urgent email. If the AI fails, `template_email` builds a plain email with code, so an alert is never lost.

---

## 4. `mailer.py`: the post office

```python
msg = EmailMessage()
msg["Subject"] = subject
msg.set_content(body)
msg.add_attachment(text.encode("utf-8"), maintype="text", subtype="csv", filename=name)
with smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=...) as server:
    server.login(cfg.EMAIL_SENDER, cfg.EMAIL_PASSWORD)
    server.send_message(msg)
```
- `EmailMessage` is like an empty letter. We fill in subject, sender, receiver, body and attach CSV files.
- **SMTP** is the language email servers speak. `SMTP_SSL` makes the connection secure.
- `with ... as server:` opens the connection and **closes it automatically** when the block ends, even if there was an error.
- `.encode("utf-8")` turns text into bytes, which attachments need.
- The password must be a Gmail **app password**, a special password for programs.

The function returns a pair like `(True, "sent to ...")` or `(False, "reason")`. It never raises an error, because a broken email must not stop the autoscaler.

---

## 5. `nodes.py`: the eight workers (the heart)

A **node** is just a function with one rule: it receives the `state` and returns a small dictionary with **only the things it changed**.

### The helpers at the top

- `replicas_for(demand, capacity, min, max)`: the "how many cooks" formula, then forced between min and max.
- `reset_files()`: deletes old CSV files so every run starts clean.
- `append_row(...)`: adds one row to a CSV with `csv.DictWriter`. It writes the header (column names) only if the file is new.
- `read_predictions()`: `pd.read_csv(...)` loads the CSV into a pandas table.
- `sys.path.append(...)`: Python only looks in certain folders for `import`. This line adds the `notebook` folder so `from predict import ...` can find your teammate's file.

### The `Feed` class

A **class** is a blueprint that bundles data and functions together. When we write `feed = Feed()`, Python runs `__init__` once, and that function loads the dataset and the LSTM model. `self` means "this particular object".

```python
self.capacity = cfg.CAPACITY_PER_REPLICA or max(1.0, train.mean() / cfg.AVG_REPLICAS)
```
The `or` trick means: use the config number if it is set. If it is `None`, calculate it. The calculation says "the average training traffic should need 5 cooks".

### Node 1: `store_prediction`

It gets this minute's real traffic, asks the model for the forecast 10 minutes ahead, and adds a row to `predictions.csv`. It is written as a function that **returns a function** (`make_store_prediction(feed)` gives back `store_prediction`). LangGraph calls nodes with only the state, so the node needs a way to "remember" `feed`. This pattern is called a **closure**.

### Node 2: `trigger_check` (the decision-maker)

It looks at the numbers and chooses a mode, in this priority order: **unusual, then timer, then auto.** `unusual_reason` tests three rules:

1. **Spike:** the forecast jumped more than 30% since last minute.
2. **Near capacity:** traffic or forecast is above 95% of what our cooks can handle.
3. **Bad forecasts:** the predictions were wrong by more than 50% over the last 5 minutes.

There is a 3-minute **cooldown** so we don't call the expensive AI every minute during one long spike. If nothing is unusual and 5 minutes have passed, the mode is `timer`. Otherwise it is `auto`.

### Node 3: `script_creator`

It builds a text report of the last 10 minutes for the LLM to read.

```python
predicted_for = dict(zip(df["forecast_for"], df["forecast"]))
```
`zip` pairs two lists side by side, and `dict` turns the pairs into a lookup table. Here it means: "for minute X, what did we predict earlier?" That lets us compare **what we predicted** against **what really happened**. The report is a list of text lines joined with `"\n".join(lines)`.

### Nodes 4, 5, 6: the three branches

- `llm_unusual` and `llm_timer`: both call `llm.ask_llm(...)`. Only the reason differs.
- `auto_scale`: no AI. It takes the **highest demand in the last 10 minutes** (`np.maximum` compares two columns number by number) and applies the formula. Going **up** happens immediately, because the newest minute is always included. Going **down** waits until all of the last 10 minutes were low. This stops the cooks from being hired and fired every minute.

### Node 7: `apply_and_log` and the guardrail

The guardrail is a safety rule that limits **every** decision, whether it came from the AI or the formula:

```python
r = max(MIN, min(max_replicas, int(proposed)))
r = min(r, max(current + 2, int(current * 2.0)))
r = max(r, current - max(1, int(current * 0.25)))
```
Example up: 5 cooks now, the AI wants 20, max is 11. Step 1 gives 11. Step 2 allows at most `max(7, 10)` = 10, so the answer is **10**.
Example down: 8 cooks now, the AI wants 1. Step 2 leaves 1. Step 3 allows at most `8 - max(1, 2)` = 6 cooks removed from 8, so the answer is **6**.

`set_replicas()` is an empty placeholder. Later you connect Docker or Kubernetes there to really start and stop copies.

This node also writes `actions.csv`, but skips the boring minutes (auto mode and no change). Then `alert_reason_for` decides if a human must be told: the AI asked for help, the AI failed, traffic was above capacity 5 minutes in a row, or we are at the maximum and still overloaded. A 30-minute cooldown prevents email spam.

### Node 8: `alert_human`

It runs only when something is wrong. It collects the last 60 minutes, builds a context text, asks the LLM to write the email, attaches two CSV files, saves the email as a `.txt` file, and sends it only if sending is turned on.

---

## 6. `graph.py`: drawing the arrows

**LangGraph** lets us describe a workflow as a **graph**: boxes (nodes) joined by arrows (edges).

```python
g = StateGraph(AgentState)
g.add_node("trigger_check", nodes.trigger_check)
g.add_edge("store_prediction", "trigger_check")
g.add_conditional_edges("script_creator", route_mode, [...])
return g.compile()
```
- `add_node(name, function)` puts a box on the board.
- `add_edge(a, b)` is an arrow that always goes from a to b.
- `add_conditional_edges` is a **fork in the road**. A small function (`route_mode`) looks at the state and says which road to take.
- `compile()` finishes the diagram and makes it runnable.

There are only two forks:
- `route_mode` reads `state["mode"]` and returns `"llm_unusual"`, `"llm_timer"` or `"auto_scale"`.
- `route_alert` goes to `alert_human` only if `alert_reason` is not empty. Otherwise it goes to `END`.

This file has no calculations at all, only wiring.

---

## 7. `run.py`: the start button

You run this file. It is the one that actually repeats everything minute after minute.

**Options with `argparse`:**
```
python agent/run.py --minutes 120 --tick 0 --provider fake
```
`argparse` reads the words you type after the filename. `type=positive_int` rejects `--minutes 0` with a clean error message.

**The main loop:**
```python
for pos in range(feed.start_pos, end):
    state["pos"] = pos
    state = app.invoke(state)
    time.sleep(tick)
```
- `range(a, b)` counts through positions in the dataset, each one is "one minute".
- `app.invoke(state)` runs the whole graph once and returns the updated notebook. We reuse it next minute, which is how `replicas` and the timers carry over.
- `time.sleep(tick)` waits, so one minute passes in about one second.

**Ctrl+C:** `try: ... except KeyboardInterrupt:` catches you pressing Ctrl+C, so the program stops politely and still prints its summary.

**`if __name__ == "__main__": main()`** means "run `main()` only when this file is started directly, not when another file imports it".

**One more detail:** `import graph` is inside `main()`, not at the top. It loads the heavy AI library, which is slow. This way, a wrong option fails instantly instead of after a long wait.

---

## 8. The small files

| File | What it is |
|---|---|
| `requirements.txt` | A shopping list of libraries. `uv pip install -r requirements.txt` installs all of them. |
| `.env.example` | A template showing which secret settings exist. Copy it to `.env` and fill it in. |
| `.env` | **You** create this. It holds your real keys and is never shared. |
| `.gitignore` | Tells Git which files to never upload (`.env`, `data/`, `__pycache__/`). |
| `README.md` | The instruction page for humans. |
| `notebook/predict.py` | Not mine, your teammate's. It loads the LSTM with `torch`, and the agent uses 4 functions from it: `load_data`, `find_model`, `load_model`, `predict_at`. |

---

## One full minute, with real numbers

Say we have **5 cooks**, each handling **200 customers/minute** (total 1000). Now: traffic is 900, forecast is 1500, and last minute's forecast was 1400.

1. **store_prediction** writes the row (minute, 900, 1500, ...).
2. **trigger_check:** 1500 is above 95% of 1000, so the mode is `unusual` ("near capacity").
3. **script_creator** writes the 10-minute report.
4. **llm_unusual** asks the AI. The fake AI computes `ceil(1500 × 1.1 / 200)` = `ceil(8.25)` = **9**.
5. **apply_and_log:** the guardrail allows up to `max(7, 10)` = 10, so 9 is fine. Replicas go from 5 to **9**, and the change is written to `actions.csv`.
6. No alert is needed, so the minute ends. Next minute starts with 9 cooks.

---

## Check yourself

1. Why does `ask_llm` return `hold` when the AI fails, instead of stopping the program?
2. What is the difference between `add_edge` and `add_conditional_edges`?
3. Why is the guardrail applied to the auto formula as well as the AI?
4. In the guardrail, current is 4 and the AI proposes 30 (max 11). What is the final number?
5. Why is the password stored in `.env` and not in `config.py`?

*(Answers: 1. safety, doing nothing is safer than doing something random. 2. one always goes to the same box, the other chooses a road. 3. no decision should be able to break the limits. 4. min(11, max(6, 8)) = 8. 5. so secrets never get shared with the code.)*

I can turn this into a PDF handout or a Word file for the students if you want.