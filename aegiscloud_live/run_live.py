"""
run_live.py - starts the whole system with REAL replicas (Docker containers or Kubernetes Pods) and stops it with Ctrl+C.

    python run_live.py                           # Docker containers (default); the replica image is built on first start
    python run_live.py --backend process         # replicas as local processes (no Docker needed, no CPU / memory limits)
    python run_live.py --backend k8s             # Kubernetes Pods (cluster must be running, see infra/README.md)
    python run_live.py --tick 10                 # 10 real seconds per simulated minute (also changeable on the dashboard)
    python run_live.py --provider gemini         # agent uses the real LLM (key in .env)

It does what run_all.py does, with three differences: the old demo target app is replaced by the GATEWAY (+ real replicas),
the agent is started through infra.agent_real (real scaling), and a small supervisor API (port 8005) lets the dashboard
apply a new tick length / device profile by restarting the parts that need it.
Dashboard: http://localhost:8501   Live logs (browser): http://localhost:8006   Live logs (terminal): python -m obs.viewer --follow
Log files: data/logs/<part>.jsonl (structured) and data/logs/<part>.log (raw console text)
"""
import argparse
import os
import subprocess
import sys
import threading
import time

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

import settings as S
from infra import config as C
from infra import device as D
from infra import runtime as R
from infra.backends import get_backend
from obs.web import PORT as PORT_LOGS

PY, ROOT = sys.executable, S.ROOT


def uv(module, port):
    return [PY, "-m", "uvicorn", module, "--host", S.HOST, "--port", str(port), "--log-level", "warning"]


