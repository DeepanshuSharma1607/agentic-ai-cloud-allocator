"""
llm.py - the only file that talks to an LLM.

One function is used by the nodes:

    ask_llm(script, mode, reason, facts) -> {"action": ..., "replicas": ..., "reason": ..., "escalate": bool}
    write_alert_email(reason, context)   -> {"subject": ..., "body": ...}      (urgent email to a human)

  script : the 10-minute text made by script_creator
  mode   : "unusual" or "timer" (why the LLM is being called)
  reason : plain-words reason from trigger_check
  facts  : dict with traffic_now, forecast, replicas, capacity, min_replicas, max_replicas

The answer is ALWAYS a valid dict. If the LLM fails, times out, or returns garbage,
the answer is "hold" (keep the current replicas), so the agent never crashes or does something random.
Provider is chosen in config.py: "fake", "gemini" or "mistral".
"""
import json
import math
import time

import requests

import config as cfg

PROVIDERS = ("fake", "gemini", "mistral")

SYSTEM_PROMPT = """You are the governor of an autoscaler for one containerized app.
You receive a short report of the last minutes: traffic, forecasts made 10 minutes earlier, the actual traffic, and the current replicas.
Your job: check whether the current replica count is right, and fix it if there is a problem.
Rules:
- One replica serves `capacity` requests per minute. Keep about 10% spare room.
- A new replica needs about 2 minutes to start, so react to the forecast, not only to the current traffic.
- If the forecasts were badly wrong recently, trust the actual traffic more than the forecast.
- Do not change replicas for small noise. Prefer "hold" when the current count is fine.
- Never go below min_replicas or above max_replicas.
- Set "escalate" to true ONLY when scaling cannot fix the problem and a human must look: for example already at
  max_replicas and still overloaded, traffic that looks like an attack or a bug, or forecasts that are completely unreliable.
  Otherwise set it to false.
- If the current replicas are enough for the demand, "escalate" must be false.
- formula_replicas is the answer of the plain formula. Stay with formula_replicas unless the report shows a clear reason, and name that reason.
- "reason" is ONE short sentence. Do not show calculations and do not think out loud.
Reply with ONE JSON object and nothing else:
{"action": "scale_up" or "scale_down" or "hold", "replicas": <integer, the new total>, "reason": "<one short sentence>", "escalate": true or false}"""

ALERT_SYSTEM_PROMPT = """You write URGENT alert emails for the engineer who owns an autoscaler.
You receive the problem the autoscaler detected and a report of the last hour (traffic, forecasts, replicas, actions taken).
Write a short plain-text email, under 250 words, with these parts:
1. What is wrong (one or two sentences).
2. Evidence: the key numbers from the report. Use ONLY numbers that are in the report, never invent any.
3. What the autoscaler already did.
4. What the engineer should check or do next.
The full last-hour logs are attached as CSV files, so do not paste them.
Reply with ONE JSON object and nothing else:
{"subject": "<short subject that starts with [URGENT]>", "body": "<the email text>"}"""


def build_prompt(script, mode, reason, facts):
    """The text sent as the user message: facts + the 10-minute script."""
    return (
        f"Why you were called: {mode} ({reason})\n"
        f"current_replicas: {facts['replicas']}\n"
        f"capacity_per_replica: {facts['capacity']:.0f}\n"
        f"min_replicas: {facts['min_replicas']}\n"
        f"max_replicas: {facts['max_replicas']}\n"
        f"highest_demand_last_minutes: {facts.get('recent_peak', facts['traffic_now']):.0f}\n"
        + (f"formula_replicas: {facts['formula_replicas']}\n" if "formula_replicas" in facts else "")
        + "\n"
        f"Report of the last minutes:\n{script}"
    )


# ---------------------------------------------------------------- the three providers
def fake_llm(facts):
    """Rule-based stand-in. Free. Same output format as the real LLM."""
    demand = max(facts["traffic_now"], facts["forecast"], facts.get("recent_peak", 0))   # same idea as auto_scale: no flapping
    need = math.ceil(demand * (1 + cfg.MARGIN) / facts["capacity"])
    return {"action": "fake", "replicas": need, "reason": f"fake LLM: demand {demand:.0f}/min needs {need} replicas"}


# ---------------------------------------------------------------- sending a message to an online LLM
RETRY_STATUS = (429, 500, 502, 503, 504)       # "busy / try again" answers from the server


def post_json(url, body, headers):
    """POST and return the reply as a dict. Temporary problems (busy server, dropped connection) are retried
    a few times. Real errors (wrong key, wrong model name) are raised at once with the server's explanation."""
    last = "unknown problem"
    for attempt in range(cfg.LLM_RETRIES + 1):
        try:
            r = requests.post(url, json=body, headers=headers, timeout=cfg.LLM_TIMEOUT)
            if r.status_code not in RETRY_STATUS:
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                return r.json()
            last = f"HTTP {r.status_code} (server busy)"
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < cfg.LLM_RETRIES:
            time.sleep(cfg.LLM_RETRY_WAIT * (attempt + 1))
    raise RuntimeError(f"still failing after {cfg.LLM_RETRIES + 1} tries, last problem: {last}")


