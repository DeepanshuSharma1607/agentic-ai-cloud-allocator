"""
obs/ - "observability": everything that lets you SEE what the system is doing.

  log.py         one shared logging setup used by every part (console + a JSON-lines file per part)
  middleware.py  logs web requests without flooding (individual lines for rare calls, a summary for busy ones)
  problems.py    turns a raw error message into a plain-English cause
  store.py       reads the log files back (used by the terminal viewer and the web page)
  viewer.py      live logs in a terminal:      python -m obs.viewer --follow
  web.py         live logs in a browser:       python -m obs.web      ->  http://localhost:8006
"""