class Stack:
    def __init__(self, args):
        self.args = args
        self.procs: dict[str, tuple] = {}
        self.lock = threading.Lock()
        S.LOG_DIR.mkdir(parents=True, exist_ok=True)

    def env(self):
        rt = R.load()
        return dict(os.environ, PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""), PYTHONUNBUFFERED="1",
                    AEGIS_TICK_SECONDS=str(rt["tick_seconds"]))

    def cmd(self, name, keep_files=False):
        a = self.args
        if name == "gateway":
            return uv("infra.gateway:app", S.PORT_TARGET), f"{S.URL_TARGET}/health"
        if name == "prediction":
            return uv("prediction.server:app", S.PORT_PREDICTION), f"{S.URL_PREDICTION}/health"
        if name == "collector":
            return uv("traffic.collector.app:app", S.PORT_COLLECTOR), f"{S.URL_COLLECTOR}/health"
        if name == "logs":
            return [PY, "-m", "obs.web"], f"http://{S.HOST}:{PORT_LOGS}/health"
        if name == "loadgen":
            return uv("traffic.loadgen.app:app", S.PORT_LOADGEN), f"{S.URL_LOADGEN}/health"
        if name == "agent":
            cmd = [PY, "-m", "infra.agent_real", "--quiet", "--no-metrics"]
            if a.provider:
                cmd += ["--provider", a.provider]
            if a.timer:
                cmd += ["--timer", str(a.timer)]
            if keep_files:
                cmd += ["--keep-files"]
            return cmd, None
        if name == "frontend":
            return [PY, "-m", "streamlit", "run", str(ROOT / "frontend" / "app.py"), "--server.port", str(S.PORT_FRONTEND),
                    "--server.headless", "true", "--browser.gatherUsageStats", "false"], None
        raise KeyError(name)

    @staticmethod
    def open_log(name):
        """Raw console log of one part. APPENDS (a restart used to wipe it); it is moved aside only when it passes 10 MB."""
        path = S.LOG_DIR / f"{name}.log"
        try:
            if path.exists() and path.stat().st_size > 10_000_000:
                path.replace(path.with_suffix(".log.1"))
        except OSError:
            pass
        log = open(path, "a", encoding="utf-8")
        log.write(f"\n===== {name} started {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        log.flush()
        return log

    def start(self, name, keep_files=False, wait=True):
        cmd, health = self.cmd(name, keep_files)
        log = self.open_log(name)
        proc = subprocess.Popen(cmd, cwd=ROOT, env=self.env(), stdout=log, stderr=subprocess.STDOUT)
        with self.lock:
            self.procs[name] = (proc, log)
        ok = True
        if health and wait:
            ok = False
            end = time.time() + 90
            while time.time() < end and proc.poll() is None:
                try:
                    if httpx.get(health, timeout=1).status_code == 200:
                        ok = True
                        break
                except Exception:
                    pass
                time.sleep(0.4)
        return ok

    def stop(self, name):
        with self.lock:
            rec = self.procs.pop(name, None)
        if not rec:
            return
        proc, log = rec
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
        log.close()

    def restart(self, name):
        self.stop(name)
        return self.start(name, keep_files=True)

    def status(self):
        with self.lock:
            return {n: ("running" if p.poll() is None else f"stopped ({p.returncode})") for n, (p, _) in self.procs.items()}

    def stop_all(self):
        for name in list(self.procs):
            self.stop(name)


# ====================================================================== supervisor API (used by the dashboard)
class Apply(BaseModel):
    tick_seconds: float | None = None
    device: dict | None = None


def make_api(stack: Stack):
    api = FastAPI(title="AegisCloud supervisor")

    @api.get("/health")
    def health():
        return {"ok": True}

    @api.get("/status")
    def status():
        return {"parts": stack.status(), "runtime": R.load()}

    @api.post("/apply")
    def apply(body: Apply):
        """New tick length and / or device profile: store them, rebuild the replicas, restart collector, load sender and agent."""
        dev = D.Device.from_dict(body.device) if body.device else D.load_device()
        tick = float(body.tick_seconds or R.load()["tick_seconds"])
        tick = min(max(tick, 1.0), 600.0)
        D.save_device(dev)
        rt = R.apply_settings(dev, tick, stack.args.backend)
        try:
            httpx.post(f"{S.URL_TARGET}/infra/reload", json={"burn_ms": rt["effective_burn_ms"]}, timeout=60)
        except Exception as e:
            return {"ok": False, "detail": f"gateway did not accept the new device profile: {e}", "runtime": rt}
        restarted = [n for n in ("collector", "loadgen", "agent") if n in stack.procs and stack.restart(n) is not None]
        return {"ok": True, "runtime": rt, "restarted": restarted, "limits": dev.limits()}

    @api.post("/restart/{name}")
    def restart(name: str):
        if name not in stack.procs:
            return {"ok": False, "detail": "unknown part"}
        return {"ok": bool(stack.restart(name))}

    return api


def main():
    p = argparse.ArgumentParser(description="Start AegisCloud live with real replicas")
    p.add_argument("--backend", choices=["docker", "k8s", "process"], default=None)
    p.add_argument("--tick", type=float, default=None, help="real seconds per simulated minute (default: saved value, else 5)")
    p.add_argument("--no-agent", action="store_true")
    p.add_argument("--no-frontend", action="store_true")
    p.add_argument("--provider", choices=["fake", "gemini", "mistral"], default=None)
    p.add_argument("--timer", type=int, default=None, help="agent: ticks between LLM checks")
    a = p.parse_args()

    saved = R.load()
    a.backend = a.backend or saved.get("backend") or "docker"
    tick = a.tick or float(saved["tick_seconds"])
    if not any(S.MODELS_DIR.rglob("*.pt")):
        raise SystemExit(f"No .pt model in {S.MODELS_DIR}. Copy your lstm_requests_forecaster.pt there first (or use run_all.py --demo once).")

    dev = D.load_device()
    D.save_device(dev)
    rt = R.apply_settings(dev, tick, a.backend)
    lim = dev.limits()
    print(f"backend {a.backend} | tick {tick} s | device {dev.cores:g} cores / {dev.ram_mb} MB -> max {lim['max_replicas']} replicas "
          f"(limited by {lim['binding']}) | each replica {dev.cpu_per_replica:g} core, {dev.mem_per_replica_mb} MB | "
          f"app weight {rt['effective_burn_ms']} ms/request | capacity {rt['capacity_per_tick']}/tick ({rt['capacity_source']})")
    for w in dev.warnings():
        print("  WARNING:", w)
    try:
        backend = get_backend(a.backend)
        backend.prepare({"cpu_cores": dev.cpu_per_replica, "mem_mb": dev.mem_per_replica_mb, "burn_ms": rt["effective_burn_ms"],
                         "max_replicas": lim["max_replicas"]}, build=True)
    except RuntimeError as e:
        raise SystemExit(f"\n{e}")

    stack = Stack(a)
    server = None
    try:
        for name in ("logs", "gateway", "prediction", "collector", "loadgen"):          # logs first: you can watch the others start
            ok = stack.start(name)
            print(f"{'started' if ok else 'FAILED '}  {name:<11}")
            if not ok:
                raise SystemExit(f"{name} did not start - see {S.LOG_DIR / (name + '.log')}")
        if not a.no_agent:
            stack.start("agent", wait=False)
            print("started  agent       (log: data/logs/agent.log)")
        if not a.no_frontend:
            stack.start("frontend", wait=False)
            print(f"started  dashboard   http://localhost:{S.PORT_FRONTEND}")
        server = uvicorn.Server(uvicorn.Config(make_api(stack), host=S.HOST, port=C.PORT_SUPERVISOR, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        print(f"open      counter     http://localhost:{S.PORT_TARGET}   (APP 1: big live request counter)")
        print(f"open      sender      http://localhost:{S.PORT_LOADGEN}   (APP 2: type a number, press Start, or run the demo)")
        print(f"started  live logs   http://localhost:{PORT_LOGS}   (terminal: python -m obs.viewer --follow)")
        print("\nEverything is running. Press Ctrl+C to stop all parts (replicas are removed too).\n")
        while True:
            time.sleep(2)
            for name, state in stack.status().items():
                if state != "running":
                    print(f"{name} {state} - see {S.LOG_DIR / (name + '.log')}")
                    stack.procs.pop(name, None)
    except KeyboardInterrupt:
        print("\nStopping ...")
    finally:
        if server:
            server.should_exit = True
        stack.stop_all()                          # the gateway's shutdown removes the replicas
        try:
            backend.cleanup()                     # and again, in case the gateway was killed
        except Exception:
            pass


if __name__ == "__main__":
    main()
