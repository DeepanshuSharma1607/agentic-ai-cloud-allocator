"""
graph_tester.py - runs the REAL LangGraph pipeline (all 8 nodes) for a few minutes and checks that everything works.

    python test/graph_tester.py                       # fake LLM, no internet, no keys
    python test/graph_tester.py --provider gemini     # real Gemini (needs the key in agent/.env)
    python test/graph_tester.py --provider gemini --send-email   # also send ONE real alert email

It uses your real LSTM model and your real dataset, and forces every part of the graph to run:
    minute 3  -> an "unusual" event   (llm_unusual runs)
    minute 6+ -> the timer is due     (llm_timer runs)   [timer is set to every 3 minutes for this test]
    other     -> normal minutes       (auto_scale runs)
    minute 9  -> a forced alert       (alert_human runs)

Everything it writes goes into test/output/, so your agent/data/ files are NOT touched.
At the end it prints PASS or FAIL for every check. Exit code 0 = all passed, 1 = something failed.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "agent"))        # so "config", "nodes", "graph" are found in the agent folder

import config as cfg
import llm
from state import new_state

ALL_NODES = ["store_prediction", "trigger_check", "script_creator", "llm_unusual",
             "llm_timer", "auto_scale", "apply_and_log", "alert_human"]
BRANCH_OF_MODE = {"unusual": "llm_unusual", "timer": "llm_timer", "auto": "auto_scale"}
UNUSUAL_MINUTE = 2      # 0-based position of the minute where we force an "unusual" event
ALERT_MINUTE = 8        # 0-based position of the minute where we force an alert

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ->  {detail}" if detail else ""))


def parse_args():
    p = argparse.ArgumentParser(description="Full pipeline test for the LangGraph agent")
    p.add_argument("--provider", choices=llm.PROVIDERS, help="fake, gemini or mistral (default: LLM_PROVIDER in config.py)")
    p.add_argument("--minutes", type=int, default=12, help="minutes to run, at least 9 (default 12)")
    p.add_argument("--send-email", action="store_true", help="send the forced alert as a REAL email")
    p.add_argument("--app", help="app to replay (default: APP in config.py)")
    a = p.parse_args()
    if a.minutes < 9:
        p.error("--minutes must be at least 9, so that every node gets a chance to run")
    return a


def main():
    a = parse_args()
    if a.provider:
        cfg.LLM_PROVIDER = a.provider
    if a.app:
        cfg.APP = a.app
    keys = {"gemini": cfg.GEMINI_API_KEY, "mistral": cfg.MISTRAL_API_KEY}
    if cfg.LLM_PROVIDER in keys and not keys[cfg.LLM_PROVIDER]:
        raise SystemExit(f"{cfg.LLM_PROVIDER.upper()}_API_KEY is empty. Put it in agent/.env or use --provider fake.")
    if a.send_email and not (cfg.EMAIL_SENDER and cfg.EMAIL_PASSWORD and cfg.EMAIL_TO):
        raise SystemExit("--send-email needs EMAIL_SENDER, EMAIL_PASSWORD and EMAIL_TO in agent/.env")

    # --- test settings: separate output folder, short timer, email only if asked
    out = HERE / "output"
    cfg.DATA_DIR = out
    cfg.PREDICTIONS_CSV = out / "predictions.csv"
    cfg.ACTIONS_CSV = out / "actions.csv"
    cfg.ALERT_DIR = out / "alerts"
    cfg.TIMER_EVERY = 3
    cfg.ALERT_SEND_EMAIL = a.send_email

    import graph          # heavy import (torch), done after the arguments are checked
    import nodes

    nodes.reset_files()
    print("Loading real data and model ...")
    feed = nodes.Feed()
    app = graph.build_graph(feed)
    state = new_state(feed.capacity, feed.max_replicas, feed.start_replicas, feed.start_minute)
    print(f"App {cfg.APP} | LLM: {cfg.LLM_PROVIDER} | {a.minutes} minutes | real email: {'YES' if a.send_email else 'no (saved as file)'}")
    print(f"Output folder: {out}\n")

    # =============================================================== run the graph minute by minute
    print("--- running the graph (every minute is one full pass through the nodes) ---")
    log = []
    for i in range(a.minutes):
        state["pos"] = feed.start_pos + i
        state["force_alert"] = (i == ALERT_MINUTE)
        normal_threshold = cfg.NEAR_CAPACITY
        if i == UNUSUAL_MINUTE:
            cfg.NEAR_CAPACITY = 0.01                       # makes "near capacity" true for this one minute
        before, path = state["replicas"], []
        try:
            for chunk in app.stream(dict(state), stream_mode="updates"):   # one chunk per node that finished
                for node, update in chunk.items():
                    path.append(node)
                    if update:
                        state.update(update)
        finally:
            cfg.NEAR_CAPACITY = normal_threshold
        entry = {"i": i, "minute": state["minute"], "path": path, "mode": state["mode"], "before": before,
                 "applied": state["applied"], "decision": state["decision"], "alert": state["alert_reason"], "reason": state["reason"],
                 "status": state.get("alert_status", "") if "alert_human" in path else "", "script": state["script"]}
        log.append(entry)
        branch = path[3] if len(path) > 3 else "?"
        extra = "  + alert_human" if "alert_human" in path else ""
        print(f"  minute {entry['minute']} | mode {entry['mode']:<7} | branch {branch:<11} | "
              f"replicas {before} -> {entry['applied']}{extra}")

    # =============================================================== the checks
    print("\n--- check 1: every node ran at least once ---")
    counts = Counter(node for e in log for node in e["path"])
    for node in ALL_NODES:
        check(f"node {node}", counts[node] > 0, f"ran {counts[node]} time(s)")

    print("\n--- check 2: correct order in every minute ---")
    bad = []
    for e in log:
        p = e["path"]
        ok = (p[:3] == ["store_prediction", "trigger_check", "script_creator"]
              and len(p) >= 5 and p[3] == BRANCH_OF_MODE[e["mode"]] and p[4] == "apply_and_log"
              and (("alert_human" in p) == bool(e["alert"])) and len(p) == (6 if e["alert"] else 5))
        if not ok:
            bad.append(f"minute {e['minute']}: {p}")
    check("store -> trigger -> script -> branch -> apply (-> alert only when needed)", not bad, "; ".join(bad[:2]))

    print("\n--- check 3: the three modes ---")
    modes = Counter(e["mode"] for e in log)
    check("unusual mode was chosen at the forced minute", log[UNUSUAL_MINUTE]["mode"] == "unusual",
          f"mode was {log[UNUSUAL_MINUTE]['mode']}, reason: {log[UNUSUAL_MINUTE]['reason'][:60]}")
    check("timer mode happened", modes["timer"] > 0, f"{modes['timer']} time(s)")
    check("auto mode happened", modes["auto"] > 0, f"{modes['auto']} time(s)")

    print("\n--- check 4: predictions.csv ---")
    import pandas as pd
    df = pd.read_csv(cfg.PREDICTIONS_CSV)
    check("columns are correct", list(df.columns) == nodes.PRED_COLS, str(list(df.columns)))
    check("one row per minute", len(df) == a.minutes, f"{len(df)} rows for {a.minutes} minutes")
    check("no empty values", not df.isna().any().any())
    check("minutes follow each other", (df["minute"].diff().dropna() == 1).all())
    check("forecast is for minute + H", ((df["forecast_for"] - df["minute"]) == int(feed.ckpt["H"])).all(),
          f"H = {feed.ckpt['H']}")

    print("\n--- check 5: the script given to the LLM ---")
    script = log[-1]["script"]
    table_rows = [ln for ln in script.splitlines() if re.match(r"^\d+ \|", ln)]
    check("has the table header", "minute | actual | predicted_earlier" in script)
    check("has a recent-actions part", "Recent actions:" in script)
    check(f"at most {cfg.SCRIPT_MINUTES} minutes of rows", 0 < len(table_rows) <= cfg.SCRIPT_MINUTES, f"{len(table_rows)} rows")

    print("\n--- check 6: replicas and guardrail ---")
    chain_ok = all(log[k]["before"] == log[k - 1]["applied"] for k in range(1, len(log)))
    check("replicas carry over from one minute to the next", chain_ok)
    violations = []
    for e in log:
        b, ap = e["before"], e["applied"]
        low = max(cfg.MIN_REPLICAS, b - max(1, int(b * cfg.MAX_DOWN_FRACTION)))
        high = min(state["max_replicas"], max(b + 2, int(b * cfg.MAX_UP_MULTIPLIER)))
        if not (low <= ap <= high):
            violations.append(f"minute {e['minute']}: {b} -> {ap} (allowed {low}..{high})")
    check("every change stays inside the guardrail", not violations, "; ".join(violations[:2]))

    print("\n--- check 7: actions.csv ---")
    expected = sum(1 for e in log if e["mode"] != "auto" or e["applied"] != e["before"])
    if cfg.ACTIONS_CSV.exists():
        act = pd.read_csv(cfg.ACTIONS_CSV)
        check("a row for every LLM call and every replica change", len(act) == expected, f"{len(act)} rows, expected {expected}")
        check("columns are correct", list(act.columns) == nodes.ACTION_COLS)
    else:
        check("actions.csv exists", expected == 0, "file missing")

    print(f"\n--- check 8: the LLM ({cfg.LLM_PROVIDER}) ---")
    llm_minutes = [e for e in log if e["mode"] in ("unusual", "timer")]
    shape_ok = all({"action", "replicas", "reason"} <= set(e["decision"]) and isinstance(e["decision"]["replicas"], int)
                   for e in log)
    check("every decision has action, replicas (a whole number) and reason", shape_ok)
    errors = [e for e in llm_minutes if e["decision"].get("error")]
    check(f"all {len(llm_minutes)} LLM calls succeeded", not errors,
          f"minute {errors[0]['minute']}: {errors[0]['decision']['reason'][:150]}" if errors else "")

    print("\n--- check 9: the alert ---")
    alert = log[ALERT_MINUTE]
    check("alert fired at the forced minute", alert["alert"].startswith("TEST ALERT"), alert["alert"][:60])
    alert_file = cfg.ALERT_DIR / f"alert_{alert['minute']}.txt"
    text = alert_file.read_text(encoding="utf-8") if alert_file.exists() else ""
    check("alert email was saved as a file", "Subject:" in text, alert_file.name)
    if cfg.LLM_PROVIDER != "fake":
        check("the LLM wrote the email text", "could not write this email" not in text)
    if a.send_email:
        check("real email was sent", alert["status"].startswith("sent to"), alert["status"])
    else:
        print(f"  [INFO] email sending was off. Status: {alert['status']}")
    print(f"  [INFO] read it here: {alert_file}")

    # =============================================================== verdict
    passed, failed = sum(results), len(results) - sum(results)
    print(f"\n===== {passed} passed, {failed} failed =====")
    print("ALL GOOD: the whole pipeline works." if not failed else "SOMETHING FAILED: read the [FAIL] lines above.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
