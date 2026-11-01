"""
run.py - starts the agent. It replays the dataset one row per "minute" and runs the graph once per minute.

Run from the Major_Project folder (or from anywhere):

    python agent/run.py                          # whole test period, 1 second per minute, fake LLM
    python agent/run.py --minutes 120 --tick 0   # quick test: 120 minutes, no waiting
    python agent/run.py --timer 3                # LLM check every 3 minutes
    python agent/run.py --provider gemini        # real LLM (needs GEMINI_API_KEY in agent/.env)
    python agent/run.py --provider mistral
    python agent/run.py --email                  # also SEND alert emails (needs the 3 EMAIL_ lines in agent/.env)
    python agent/run.py --quiet                  # print only the minutes where something happens

Ctrl+C stops it safely: the CSV files are already written, and a summary is printed.
Output files (agent/data/): predictions.csv, actions.csv, alerts/alert_<minute>.txt
"""
import argparse
import sys
import time

import config as cfg
import llm
from state import new_state


def positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def parse_args():
    p = argparse.ArgumentParser(description="Autoscaler agent (LangGraph)")
    p.add_argument("--minutes", type=positive_int, help="how many minutes to replay (default: until the data ends)")
    p.add_argument("--tick", type=float, help="seconds to wait between minutes (default: TICK_SECONDS in config.py)")
    p.add_argument("--timer", type=positive_int, help="minutes between normal LLM checks (default: TIMER_EVERY in config.py)")
    p.add_argument("--app", help="app column to replay, e.g. app_1 (default: APP in config.py)")
    p.add_argument("--provider", choices=llm.PROVIDERS, help="fake, gemini or mistral (default: LLM_PROVIDER in config.py)")
    p.add_argument("--email", action="store_true", help="really send alert emails")
    p.add_argument("--quiet", action="store_true", help="print only minutes with an LLM call, a replica change or an alert")
    p.add_argument("--metrics-port", type=positive_int, default=8000, help="Prometheus exporter port (default: 8000)")
    p.add_argument("--no-metrics", action="store_true", help="disable the Prometheus metrics endpoint")
    p.add_argument("--test-alert", action="store_true", help="force exactly one test alert on the first replay minute")
    p.add_argument("--serve-after-replay", action="store_true", help="keep the metrics endpoint alive after replay ends; Ctrl+C stops it")
    return p.parse_args()


