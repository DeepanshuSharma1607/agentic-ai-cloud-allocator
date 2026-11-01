# AegisCloud: fixes to do

Order: P1 before Prometheus and Grafana (Day 2), P2 during Days 2 to 4, P3 is the rest of the plan.
Tick each box when done and re-run the check shown next to it.

---

## P1: fix first (they affect correctness)

Status: items 1 to 7 are done in code. Re-run the Check line of each with your own keys to confirm.

### [x] 1. Declare `llm_failures` in `agent/state.py`
**Problem:** `apply_and_log` returns `llm_failures`, but it is not a key of `AgentState`. LangGraph silently drops undeclared keys (I tested this), so the counter restarts every minute and the alert "LLM failed 2 times in a row" can never fire.
**Fix:** add inside `AgentState`:
```python
    llm_failures: int           # LLM failures in a row (alert after LLM_FAILURES_BEFORE_ALERT)
```
**Check:** run `python test/graph_tester.py --provider gemini`, then temporarily set a wrong `GEMINI_API_KEY`. After 2 timer calls you should see an alert reason that starts with "the LLM failed 2 times in a row".

### [x] 2. Stop false escalations
**Problem:** in run 7, Gemini set `escalate: true` at minute 14130 while its reason said replicas were sufficient (82% utilisation). In run 4 an unplanned alert also appeared at minute 14117.
**Fix A, prompt** (`SYSTEM_PROMPT` in `agent/llm.py`), add to the rules:
```
- If the current replicas are enough for the demand, "escalate" must be false.
```
**Fix B, code** (`alert_reason_for` in `agent/nodes.py`). The LLM may only wake a human when plain code also sees high load:
```python
    if decision.get("escalate"):
        load = max(state["traffic_now"], state["forecast"]) / (applied * state["capacity"])
        if load > 0.9:
            return f"the LLM asks for a human: {decision['reason']}"
```
The 0.9 is a first guess. Note this also blocks a legitimate "forecasts are completely unreliable at low load" escalation. Decide if you want a second condition for a high forecast error.
**Check:** repeat `python agent/run.py --provider gemini --timer 3 --minutes 60 --quiet` three times. Expect no alert at low load.

### [x] 3. Stop flapping (LLM and `auto_scale` undoing each other)
**Problem:** minute 14145 Gemini 6 -> 7, minute 14146 `auto_scale` 7 -> 6.
**Fix:** after any scale-up, do not let `auto_scale` scale down for `DOWN_WAIT` minutes.
1. `state.py`, add the key (undeclared keys get dropped, see fix 1):
```python
    last_scale_up_minute: int   # minute of the last scale-up
```
2. `nodes.py`, in `apply_and_log`, add to the returned dict:
```python
    if applied > before:
        out["last_scale_up_minute"] = state["minute"]
```
3. `nodes.py`, in `auto_scale`, before computing `action`:
```python
    if state["minute"] - state.get("last_scale_up_minute", -10 ** 9) < cfg.DOWN_WAIT:
        need = max(need, state["replicas"])
```
**Check:** in the fake and Gemini runs there must be no `N -> N+1` followed by `N+1 -> N` within 10 minutes.

### [x] 4. Make the LLM's reason clean and correct
**Problem:** reasons with wrong arithmetic (minute 14115) and "Wait, let's calculate:" (minute 14118).
**Fix A, prompt**, add to the rules:
```
- "reason" is ONE short sentence. Do not show calculations and do not think out loud.
```
**Fix B, give it the answer.** Compute the plain formula result and pass it in the prompt as `formula_replicas`, with the rule: "Stay with formula_replicas unless the report shows a clear reason, and name that reason." This removes most of the arithmetic the small model gets wrong. See also fix 9.
**Check:** the reasons in `actions.csv` are one sentence each, with numbers that match the report.

### [x] 5. Clean up `agent/nodes.py`
**Problem:** `alert_reason_for` contains the `force_alert` check twice, and the comment mentions `run.py --test-alert`, which does not exist.
**Fix:** keep one copy:
```python
    if state.get("force_alert"):          # tests only: used by test/graph_tester.py, ignores the cooldown
        return "TEST ALERT: forced by graph_tester.py"
```
**Check:** `python test/graph_tester.py` still shows 28 passed.

