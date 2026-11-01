"""
config.py - every setting of the agent lives here. No logic, only numbers and paths.
Change a number here and the whole graph changes; you never edit the nodes for tuning.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------- paths (shared with the other four parts through settings.py)
import settings as S

AGENT_CODE_DIR = Path(__file__).resolve().parent
load_dotenv(S.ROOT / ".env")                        # keys can live in the project root .env ...
load_dotenv(AGENT_CODE_DIR / ".env")                # ... or in agent/.env (this one wins)
DATA_DIR = S.AGENT_DIR                              # data/agent/
PREDICTIONS_CSV = DATA_DIR / "agent_ticks.csv"      # one row per tick: traffic, forecasts, replicas (the agent's own log)
ACTIONS_CSV = DATA_DIR / "actions.csv"              # one row per decision (last node)
ALERT_DIR = DATA_DIR / "alerts"                     # every urgent email is also saved here as a text file

# ---------------------------------------------------------------- live feed
# One TICK = 5 real seconds = 1 SIMULATED MINUTE. Every "minutes" setting below counts ticks:
# 12 ticks = 1 real minute, 720 ticks = 1 real hour.
APP = "live"                                        # label used in reports and metrics
FORECAST_HORIZON = S.HORIZONS[0]                    # the forecast the agent scales on (+10 simulated minutes)
POLL_SECONDS = 1.0                                  # how often the agent asks the prediction service for a new tick
STATUS_EVERY = 10.0                                 # seconds between "still warming up" messages

# ---------------------------------------------------------------- capacity (same idea as the README)
AVG_REPLICAS = 5          # replicas needed at the average training load -> sets capacity per replica
CAPACITY_PER_REPLICA = None   # None = computed at start from the training data. Or set a number.
MIN_REPLICAS = 1
MAX_REPLICAS = None       # None = computed at start. Or set a number.
MARGIN = 0.10             # headroom: size for demand * (1 + MARGIN)
START_REPLICAS = None     # None = sized for the first traffic value

# ---------------------------------------------------------------- script and timer
SCRIPT_MINUTES = 10       # the script given to the LLM covers the last 10 minutes
TIMER_EVERY = 12          # ticks between normal LLM checks (12 ticks = 1 real minute; use 2 or 3 to test faster)

# ---------------------------------------------------------------- "unusual" rules (plain code, no LLM)
SPIKE_RATIO = 1.3         # forecast is 30% higher than the previous minute's forecast
SPIKE_MIN_LOAD = 0.5      # ...but only if the forecast is above 50% of current capacity (ignores noise at low load)
NEAR_CAPACITY = 0.95      # forecast or traffic is above 95% of current capacity
ERROR_LIMIT = 0.5         # forecast error (WAPE) over the last 5 minutes is above 50%
ERROR_WINDOW = 5          # how many minutes the error check looks at
UNUSUAL_COOLDOWN = 6      # after an unusual LLM call, wait this many minutes before the next one

# ---------------------------------------------------------------- auto_scale (plain rule, no LLM)
DOWN_WAIT = 10            # scale up at once, but scale down only when the last 10 minutes all needed fewer replicas

# ---------------------------------------------------------------- guardrail (applied to every decision)
MAX_UP_MULTIPLIER = 2.0       # at most double the replicas in one decision (and always allowed +2)
MAX_DOWN_FRACTION = 0.25      # at most remove 25% of the replicas in one decision

# ---------------------------------------------------------------- alert: urgent email to a human (node alert_human)
# An alert fires when: the LLM asks for a human, the LLM call fails, traffic is above capacity
# ALERT_MISS_MINUTES minutes in a row, or we are at max replicas and still overloaded.
ALERT_COOLDOWN = 120       # minutes between two alerts (stops email spam)
ALERT_MISS_MINUTES = 2    # "overloaded for this many minutes in a row"
ALERT_LOG_MINUTES = 60    # the email carries the last hour of logs
ESCALATE_MIN_LOAD = 0.9   # an LLM "escalate" only becomes an alert if max(traffic, forecast) is above 90% of capacity (first guess, tune it)
ALERT_SEND_EMAIL = True  # False = only save the email in data/alerts/. True = also send it by SMTP
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465           # SSL
SMTP_PORT_STARTTLS = 587  # second way, tried automatically if the SSL connection fails
EMAIL_TIMEOUT = 20        # seconds
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")        # the address that sends the alert
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")    # Gmail: an "app password", NOT your normal password
EMAIL_TO = os.getenv("EMAIL_TO", "")                # the human who gets the alert (comma-separated for several)

# ---------------------------------------------------------------- LLM
# "fake"    = rule-based stand-in, free, use it first to test the whole graph
# "gemini"  = Google Gemini, needs env var GEMINI_API_KEY
# "mistral" = Mistral Small, needs env var MISTRAL_API_KEY
LLM_PROVIDER = "fake"
GEMINI_MODEL = "gemini-3.5-flash-lite"       # first choice: light model, rarely overloaded
GEMINI_FALLBACK_MODEL = "gemini-3.8-flash"   # used automatically if the first one fails. "" = no fallback
MISTRAL_MODEL = "mistral-small-latest"
LLM_TIMEOUT = 30          # seconds to wait for the LLM before giving up (the agent then holds)
LLM_RETRIES = 2           # extra tries when the server is busy (503/429) or the connection drops
LLM_RETRY_WAIT = 2        # seconds to wait before a retry (2 s, then 4 s)
LLM_FAILURES_BEFORE_ALERT = 2   # email a human only after this many LLM failures IN A ROW (one 503 is not an emergency)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")

# ---------------------------------------------------------------- the three modes (used by trigger_check and graph)
MODE_UNUSUAL = "unusual"
MODE_TIMER = "timer"
MODE_AUTO = "auto"