def check_setup():
    """Stop early, with a clear message, if the settings cannot work."""
    keys = {"gemini": cfg.GEMINI_API_KEY, "mistral": cfg.MISTRAL_API_KEY}
    if cfg.LLM_PROVIDER in keys and not keys[cfg.LLM_PROVIDER]:
        name = cfg.LLM_PROVIDER.upper() + "_API_KEY"
        raise SystemExit(f"{name} is empty. Put it in agent/.env (see .env.example) or use --provider fake.")
    if cfg.ALERT_SEND_EMAIL and not (cfg.EMAIL_SENDER and cfg.EMAIL_PASSWORD and cfg.EMAIL_TO):
        print("WARNING: email is on but EMAIL_SENDER / EMAIL_PASSWORD / EMAIL_TO are not all set in agent/.env. "
              "Alerts will only be saved as files.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")     # an LLM reply with odd characters must never crash the printing
    a = parse_args()
    if a.app:
        cfg.APP = a.app
    if a.provider:
        cfg.LLM_PROVIDER = a.provider
    if a.timer:
        cfg.TIMER_EVERY = a.timer
    if a.email:
        cfg.ALERT_SEND_EMAIL = True
    tick = cfg.TICK_SECONDS if a.tick is None else max(0.0, a.tick)
    check_setup()

    import graph      # imported here because it loads torch, so a wrong option fails fast, without the wait
    import nodes

    nodes.reset_files()
    print("Loading data and model ...")
    feed = nodes.Feed()
    app = graph.build_graph(feed)
    state = new_state(feed.capacity, feed.max_replicas, feed.start_replicas, feed.start_minute)

    exporter = None
    if not a.no_metrics:
        from metrics import AllocatorMetrics
        exporter = AllocatorMetrics(cfg.APP, cfg.LLM_PROVIDER)
        exporter.set_initial(state)
        exporter.start(a.metrics_port)
        print(f"Prometheus metrics: http://localhost:{a.metrics_port}/metrics")

    if a.test_alert:
        print("TEST ALERT enabled: the first replay minute will create one test alert.")
        if not cfg.ALERT_SEND_EMAIL:
            print("Email sending is OFF. The alert will be saved to agent/data/alerts/ only; add --email to send it.")

    end = feed.n if a.minutes is None else min(feed.n, feed.start_pos + a.minutes)

    print(f"App {cfg.APP} | LLM: {cfg.LLM_PROVIDER} | timer every {cfg.TIMER_EVERY} min | "
          f"capacity {feed.capacity:.0f}/min per replica | replicas {cfg.MIN_REPLICAS}-{feed.max_replicas} | "
          f"alert emails: {'ON' if cfg.ALERT_SEND_EMAIL else 'OFF (saved as files)'}")
    print(f"Replaying {end - feed.start_pos} minutes. Press Ctrl+C to stop.\n")

    stats = {"minutes": 0, "llm_calls": 0, "scale_events": 0, "alerts": 0, "over_capacity": 0, "replica_minutes": 0}
    interrupted = False
    try:
        for pos in range(feed.start_pos, end):
            before = state["replicas"]
            state["pos"] = pos
            # The test switch is true for the first replay minute only. It uses the
            # existing alert_human node and does not change the normal alert rules.
            state["force_alert"] = bool(a.test_alert and pos == feed.start_pos)

            graph_started = time.perf_counter()
            state = app.invoke(state)                       # one full pass through the graph = one minute
            graph_duration = time.perf_counter() - graph_started

            after, mode, alert = state["applied"], state["mode"], state["alert_reason"]
            over_capacity_before = state["traffic_now"] > before * state["capacity"]
            if exporter is not None:
                exporter.record_tick(state, before, graph_duration, over_capacity_before)
            stats["minutes"] += 1
            stats["replica_minutes"] += before
            stats["llm_calls"] += mode in (cfg.MODE_UNUSUAL, cfg.MODE_TIMER)
            stats["scale_events"] += after != before
            stats["alerts"] += bool(alert)
            stats["over_capacity"] += over_capacity_before

            if not a.quiet or mode != cfg.MODE_AUTO or after != before or alert:
                print(f"minute {state['minute']} | traffic {state['traffic_now']:>8.0f} | forecast {state['forecast']:>8.0f} | "
                      f"replicas {before:>3} -> {after:<3} | {mode:<7} | {state['decision']['reason'][:70]}")
            if state["decision"].get("error"):
                print(f"    LLM ERROR (full text): {state['decision']['reason']}")
            if alert:
                print(f"    ALERT: {alert}\n    -> {state['alert_status']}")
            if tick > 0:
                time.sleep(tick)
    except KeyboardInterrupt:
        interrupted = True
        print("\nStopped with Ctrl+C.")

    print("\n===== summary =====")
    print(f"minutes replayed        : {stats['minutes']}")
    print(f"LLM calls               : {stats['llm_calls']}  (provider: {cfg.LLM_PROVIDER})")
    print(f"replica changes         : {stats['scale_events']}")
    print(f"alerts                  : {stats['alerts']}")
    print(f"replica-minutes (cost)  : {stats['replica_minutes']}")
    print(f"minutes above capacity  : {stats['over_capacity']}  (new replicas are assumed to start instantly)")
    print(f"files                   : {cfg.DATA_DIR}")

    if a.serve_after_replay and exporter is not None and not interrupted:
        print(f"\nReplay finished. Metrics endpoint remains available at http://localhost:{a.metrics_port}/metrics")
        print("Prometheus/Grafana can continue scraping the final values. Press Ctrl+C to stop the exporter.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nMetrics exporter stopped.")


if __name__ == "__main__":
    main()