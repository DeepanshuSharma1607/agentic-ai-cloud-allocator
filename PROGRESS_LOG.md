# AegisCloud — Progress Log

**Date:** Session 1 (planning + first dataset)
**Status:** Data generation phase — no model training has started yet.

---

## What this project is

AegisCloud is a research project that builds a system to automatically manage cloud
servers for a demand-driven app (think Zomato/Blinkit/Uber-style traffic). It predicts
upcoming demand, decides how many servers to run, and uses an LLM periodically as a
"health auditor" to catch problems the automated system might miss — without putting
an LLM in the loop for every single decision.

Three components, working together:
1. **Forecaster** — predicts near-future demand from recent history
2. **RL controller (PPO)** — decides scaling actions (add/remove servers) continuously
3. **LLM auditor** — checks system health periodically, flags degradation, recommends fixes
   (a deterministic safety layer has final say over any actual intervention)

---

## What we did today

### 1. Corrected project direction (twice)
- Started by misreading the project as a DeepRM-style **job-queue scheduler** (deciding
  which waiting job runs next on a cluster). This was wrong.
- Corrected to the real goal: an **auto-scaling / resource-provisioning system** that
  reacts to continuous demand (requests/minute), not discrete jobs.
- Then received an improved README (v2) that clarified the LLM's role: not a per-decision
  gate, but a **periodic auditor** of system health. Adopted this as the current design.

### 2. Designed the core data schema
Settled on a **telemetry time-series** format — one row per time interval, containing:
demand, capacity, utilization, queue backlog, latency, error rate, and cost.
(Full column reference is in the roadmap doc.)

### 3. Built and iterated a synthetic data generator
- **v1**: basic Poisson-arrival job data (discarded — wrong problem framing)
- **v2**: telemetry with morning/lunch/evening demand curves, reactive-threshold baseline scaling
  - First attempt had capacity too generous — scaling never triggered. Fixed by tightening
    pod capacity relative to demand.
- **v3 (current)**: added real-world imperfection on request, specifically:
  - Day-type events: normal / rain / festival days, each with different demand multipliers
  - Autocorrelated (AR(1)) noise instead of independent random noise, so bursts persist
    realistically instead of resetting every timestep
  - Long-term growth trend (compounding ~0.3%/day → ~20-30% growth over 90 days)
  - Spot vs. on-demand server cost tiers, with random spot preemption events
  - Latency and error-rate degradation that stays flat under normal load, then rises
    sharply past ~80% utilization (mimics real system collapse behavior)
  - Scaling delay (servers take a few minutes to boot) and a cooldown period between
    scaling actions (prevents unrealistic instant/constant rescaling)
- Explicitly deferred: multi-service correlation (e.g. order-placement + delivery-tracking
  as two related but distinct demand streams) — agreed to validate single-service mechanics
  first.

### 4. Verified the data tells the right story
Inspected a real morning-peak window: demand climbed from ~813 to ~1350 req/min between
7:30–8:30am, servers lagged behind because of boot delay, latency spiked to ~700ms and
queue backed up to 19 before capacity caught up. This is exactly the gap a forecasting
model is supposed to close by preparing capacity *before* the peak rather than after.

### 5. Decided on time resolution
Chose **1-minute intervals** over 5-minute or per-second, balancing realism (matches
real autoscaler check intervals), data volume (manageable), and having enough
resolution to clearly show the "demand rises → queue builds → latency spikes →
capacity catches up" sequence.

---

## Key learnings

- **Order of operations matters**: build realistic data before writing any model code.
  A model is only as good as the data it learns from, and our first drafts weren"t
  realistic enough to teach anything useful (e.g., scaling that never triggered).
- **Real-world messiness is a design choice, not an accident** — autocorrelated noise,
  scaling delay, and random preemption events aren't just "extra realism," they're what
  make forecasting and careful decision-making actually matter. A perfectly clean,
  instantly-reactive simulation would make *any* method look equally good.
- **Avoid circular evaluation**: keeping the forecaster's training data independent of
  any LLM-generated labels (per the updated README) prevents a subtle bug where the
  system would appear to "work" only because it's grading its own homework.
- **Scope discipline improves research quality.** Narrowing the LLM's role from "gates
  every decision" to "periodic auditor" made the system both easier to build and easier
  to defend as a research contribution — a good reminder that simpler, well-isolated
  designs often make stronger papers than maximally ambitious ones.

---

## Open questions for next session

1. Continuous telemetry vs. discrete job data — confirm we're staying with continuous
   (recommended), since the newest README mentions job-level fields that don't match
   our current schema.
2. Regenerate the dataset at 1-minute resolution over a full year (525,600 rows) —
   see roadmap doc for feasibility notes.
3. Decide whether to add seasonal (multi-month) demand variation to make full-year
   data meaningfully different from just a longer repeat of the 90-day pattern.
4. Next build target: the Gymnasium RL environment consuming this telemetry (Phase 2).

---

## Files produced so far
- `sample_telemetry_v2.csv` — 90-day synthetic dataset, 1-minute-resolution version pending
- This progress log
- A companion roadmap document (tools, libraries, concepts needed)
