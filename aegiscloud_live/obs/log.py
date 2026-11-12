"""
log.py - the ONE logging setup shared by every part of AegisCloud.

ROLE
    Every part (gateway, collector, prediction, loadgen, agent ...) calls  setup("<name>")  once at start-up.
    After that, anything written with the normal  logging.getLogger(...)  lands in two places:
      1. the console of that part (human readable, coloured when it is a real terminal)
      2. data/logs/<name>.jsonl  (one JSON object per line) - this is what the log viewer and the log web page read.

HOW IT WORKS
    - A JSON line looks like {"t": 1731.2, "app": "gateway", "level": "WARNING", "src": "gateway", "msg": "..."}.
    - Each part owns its own file, so two parts never write to the same file (safe on Windows too).
    - Files rotate at 5 MB (2 old copies kept), so logs can never fill the disk.
    - Crashes that nobody catches are written to the log too, so a dying part leaves a reason behind.
    - warn_every(key, seconds, msg) prevents one repeating problem from writing thousands of identical lines.

REMEMBER
    - Level comes from AEGIS_LOG_LEVEL (default INFO). Use DEBUG to see every quiet request.
    - Nothing here changes behaviour of the project; it only writes text.

TEST    python -m pytest tests/test_obs.py -q
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time

import settings as S

_COLORS = {"DEBUG": "\033[90m", "INFO": "\033[0m", "WARNING": "\033[33m", "ERROR": "\033[31m", "CRITICAL": "\033[41m"}
_RESET = "\033[0m"
_last_warn: dict[str, float] = {}


class JsonFormatter(logging.Formatter):
    """One log record -> one JSON line (what the viewer reads)."""

    def __init__(self, app: str):
        super().__init__()
        self.app = app

    def format(self, record: logging.LogRecord) -> str:
        d = {"t": round(record.created, 6), "app": self.app, "level": record.levelname,
             "src": record.name, "msg": record.getMessage()}
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Short human line: 14:03:05 gateway  WARNING  message (coloured on a real terminal)."""

    def __init__(self, app: str, color: bool):
        super().__init__()
        self.app, self.color = app, color

    def format(self, record: logging.LogRecord) -> str:
        clock = time.strftime("%H:%M:%S", time.localtime(record.created))
        line = f"{clock} {self.app:<10} {record.levelname:<8} {record.getMessage()}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return f"{_COLORS.get(record.levelname, '')}{line}{_RESET}" if self.color else line


class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotation can fail on Windows while the viewer has the file open; logging must never crash because of that."""

    def doRollover(self):
        try:
            super().doRollover()
        except OSError:
            pass


def setup(app: str, level: str | None = None) -> logging.Logger:
    """Call once at the start of a part. Returns that part's logger. Safe to call twice."""
    root = logging.getLogger()
    if getattr(root, "_aegis_app", None):
        return logging.getLogger(app)
    lvl = getattr(logging, (level or os.getenv("AEGIS_LOG_LEVEL", "INFO")).upper(), logging.INFO)
    for h in list(root.handlers):                       # replace anything a library or basicConfig added before us
        root.removeHandler(h)
    root.setLevel(lvl)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ConsoleFormatter(app, color=sys.stdout.isatty()))
    root.addHandler(console)
    try:
        S.LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = SafeRotatingFileHandler(S.LOG_DIR / f"{app}.jsonl", maxBytes=5_000_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(JsonFormatter(app))
        root.addHandler(fh)
    except OSError as e:                                # a read-only folder must not stop the part from running
        root.warning("cannot write the log file (%s) - logging to the console only", e)

    for noisy in ("uvicorn.access", "httpx", "httpcore", "watchfiles", "urllib3", "docker", "kubernetes"):
        logging.getLogger(noisy).setLevel(logging.WARNING)   # our middleware already reports requests, in a readable way
    root._aegis_app = app                                # marker so a second setup() does nothing

    def _crash(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logging.getLogger(app).critical("part crashed: %s: %s", exc_type.__name__, exc, exc_info=(exc_type, exc, tb))

    sys.excepthook = _crash
    logging.getLogger(app).info("started (log level %s, file %s)", logging.getLevelName(lvl), S.LOG_DIR / f"{app}.jsonl")
    return logging.getLogger(app)


def warn_every(key: str, seconds: float, logger: logging.Logger, msg: str, *args) -> bool:
    """Log a warning at most once per `seconds` for the same key. Returns True if it was written."""
    now = time.time()
    if now - _last_warn.get(key, 0.0) < seconds:
        return False
    _last_warn[key] = now
    logger.warning(msg, *args)
    return True
