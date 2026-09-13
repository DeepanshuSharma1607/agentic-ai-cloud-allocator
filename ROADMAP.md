# AegisCloud — Build Roadmap

This is a plain-language guide to what we'll build, in what order, and what tools/
concepts each stage needs. Written so someone without a CS background can follow along.

---

## The big picture, in one sentence

We're building three "brains" (a predictor, a decision-maker, and a health-checker)
that sit on top of realistic fake data, and testing whether they manage cloud servers
better than simple rule-based approaches.

---

## Phase-by-phase plan

### Phase 1 — Realistic Data (mostly done)

**What it is:** Fake-but-realistic records of server activity over time — demand,
capacity, latency, cost, etc. Think of it as a flight simulator's training data for
a pilot: nothing "smart" happens yet, we're just building the practice environment.

**Tools needed:**
- **Python** — the programming language everything else is written in. Chosen because
  it has the richest set of tools for data and AI work, and reads close to plain English.
- **NumPy** — a library for fast number-crunching (generating random numbers with
  specific statistical shapes, doing math on large arrays of numbers quickly).
- **Pandas** — a library for working with data in table form (rows and columns, like
  a spreadsheet you can filter, sort, and analyze with code instead of clicking).

**Concepts to understand:**
- **What a time series is** — a sequence of numbers recorded over time (e.g., demand
  every minute). Almost everything in this project is a time series.
- **What a distribution is** — a shape describing how likely different values are.
  E.g., "most jobs are small, a few are huge" is a specific distribution shape
  (called Pareto/heavy-tailed), different from "most values cluster around an average"
  (called normal/Gaussian).
- **Percentiles** (like "p95 latency") — p95 means "95% of requests were faster than
  this number." It's a more honest way to describe "typical slowness" than an average,
  because a few very slow requests would get hidden inside an average but show up
  clearly in a p95 measurement.

**Status:** ✅ We have a working generator with realistic demand curves, day-type
events, scaling delay, cost tiers, and overload behavior.

---

### Phase 2 — Reinforcement Learning (RL) Controller

**What it is:** A system that learns, through trial and error, when to add or remove
servers — similar to how a person learns a video game by playing it repeatedly and
gradually figuring out which moves lead to better outcomes.

**Tools needed:**
- **Gymnasium** — a standard "interface" library for RL. It defines a common shape
  for "here's the current situation," "here's the action taken," "here's the result
  and score" — so we don't have to invent this structure from scratch, and so our
  code works with off-the-shelf RL algorithms.
- **Stable-Baselines3** — a library containing ready-made, well-tested implementations
  of RL algorithms (including **PPO**, the one we're using). We don't need to
  implement the learning algorithm's math ourselves — we plug our environment into
  their PPO trainer.
- **PyTorch** — the underlying deep learning library that Stable-Baselines3 and our
  own custom neural networks are built on top of.

**Concepts to understand:**
- **What Reinforcement Learning (RL) is, simply:** an "agent" (our controller) looks
  at a situation ("state"), picks an action, and later finds out whether that action
  was good or bad (a "reward"). Over many repeated attempts, it gradually learns which
  actions tend to lead to good outcomes in which situations. No one tells it the
  right answer directly — it discovers a good strategy through repeated feedback.
- **What PPO is:** a specific, popular, and fairly stable RL algorithm. You don't need
  to understand its internal math to use it — think of it as "a well-tested training
  method," similar to how you can drive a car without knowing how the engine works.
- **State, action, reward:** the three ingredients of any RL problem.
  - *State* = what the controller currently sees (demand, CPU usage, cost so far, etc.)
  - *Action* = what it can choose to do (add a server, remove a server, do nothing)
  - *Reward* = a score telling it how good that choice turned out to be

---

### Phase 3 — Forecasting Model

**What it is:** A model that looks at recent demand and predicts what's coming next
— similar to predicting tomorrow's weather from today's patterns.

**Tools needed:**
- **PyTorch** (same as above) — used to build the forecasting neural network.
- Simple statistical baselines first (no special library needed) — e.g., "assume
  tomorrow looks like today," used to sanity-check that a fancier model is actually
  worth the added complexity.
- **Transformer** — a type of neural network architecture (the same family of model
  behind tools like ChatGPT) that's good at finding patterns across a sequence of
  data points. We build a small, purpose-specific version — nothing like a full
  language model, just the same underlying pattern-recognition idea applied to numbers
  instead of words.

**Concepts to understand:**
- **Why forecasting even matters here:** if you only ever *react* to demand after it
  happens, you're always a step behind. A forecast lets you start preparing (booting
  servers) before the peak actually arrives.
