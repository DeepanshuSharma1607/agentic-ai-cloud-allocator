"""
store.py - reads the log files back, merged into one time-ordered stream.

ROLE
    The terminal viewer (viewer.py) and the log web page (web.py) both need "give me the recent log lines, from all parts,
    in time order, filtered". This file is that one reader, so both show exactly the same thing.

HOW IT WORKS
    - Each part writes data/logs/<part>.jsonl (see log.py). read() loads the tail of every file, filters, and merges by time.
    - Follower remembers how far it has read in each file, so a live view only fetches NEW lines.
    - app_status() gives one row per part: last time it logged, and how many warnings/errors it wrote recently.
      A part that has gone quiet is how you notice it has stopped.
    - problems() groups recent warnings/errors, counts repeats and attaches the plain-English cause (problems.py).

REMEMBER
    - Lines that are not valid JSON (for example half-written at the moment of reading) are skipped, never crash the reader.
    - Only the last ~2 MB of each file is read for history, so even a big log opens instantly.

TEST    python -m pytest tests/test_obs.py -q
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import settings as S
from obs.problems import explain

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
TAIL_BYTES = 2_000_000


def log_files() -> list[Path]:
    return sorted(S.LOG_DIR.glob("*.jsonl")) if S.LOG_DIR.exists() else []


def _parse(line: str) -> dict | None:
    try:
        d = json.loads(line)
        return d if isinstance(d, dict) and "t" in d and "msg" in d else None
    except ValueError:
        return None


def _keep(d: dict, apps, min_level: int, q: str) -> bool:
    if apps and d.get("app") not in apps:
        return False
    if LEVELS.get(d.get("level", "INFO"), 20) < min_level:
        return False
    return not q or q.lower() in (d.get("msg", "") + " " + d.get("app", "")).lower()


def read(since: float = 0.0, apps=None, level: str = "INFO", q: str = "", limit: int = 300) -> list[dict]:
    """Newest `limit` entries with time > since, oldest first."""
    mn, out = LEVELS.get(level.upper(), 20), []
    for path in log_files():
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - TAIL_BYTES))
                raw = f.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        for line in raw.splitlines():
            d = _parse(line)
            if d and d["t"] > since and _keep(d, apps, mn, q):
                out.append(d)
    out.sort(key=lambda d: d["t"])
    return out[-limit:]


class Follower:
    """Remembers a read position per file; poll() returns only lines written since the last call."""

    def __init__(self, apps=None, level: str = "INFO", q: str = "", from_start: bool = False):
        self.apps, self.mn, self.q = apps, LEVELS.get(level.upper(), 20), q
        self.pos: dict[Path, int] = {}
        self.from_start = from_start

    def poll(self) -> list[dict]:
        out = []
        for path in log_files():
            try:
                size = path.stat().st_size
                start = self.pos.get(path, 0 if self.from_start else size)
                if size < start:                                   # file was rotated: read the new one from the top
                    start = 0
                with open(path, "rb") as f:
                    f.seek(start)
                    chunk = f.read()
                self.pos[path] = start + len(chunk)
            except OSError:
                continue
            text = chunk.decode("utf-8", errors="replace")
            if not text.endswith("\n"):                            # last line still being written: leave it for next poll
                keep = text.rfind("\n") + 1
                self.pos[path] -= len(text[keep:].encode("utf-8"))
                text = text[:keep]
            for line in text.splitlines():
                d = _parse(line)
                if d and _keep(d, self.apps, self.mn, self.q):
                    out.append(d)
        self.from_start = False
        out.sort(key=lambda d: d["t"])
        return out


def app_status(window_s: float = 300.0) -> list[dict]:
    """One row per part: when it last logged, and how many warnings / errors in the last `window_s` seconds."""
    now, rows = time.time(), []
    for path in log_files():
        last, warns, errs = 0.0, 0, 0
        for d in read(apps={path.stem}, level="DEBUG", limit=5000):
            last = max(last, d["t"])
            if now - d["t"] <= window_s:
                lv = LEVELS.get(d.get("level"), 20)
                warns += lv == 30
                errs += lv >= 40
        rows.append({"app": path.stem, "last_seen_s": round(now - last, 1) if last else None, "warnings": warns, "errors": errs})
    return rows


def _shape(msg: str) -> str:
    """Numbers differ between repeats of the same problem; replace them so repeats group together."""
    return re.sub(r"\d+(\.\d+)?", "#", msg)[:160]


def problems(window_s: float = 900.0) -> list[dict]:
    """Recent warnings/errors, grouped, newest first, each with a plain-English cause when we know one."""
    now, groups = time.time(), {}
    for d in read(level="WARNING", limit=2000):
        if now - d["t"] > window_s:
            continue
        g = groups.setdefault((d["app"], _shape(d["msg"])), {"app": d["app"], "level": d["level"], "msg": d["msg"], "count": 0, "last": 0.0})
        g["count"] += 1
        g["last"] = max(g["last"], d["t"])
        g["msg"] = d["msg"]
    out = sorted(groups.values(), key=lambda g: g["last"], reverse=True)
    for g in out:
        g["why"] = explain(g["msg"])
    return out
