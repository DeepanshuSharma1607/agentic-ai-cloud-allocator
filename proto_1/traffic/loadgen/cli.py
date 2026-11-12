"""
cli.py - control the request sender from a terminal (the dashboard does the same through the same API).

  python -m traffic.loadgen.cli status
  python -m traffic.loadgen.cli start fixed --n 300            # 300 requests every 5 s (= 60 per second)
  python -m traffic.loadgen.cli start random --lo 50 --hi 400
  python -m traffic.loadgen.cli start pattern --scale 1.5      # the daily curve, 1.5x bigger
  python -m traffic.loadgen.cli start replay --start 18720     # replay real rows of the training data
  python -m traffic.loadgen.cli schedule --in 120 --duration 300 fixed --n 500   # in 2 min, for 5 min
  python -m traffic.loadgen.cli stop
"""
import argparse
import json

import httpx

import settings as S


def call(method, path, body=None):
    r = httpx.request(method, f"{S.URL_LOADGEN}{path}", json=body, timeout=10)
    if r.status_code >= 400:
        raise SystemExit(f"error {r.status_code}: {r.text}")
    return r.json()


def add_plan_args(p):
    p.add_argument("mode", choices=["idle", "fixed", "random", "pattern", "replay"])
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--lo", type=int, default=50)
    p.add_argument("--hi", type=int, default=200)
    p.add_argument("--smooth", type=float, default=0.0)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--noise", type=float, default=0.25)
    p.add_argument("--burst-prob", type=float, default=0.01)
    p.add_argument("--burst-mult", type=float, default=3.0)
    p.add_argument("--start", type=int, default=0)


def plan_from(a):
    return {"mode": a.mode, "n": a.n, "lo": a.lo, "hi": a.hi, "smooth": a.smooth, "scale": a.scale, "noise": a.noise,
            "burst_prob": a.burst_prob, "burst_mult": a.burst_mult, "start": a.start}


def main():
    p = argparse.ArgumentParser(description="Control the AegisCloud request sender")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("stop")
    add_plan_args(sub.add_parser("start"))
    sch = sub.add_parser("schedule")
    sch.add_argument("--in", dest="in_seconds", type=float, default=0.0, help="start after this many seconds")
    sch.add_argument("--at", help="start at this local time, e.g. 2026-10-30T14:30:00")
    sch.add_argument("--duration", type=float, required=True, help="seconds")
    add_plan_args(sch)
    a = p.parse_args()
    if a.cmd == "status":
        out = call("GET", "/status")
    elif a.cmd == "stop":
        out = call("POST", "/stop", {"cancel_schedule": True})
    elif a.cmd == "start":
        out = call("POST", "/start", plan_from(a))
    else:
        out = call("POST", "/schedule", {"plan": plan_from(a), "duration_s": a.duration,
                                         "in_seconds": a.in_seconds, "start_at": a.at})
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
