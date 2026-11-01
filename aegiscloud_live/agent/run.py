"""
run.py - starts the agent. It runs the LangGraph ONCE PER NEW TICK of the live system (every 5 real seconds):

    python -m agent.run                          # fake LLM, no keys needed
    python -m agent.run --provider gemini        # real LLM (needs GEMINI_API_KEY in .env)
    python -m agent.run --timer 3                # LLM check every 3 ticks (default 12 = 1 real minute)
    python -m agent.run --email                  # also SEND alert emails (needs the EMAIL_ lines in .env)
    python -m agent.run --quiet                  # print only ticks with an LLM call, a replica change or an alert
    python -m agent.run --max-ticks 100          # stop after 100 ticks
    python -m agent.run --keep-files             # do not clear data/agent/ at start

Run it from the project root, after the other services are up (python run_all.py starts everything).
Ctrl+C stops it safely; the CSV files are already written and a summary is printed.
Output files (data/agent/): agent_ticks.csv, actions.csv, alerts/alert_<minute>.txt
"""
import argparse
import sys
import time

from agent import config as cfg
from agent import llm
from agent.state import new_state


def positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def parse_args():
    p = argparse.ArgumentParser(description="Autoscaler agent (LangGraph), live")
    p.add_argument("--max-ticks", type=positive_int, help="stop after this many ticks (default: run until Ctrl+C)")
    p.add_argument("--timer", type=positive_int, help="ticks between normal LLM checks (default: TIMER_EVERY in config.py)")
    p.add_argument("--provider", choices=llm.PROVIDERS, help="fake, gemini or mistral (default: LLM_PROVIDER in config.py)")
    p.add_argument("--email", action="store_true", help="really send alert emails")
    p.add_argument("--quiet", action="store_true", help="print only ticks with an LLM call, a replica change or an alert")
    p.add_argument("--keep-files", action="store_true", help="keep the CSV files of the previous run")
    p.add_argument("--metrics-port", type=positive_int, default=8000, help="Prometheus exporter port (default: 8000)")
    p.add_argument("--no-metrics", action="store_true", help="disable the Prometheus metrics endpoint")
    p.add_argument("--test-alert", action="store_true", help="force exactly one test alert on the first tick")
    return p.parse_args()


