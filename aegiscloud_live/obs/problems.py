"""
problems.py - turns a raw error line into a plain-English "what is probably wrong".

ROLE
    The log web page and the terminal viewer call explain(message) for every WARNING/ERROR line and show the answer
    under it. This is how a non-technical person can tell "Docker is off" from "model file missing" at a glance.

HOW IT WORKS
    A short list of (pattern, explanation) rules. The first rule whose pattern is found in the message wins.
    No AI, no network: it is a lookup table, so it is fast and always works.

REMEMBER
    - To teach it a new problem, add one line to RULES. Nothing else needs to change.
    - It only EXPLAINS. It never hides or changes the original message.

TEST    python -m pytest tests/test_obs.py -q
"""
from __future__ import annotations

import re

RULES: list[tuple[str, str]] = [
    (r"Docker is not running|Cannot create a Docker client|docker.*(Connection|FileNotFound)",
     "Docker is not running. Start Docker Desktop, or start the system with --backend process."),
    (r"Kubernetes is not reachable|No Kubernetes cluster",
     "Kubernetes cluster not found. Start k3d / Docker Desktop Kubernetes first (see infra/README.md)."),
    (r"no ready replica",
     "Requests arrived while no replica was Ready (replicas still starting, or all of them failed). Check the cluster events."),
    (r"replica refused or failed|replica call failed",
     "A replica did not answer correctly. It may be overloaded, still starting, or crashed."),
    (r"not Ready after|did not become ready|START_TIMEOUT",
     "A replica took too long to start and is being replaced. Check Docker / image build."),
    (r"prediction service unreachable|prediction service answered",
     "The collector cannot reach the prediction service (port 8004). Check that it is running. Data rows are still saved."),
    (r"target app unreachable|gateway unreachable|could not reach the gateway",
     "The front door (gateway / target app, port 8001) is not answering. Check that it is running."),
    (r"could not load .*\.pt|No .pt model|model file",
     "A forecast model file is missing or broken. Check prediction/models/."),
    (r"LLM error|Gemini|quota|API key|RESOURCE_EXHAUSTED",
     "The agent's LLM call failed (key, quota or network). The agent holds the current replica count until it works."),
    (r"email failed|SMTP|EMAIL_",
     "Email could not be sent. Check the EMAIL_ lines in .env. The alert is still saved as a file."),
    (r"Address already in use|10048|port .* in use",
     "A port is already taken by another program. Stop the old run, or change the port."),
    (r"ConnectError|Connection refused|ConnectionRefused|Max retries exceeded",
     "A part tried to talk to another part that is not running (yet)."),
    (r"MemoryError|out of memory|OOMKilled",
     "The machine or container ran out of memory. Lower the replica count or the memory per replica."),
    (r"plan error",
     "The sender's traffic plan is invalid, so it sent nothing this tick. Check the plan settings."),
    (r"tick failed",
     "The prediction service could not process one data row. See the lines above it for the reason."),
    (r"part crashed",
     "This part stopped because of an unexpected error. The line above shows the exception."),
]
_COMPILED = [(re.compile(p, re.I), text) for p, text in RULES]


def explain(message: str) -> str | None:
    """Return a plain-English cause for a log message, or None if no rule matches."""
    for rx, text in _COMPILED:
        if rx.search(message or ""):
            return text
    return None