### [x] 6. Mailer: use the second port or remove the setting
**Problem:** `config.py` has `SMTP_PORT_STARTTLS = 587` ("tried automatically"), but `mailer.py` only uses SSL on 465. Hostel Wi-Fi may block 465.
**Fix:** in `mailer.py`, replace the `with smtplib.SMTP_SSL(...)` block with:
```python
        try:
            with smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=cfg.EMAIL_TIMEOUT) as server:
                server.login(cfg.EMAIL_SENDER, cfg.EMAIL_PASSWORD)
                server.send_message(msg)
        except (OSError, smtplib.SMTPConnectError):          # port 465 blocked: try STARTTLS on 587
            with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT_STARTTLS, timeout=cfg.EMAIL_TIMEOUT) as server:
                server.starttls()
                server.login(cfg.EMAIL_SENDER, cfg.EMAIL_PASSWORD)
                server.send_message(msg)
```
Do not catch login errors here, so a wrong password is still reported clearly.
**Check:** `python test/graph_tester.py --provider gemini --send-email` still sends the email.

### [x] 7. `.gitignore`
**Problem:** the zip contains `agent/data/*.csv` (created on every run), and the root `.gitignore` has a broken line `agent/ .env`.
**Fix:** replace the root `.gitignore` with:
```
.venv/
.env
agent/.env
__pycache__/
*.pyc
llm_talks/
agent/data/
test/output/
```
Then run `git rm -r --cached agent/data` once so the old CSV files leave the repository.
**Check:** `git status` shows no `.env` and no CSV outputs.

---

## P2: during Days 2 to 4

### [ ] 8. Make the tests catch quality problems
Today `graph_tester.py` proves the wiring, not the decisions. Run 4 had an unplanned alert and still passed.
Add checks:
- **Exactly one alert** in the 12 minutes (only the forced one). This would have caught the minute 14117 alert.
- **No flapping:** no scale-up followed by a scale-down within 10 minutes.
- **Reason is one sentence** (no line break, under 200 characters).

Also run `graph_tester.py --provider gemini` 3 times. Gemini answers vary between runs even at temperature 0.

### [ ] 9. Log what the plain formula would have done
Add a `formula_replicas` column to `actions.csv`. Then compute how often the LLM disagrees with the formula and whether the disagreement helped. This is your best evidence for the final comparison.
Also log which Gemini model answered (main or fallback) in the decision, so you can see when the fallback is used.

### [ ] 10. Verify the model names
Check that `gemini-3.5-flash-lite` and `gemini-3.8-flash` are the models you want in Google's current model list. If the main one is retired, every call silently goes to the fallback and doubles latency.

### [ ] 11. Try Mistral once
`python test/llm_tester.py --provider mistral`, then `python test/graph_tester.py --provider mistral`. Until then the README must say "Mistral not run".

### [ ] 12. Replace the repeated CSV reads with in-memory data
The graph reads `predictions.csv` several times per minute. This is fine for a replay but breaks a live Prometheus loop. Keep a small in-memory list of recent rows and write the CSV only as a log.

### [ ] 13. Unit tests and CI
Add `pytest` tests for: `guardrail` (use the 4 -> 30 -> 8 example), `parse_reply` (junk, bool, huge numbers, fenced JSON), `unusual_reason`, `replicas_for`, `alert_reason_for` (cooldown, escalate, failures). Run them in GitHub Actions on every push. No LSTM or internet is needed for these.

### [ ] 14. Update the READMEs after the fixes
- Remove the "known bug" lines about `llm_failures`, the duplicate `force_alert` and the unused STARTTLS setting.
- In "What is tested", mark: forced email through the graph tester **confirmed**, Mistral status, and the new test checks.
- Add the Day 1 results from `test_results.md`.

---

## P3: the rest of the plan

| Day | Item |
|---|---|
| 2 | Prometheus metrics with `prometheus_client` (traffic, forecast, replicas, mode, LLM calls, LLM errors, alerts), Grafana dashboard, `docker-compose` |
| 3 | Live feed instead of the CSV replay. Real `set_replicas()` for Docker or Kubernetes (kind or minikube) |
| 4 | Simulator with a 2-minute replica start-up delay. Compare: threshold rule, target tracking, forecast + schedule, forecast + agent. Report cost (replica-minutes) and missed-SLO minutes. Test a harder app such as `app_185`, not only `app_62` |
| 5 | Dockerfile, compose or K8s manifests, secrets only through `.env` or the platform's secret store, README that matches reality |
| 6 | Fresh clone, run from zero, demo video, final README status |

## Security reminder

- Never commit `agent/.env`. It holds the Gemini key and the Gmail app password.
- If either was ever pasted into a chat, a screenshot or a commit, revoke it and create a new one (Gmail: delete the app password and create another).