- **Forecast error metrics (MAE, RMSE):** simple ways of measuring "how wrong was the
  prediction, on average." Lower is better. You don't need the formulas memorized —
  just know these are the project's way of grading the forecaster's accuracy.

---

### Phase 4 — Connecting Forecast + RL

**What it is:** Feeding the forecaster's predictions into the RL controller's decision
process, so it can act on what's *expected* to happen, not just what's happening right now.

**Tools needed:** No new tools — this is about wiring Phases 2 and 3 together.

**Concept to understand:** This is where we test whether forecasting actually helps.
It's tempting to assume "more information = better," but the project explicitly plans
to *measure* this rather than assume it — a good research habit.

---

### Phase 5 — LLM Auditor

**What it is:** Periodically (e.g., every 10–15 minutes), an LLM looks at a summary of
recent system health and flags whether something's going wrong — like a manager
reviewing a dashboard once an hour instead of watching every single transaction.

**Tools needed:**
- **An LLM API** (e.g., Anthropic's Claude API or a similar provider) — this is how
  our code "asks" an LLM to analyze the situation and respond in a structured way.
- **Structured JSON output** — instead of the LLM replying in free-flowing paragraphs,
  we ask it to reply in a fixed, predictable format (like filling out a form) so our
  code can reliably read its answer without needing to parse loose text.
- **(Optional) LangGraph** — a framework for organizing multi-step "agent" workflows
  if the auditing logic becomes complex enough to need it. Not required to start.

**Concepts to understand:**
- **Why not use the LLM for everything:** LLM calls are slower and more expensive than
  simple math. Using it sparingly, only for judgment calls, keeps the system fast and
  cheap while still getting the benefit of its reasoning where it matters most.
- **Deterministic safety layer:** plain, unambiguous code rules (e.g., "never scale
  below the minimum server count") that double-check the LLM's suggestions before
  anything is actually allowed to happen. This exists because an LLM can occasionally
  make mistakes or unusual suggestions, and we don't want those directly controlling
  real infrastructure unchecked.

---

### Phase 6 — Experiments & Comparisons

**What it is:** Running the same simulated scenarios through many different setups
(rule-based only, RL only, RL+forecast, RL+forecast+rule-auditor, RL+forecast+LLM-auditor,
etc.) and comparing the results side by side.

**Tools needed:**
- **Matplotlib / Seaborn** — libraries for making charts and graphs from results, which
  become the figures in your paper and portfolio write-up.
- **Jupyter Notebook** — an interactive coding environment good for running experiments
  step by step and immediately seeing results/charts, rather than running a whole
  script blind.

**Concept to understand:** This is where the paper's actual "results" come from. Every
number you'll report (cost saved, latency improved, LLM calls needed) comes from
comparing these different setups fairly, using the same underlying data for each.

---

### Phase 7 & 8 — Kubernetes + Public Traces (optional / stretch goals)

**What it is:** Testing the system on a real (small, local) Kubernetes cluster instead
of just simulation, and validating against public real-world cloud traces.

**Tools needed (if pursued):**
- **Docker** — packages an application so it runs the same way anywhere.
- **Kubernetes / K3s** — the real-world system that actually runs and scales containers;
  K3s is a lightweight version suitable for a personal laptop.
- **Prometheus** — collects real system metrics (CPU, memory, etc.) instead of
  simulated ones.

**Recommendation:** Treat Phases 1–6 as the "must complete" core of the paper and
portfolio project. Phases 7–8 are valuable stretch goals to mention as future work if
time runs out — a completed simulation-based study is more valuable than an
incomplete real-cluster one.

---

## Supporting skills (useful throughout, not tied to one phase)

- **Git / GitHub** — version control (keeping a history of code changes) and a place
  to host your project publicly for a portfolio. Worth learning early since every
  future step benefits from having a clean commit history.
- **Basic statistics** — averages, percentiles, distributions (mentioned above) — comes
  up constantly when describing both the data and the results.
- **Markdown** — the simple text-formatting style used for README files (like this one)
  — quick to learn, useful for all project documentation.

---

## Suggested learning order (if these concepts are new to you)

1. Python basics (variables, loops, functions) — if not already comfortable
2. Pandas/NumPy — enough to read and manipulate the CSV data we've generated
3. What RL is, conceptually (state/action/reward) — no math needed yet
4. Try Stable-Baselines3's own beginner tutorial on a toy example (not our project)
   to get a feel for how training loops work
5. Basic time-series forecasting concepts (moving averages) before jumping to
   Transformers
6. LLM API basics (sending a prompt, getting structured JSON back) — this is the
   easiest phase, conceptually, since it's mostly "ask a question, read the answer"