def check_setup():
    keys = {"gemini": cfg.GEMINI_API_KEY, "mistral": cfg.MISTRAL_API_KEY}
    if cfg.LLM_PROVIDER in keys and not keys[cfg.LLM_PROVIDER]:
        name = cfg.LLM_PROVIDER.upper() + "_API_KEY"
        raise SystemExit(f"{name} is empty. Put it in .env (see agent/.env.example) or use --provider fake.")
    if cfg.ALERT_SEND_EMAIL and not (cfg.EMAIL_SENDER and cfg.EMAIL_PASSWORD and cfg.EMAIL_TO):
        print("WARNING: email is on but EMAIL_SENDER / EMAIL_PASSWORD / EMAIL_TO are not all set. Alerts will only be saved as files.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")      # an LLM reply with odd characters must never crash the printing
    a = parse_args()
    if a.provider:
        cfg.LLM_PROVIDER = a.provider
    if a.timer:
        cfg.TIMER_EVERY = a.timer
    if a.email:
        cfg.ALERT_SEND_EMAIL = True
    check_setup()

    from agent import graph, nodes                    # imported here so a wrong option fails fast
    from agent.feed import LiveFeed

    if not a.keep_files:
        nodes.reset_files()
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg.ALERT_DIR.mkdir(parents=True, exist_ok=True)

    feed = LiveFeed()
    print(f"Waiting for the prediction service ({feed.url}) ...")
    feed.wait_until_ready(say=print)
    app = graph.build_graph()

    first = feed.next_tick(-10 ** 9)
    start_replicas = cfg.START_REPLICAS or nodes.replicas_for(first["traffic_now"], feed.capacity, cfg.MIN_REPLICAS, feed.max_replicas)
    state = new_state(feed.capacity, feed.max_replicas, start_replicas, first["minute"] - 1)

    exporter = None
    if not a.no_metrics:
        try:
            from agent.metrics import AllocatorMetrics
            exporter = AllocatorMetrics(cfg.APP, cfg.LLM_PROVIDER)
            exporter.set_initial(state)
            exporter.start(a.metrics_port)
            print(f"Prometheus metrics: http://localhost:{a.metrics_port}/metrics")
        except OSError as e:
            print(f"Prometheus exporter disabled ({e}); use --metrics-port to pick another port.")
            exporter = None

    print(f"LLM: {cfg.LLM_PROVIDER} | timer every {cfg.TIMER_EVERY} ticks | capacity {feed.capacity:.0f}/tick per replica | "
          f"replicas {cfg.MIN_REPLICAS}-{feed.max_replicas} | alert emails: {'ON' if cfg.ALERT_SEND_EMAIL else 'OFF (saved as files)'}")
    print("Running live. Press Ctrl+C to stop.\n")

    stats = {"ticks": 0, "skipped": 0, "llm_calls": 0, "scale_events": 0, "alerts": 0, "over_capacity": 0, "replica_ticks": 0}
    last_minute, tick, interrupted = first["minute"] - 1, first, False
    try:
        while True:
            if tick["minute"] > last_minute + 1 and stats["ticks"]:
                stats["skipped"] += tick["minute"] - last_minute - 1      # the agent was slower than the data
            before = state["replicas"]
            state["tick"] = tick
            state["force_alert"] = bool(a.test_alert and stats["ticks"] == 0)
            started = time.perf_counter()
            state = app.invoke(state)                                      # one full pass through the graph = one tick
            duration = time.perf_counter() - started

            after, mode, alert = state["applied"], state["mode"], state["alert_reason"]
            over = state["traffic_now"] > before * state["capacity"]
            if exporter is not None:
                exporter.record_tick(state, before, duration, over)
            stats["ticks"] += 1
            stats["replica_ticks"] += before
            stats["llm_calls"] += mode in (cfg.MODE_UNUSUAL, cfg.MODE_TIMER)
            stats["scale_events"] += after != before
            stats["alerts"] += bool(alert)
            stats["over_capacity"] += over

            if not a.quiet or mode != cfg.MODE_AUTO or after != before or alert:
                h20 = state.get("forecast_h20")
                print(f"minute {state['minute']} | traffic {state['traffic_now']:>7.0f} | +10: {state['forecast']:>7.0f} | "
                      f"+20: {'   n/a' if h20 is None else f'{h20:>6.0f}'} | replicas {before:>3} -> {after:<3} | {mode:<7} | "
                      f"{state['decision']['reason'][:60]}")
            if state["decision"].get("error"):
                print(f"    LLM ERROR (full text): {state['decision']['reason']}")
            if alert:
                print(f"    ALERT: {alert}\n    -> {state['alert_status']}")

            last_minute = tick["minute"]
            if a.max_ticks and stats["ticks"] >= a.max_ticks:
                break
            tick = feed.next_tick(last_minute)
    except KeyboardInterrupt:
        interrupted = True
        print("\nStopped with Ctrl+C.")

    print("\n===== summary =====")
    print(f"ticks processed         : {stats['ticks']}  (skipped because the agent was slower than the data: {stats['skipped']})")
    print(f"LLM calls               : {stats['llm_calls']}  (provider: {cfg.LLM_PROVIDER})")
    print(f"replica changes         : {stats['scale_events']}")
    print(f"alerts                  : {stats['alerts']}")
    print(f"replica-ticks (cost)    : {stats['replica_ticks']}")
    print(f"ticks above capacity    : {stats['over_capacity']}  (new replicas are assumed to start instantly)")
    print(f"files                   : {cfg.DATA_DIR}")
    return 0 if not interrupted else 130


if __name__ == "__main__":
    main()
