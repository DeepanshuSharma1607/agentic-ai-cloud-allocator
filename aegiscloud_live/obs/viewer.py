"""
viewer.py - watch the logs of ALL parts in one terminal.

ROLE
    Open a second (or third) terminal while the system runs and you see what every part is doing, merged in time order -
    like the console of a normal backend, but for the whole system at once.

USAGE
    python -m obs.viewer                      # last 40 lines, then exit
    python -m obs.viewer --follow             # keep watching new lines (Ctrl+C to stop)
    python -m obs.viewer -f --level warning   # only problems
    python -m obs.viewer -f --app gateway,agent
    python -m obs.viewer --grep "scale"       # only lines containing a word

HOW IT WORKS
    Reads data/logs/*.jsonl through store.py. Warnings and errors get an extra "why:" line with the plain-English
    cause from problems.py.

REMEMBER
    - It only READS the logs; it can run on any terminal on the same machine and never disturbs the system.
    - Colours: grey = debug, white = info, yellow = warning, red = error.

TEST    python -m pytest tests/test_obs.py -q
"""
from __future__ import annotations

import argparse
import sys
import time

from obs import store
from obs.problems import explain

COLORS = {"DEBUG": "\033[90m", "INFO": "\033[0m", "WARNING": "\033[33m", "ERROR": "\033[31m", "CRITICAL": "\033[41m"}


def render(d: dict, color: bool = True) -> str:
    """One log entry -> printable text (with the 'why' line for warnings and errors)."""
    clock = time.strftime("%H:%M:%S", time.localtime(d["t"]))
    line = f"{clock} {d.get('app', '?'):<10} {d.get('level', 'INFO'):<8} {d['msg']}"
    if d.get("exc"):
        line += "\n" + d["exc"]
    if store.LEVELS.get(d.get("level"), 20) >= 30:
        why = explain(d["msg"])
        if why:
            line += f"\n{'':>20}-> why: {why}"
    return f"{COLORS.get(d.get('level'), '')}{line}\033[0m" if color else line


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Live logs of all AegisCloud parts")
    ap.add_argument("-f", "--follow", action="store_true", help="keep watching for new lines")
    ap.add_argument("--app", default="", help="comma-separated part names, e.g. gateway,agent (default: all)")
    ap.add_argument("--level", default="INFO", help="DEBUG, INFO, WARNING or ERROR (default INFO)")
    ap.add_argument("--grep", default="", help="show only lines containing this text")
    ap.add_argument("--last", type=int, default=40, help="how many past lines to show first (default 40)")
    ap.add_argument("--no-color", action="store_true")
    a = ap.parse_args(argv)
    apps = {x.strip() for x in a.app.split(",") if x.strip()} or None
    color = sys.stdout.isatty() and not a.no_color

    if not store.log_files():
        print(f"No logs yet in {store.S.LOG_DIR}. Start the system first (python run_live.py).")
        if not a.follow:
            return 0
    for d in store.read(apps=apps, level=a.level, q=a.grep, limit=a.last):
        print(render(d, color))
    if not a.follow:
        return 0
    print("--- watching for new lines (Ctrl+C to stop) ---")
    fol = store.Follower(apps, a.level, a.grep)
    fol.poll()                                           # start at the end of every file; history was printed above
    try:
        while True:
            for d in fol.poll():
                print(render(d, color), flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
