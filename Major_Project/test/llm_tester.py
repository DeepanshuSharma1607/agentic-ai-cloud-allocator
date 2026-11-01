"""
test_llm.py - checks that llm.py works, without running the whole agent.

    python test/llm_tester.py                    # uses LLM_PROVIDER from config.py
    python test/llm_tester.py --provider fake    # no internet, no key
    python test/llm_tester.py --provider gemini
    python test/llm_tester.py --provider mistral

Test 1: the replica decision.  Test 2: the urgent alert email text.
Nothing is saved and no email is sent.
"""
import argparse
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))   # so "config" and "llm" are found in the agent folder

import config as cfg
import llm

SCRIPT = """App app_62, minute 14117. Capacity 223 requests/min per replica, 5 replicas running (limits 1-21).
Last 5 minutes:
minute | actual | predicted_earlier | error | forecast_ahead | replicas
14113 | 1115 | 1090 | -2% | 1148 | 5
14114 | 1250 | 1120 | -10% | 1300 | 5
14115 | 1380 | 1210 | -12% | 1420 | 5
14116 | 1450 | 1290 | -11% | 1480 | 5
14117 | 1500 | 1350 | -10% | 1560 | 5
Now: traffic 1500/min, forecast 1560/min, utilisation 135%.
Recent actions:
none yet"""

FACTS = {"traffic_now": 1500.0, "forecast": 1560.0, "replicas": 5, "capacity": 223.0,
         "min_replicas": 1, "max_replicas": 21, "recent_peak": 1560.0}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--provider", choices=llm.PROVIDERS, help="default: LLM_PROVIDER in config.py")
    a = p.parse_args()
    if a.provider:
        cfg.LLM_PROVIDER = a.provider

    key = {"gemini": cfg.GEMINI_API_KEY, "mistral": cfg.MISTRAL_API_KEY}.get(cfg.LLM_PROVIDER)
    print(f"provider: {cfg.LLM_PROVIDER}")
    if cfg.LLM_PROVIDER != "fake":
        model = cfg.GEMINI_MODEL if cfg.LLM_PROVIDER == "gemini" else cfg.MISTRAL_MODEL
        print(f"model   : {model}")
        if cfg.LLM_PROVIDER == "gemini" and cfg.GEMINI_FALLBACK_MODEL:
            print(f"fallback: {cfg.GEMINI_FALLBACK_MODEL}")
        print(f"API key : {'found in .env' if key else 'MISSING (put it in agent/.env)'}")

    print("\n--- test 1: replica decision (traffic 1500/min, 5 replicas of 223/min -> overloaded) ---")
    t = time.time()
    d = llm.ask_llm(SCRIPT, cfg.MODE_UNUSUAL, "near capacity: test", FACTS)
    print(f"answer in {time.time() - t:.1f}s: {d}")
    if d.get("error"):
        print("RESULT: FAILED. Read the 'reason' text above. It names the cause.")
    elif d["replicas"] > FACTS["replicas"]:
        print(f"RESULT: OK. The LLM wants {d['replicas']} replicas (scale up is the sensible answer here).")
    else:
        print("RESULT: the call worked, but the answer is odd (traffic is above capacity, so it should scale up). "
              "Read the 'reason' text.")

    print("\n--- test 2: urgent alert email text ---")
    t = time.time()
    e = llm.write_alert_email("already at the maximum of 21 replicas and traffic is still above capacity", SCRIPT)
    print(f"answer in {time.time() - t:.1f}s")
    print("subject:", e["subject"])
    print("body   :", e["body"][:600])
    if "could not write this email" in e["body"] and cfg.LLM_PROVIDER != "fake":
        print("RESULT: FAILED. The LLM could not write the email, the plain-code version was used (see the note in the body).")
    else:
        print("RESULT: OK")


if __name__ == "__main__":
    main()
