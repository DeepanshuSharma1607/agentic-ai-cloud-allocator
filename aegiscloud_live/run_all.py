"""
run_all.py - starts the whole system with one command and stops it with Ctrl+C.

    python run_all.py                       # target app + prediction + collector + request sender + agent + dashboard
    python run_all.py --demo                # first creates FAKE seed data and FAKE models (only to see it work)
    python run_all.py --no-agent            # without the LangGraph agent
    python run_all.py --provider gemini     # agent uses the real LLM (key in .env)

Then open the dashboard: http://localhost:8501
Logs of every part: data/logs/<part>.log
"""
import argparse
import os
import subprocess
import sys
import time

import httpx

import settings as S

PY = sys.executable
ROOT = S.ROOT


def has_models():
    return any(S.MODELS_DIR.rglob("*.pt"))


def uvicorn(module, port):
    return [PY, "-m", "uvicorn", module, "--host", S.HOST, "--port", str(port), "--log-level", "warning"]


def wait_healthy(name, url, proc, seconds=60):
    end = time.time() + seconds
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def main():
    p = argparse.ArgumentParser(description="Start the whole AegisCloud live system")
    p.add_argument("--demo", action="store_true", help="create FAKE seed data and models first if they are missing")
    p.add_argument("--no-agent", action="store_true")
    p.add_argument("--no-frontend", action="store_true")
    p.add_argument("--provider", choices=["fake", "gemini", "mistral"], default=None, help="LLM used by the agent")
    p.add_argument("--timer", type=int, default=None, help="agent: ticks between LLM checks")
    a = p.parse_args()

    if not has_models():
        if a.demo:
            print("No model found - creating FAKE demo data and models (this takes about a minute) ...")
            subprocess.run([PY, str(ROOT / "tools" / "make_demo_assets.py")], check=True, cwd=ROOT)
        else:
            raise SystemExit(f"No .pt model in {S.MODELS_DIR}.\n"
                             "Copy your lstm_requests_forecaster.pt there (and metrics_combined.csv to data/seed/),\n"
                             "or run `python run_all.py --demo` to try the system with FAKE demo assets.")
    if not S.SEED_CSV.exists():
        print(f"NOTE: {S.SEED_CSV} not found. Forecasts will start only after 1,441 live ticks (about 2 hours).")

    S.LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""), PYTHONUNBUFFERED="1")
    procs = []
    from obs.web import PORT as PORT_LOGS

    def launch(name, cmd):
        log = open(S.LOG_DIR / f"{name}.log", "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        procs.append((name, proc, log))
        return proc

    try:
        plan = [("target_app", uvicorn("traffic.target_app.app:app", S.PORT_TARGET), f"{S.URL_TARGET}/health"),
                ("prediction", uvicorn("prediction.server:app", S.PORT_PREDICTION), f"{S.URL_PREDICTION}/health"),
                ("collector", uvicorn("traffic.collector.app:app", S.PORT_COLLECTOR), f"{S.URL_COLLECTOR}/health"),
                ("loadgen", uvicorn("traffic.loadgen.app:app", S.PORT_LOADGEN), f"{S.URL_LOADGEN}/health")]
        launch("logs", [PY, "-m", "obs.web"])                                        # live log page, started first
        print("open      counter     http://localhost:8001   (APP 1: big live request counter)")
        print("open      sender      http://localhost:8002   (APP 2: type a number, press Start, or run the demo)")
        print(f"started  live logs   http://localhost:{PORT_LOGS}   (terminal: python -m obs.viewer --follow)")
        for name, cmd, health in plan:
            proc = launch(name, cmd)
            ok = wait_healthy(name, health, proc)
            print(f"{'started' if ok else 'FAILED '}  {name:<11} {health.rsplit('/', 1)[0]}")
            if not ok:
                raise SystemExit(f"{name} did not start - see {S.LOG_DIR / (name + '.log')}")
        if not a.no_agent:
            cmd = [PY, "-m", "agent.run", "--quiet"]
            if a.provider:
                cmd += ["--provider", a.provider]
            if a.timer:
                cmd += ["--timer", str(a.timer)]
            launch("agent", cmd)
            print("started  agent       (log: data/logs/agent.log)")
        if not a.no_frontend:
            launch("frontend", [PY, "-m", "streamlit", "run", str(ROOT / "frontend" / "app.py"), "--server.port", str(S.PORT_FRONTEND),
                                "--server.headless", "true", "--browser.gatherUsageStats", "false"])
            print(f"started  dashboard   http://localhost:{S.PORT_FRONTEND}")
        print("\nEverything is running. Press Ctrl+C to stop all parts.\n")
        while True:
            time.sleep(2)
            for name, proc, _ in procs:
                if proc.poll() is not None:
                    print(f"{name} stopped (exit code {proc.returncode}) - see {S.LOG_DIR / (name + '.log')}")
                    procs[:] = [x for x in procs if x[1] is not proc]
                    break
    except KeyboardInterrupt:
        print("\nStopping ...")
    finally:
        for name, proc, _ in procs:
            if proc.poll() is None:
                proc.terminate()
        for name, proc, log in procs:
            try:
                proc.wait(timeout=6)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                proc.kill()
            log.close()


if __name__ == "__main__":
    main()