def call_gemini(system, user):
    """Try the first model; if it fails (busy, unknown name ...), try the fallback model."""
    models = [cfg.GEMINI_MODEL] + ([cfg.GEMINI_FALLBACK_MODEL] if cfg.GEMINI_FALLBACK_MODEL else [])
    errors = []
    for model in models:
        try:
            return call_gemini_model(model, system, user)
        except Exception as e:
            errors.append(f"{model}: {e}")
    raise RuntimeError(" || ".join(errors))


def call_gemini_model(model, system, user):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    data = post_json(url, body, {"x-goog-api-key": cfg.GEMINI_API_KEY})
    return data["candidates"][0]["content"]["parts"][0]["text"]


def call_mistral(system, user):
    body = {
        "model": cfg.MISTRAL_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    data = post_json("https://api.mistral.ai/v1/chat/completions", body, {"Authorization": f"Bearer {cfg.MISTRAL_API_KEY}"})
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------- checking the reply
def parse_reply(text, facts):
    """Turn the LLM text into a clean dict. Raises ValueError if it is not usable."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in the reply")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict) or "replicas" not in data:
        raise ValueError("JSON has no 'replicas'")
    if isinstance(data["replicas"], bool):
        raise ValueError("'replicas' is not a number")
    try:
        replicas = float(data["replicas"])
    except (TypeError, ValueError):
        raise ValueError("'replicas' is not a number")
    if not math.isfinite(replicas):
        raise ValueError("'replicas' is not finite")
    replicas = int(round(replicas))
    replicas = max(facts["min_replicas"], min(facts["max_replicas"], replicas))
    current = facts["replicas"]
    action = "scale_up" if replicas > current else "scale_down" if replicas < current else "hold"
    return {"action": action, "replicas": replicas, "reason": str(data.get("reason", ""))[:300],
            "escalate": data.get("escalate") is True}


# ---------------------------------------------------------------- the one function the nodes call
def ask_llm(script, mode, reason, facts):
    if cfg.LLM_PROVIDER not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be one of {PROVIDERS}, got {cfg.LLM_PROVIDER!r}")
    try:
        if cfg.LLM_PROVIDER == "fake":
            text = json.dumps(fake_llm(facts))
        else:
            key = cfg.GEMINI_API_KEY if cfg.LLM_PROVIDER == "gemini" else cfg.MISTRAL_API_KEY
            if not key:
                raise ValueError(f"API key for {cfg.LLM_PROVIDER} is not set (see config.py)")
            user = build_prompt(script, mode, reason, facts)
            call = call_gemini if cfg.LLM_PROVIDER == "gemini" else call_mistral
            text = call(SYSTEM_PROMPT, user)
        return parse_reply(text, facts)
    except Exception as e:                                  # network, timeout, bad JSON, anything
        return {"action": "hold", "replicas": facts["replicas"], "reason": f"LLM error, holding: {e}",
                "escalate": False, "error": True}


# ---------------------------------------------------------------- the urgent email
def template_email(reason, context, note=""):
    """Email made by plain code. Used by the fake provider and whenever the LLM cannot write the email."""
    body = f"{note}The autoscaler detected a problem:\n{reason}\n\n{context}\n\nThe last hour of logs is attached."
    return {"subject": f"[URGENT] Autoscaler needs attention: {reason}"[:150], "body": body}


def write_alert_email(reason, context):
    """Always returns {"subject", "body"}. If the LLM fails, the plain-code email is used, so the alert is never lost."""
    if cfg.LLM_PROVIDER not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be one of {PROVIDERS}, got {cfg.LLM_PROVIDER!r}")
    if cfg.LLM_PROVIDER == "fake":
        return template_email(reason, context)
    try:
        key = cfg.GEMINI_API_KEY if cfg.LLM_PROVIDER == "gemini" else cfg.MISTRAL_API_KEY
        if not key:
            raise ValueError(f"API key for {cfg.LLM_PROVIDER} is not set")
        call = call_gemini if cfg.LLM_PROVIDER == "gemini" else call_mistral
        text = call(ALERT_SYSTEM_PROMPT, f"Problem detected: {reason}\n\n{context}")
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in the reply")
        data = json.loads(text[start:end + 1])
        subject, body = str(data.get("subject", "")).strip(), str(data.get("body", "")).strip()
        if not subject or not body:
            raise ValueError("subject or body is empty")
        return {"subject": subject[:150], "body": body}
    except Exception as e:
        return template_email(reason, context, note=f"(The LLM could not write this email: {e}. This is the automatic version.)\n\n")