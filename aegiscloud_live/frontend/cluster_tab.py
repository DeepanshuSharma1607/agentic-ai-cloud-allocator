"""
cluster_tab.py - the two dashboard tabs for the real replicas.

  render_cluster()  one tile per REAL replica (Starting / Ready / Draining) with its real CPU and memory, the split of the
                    device's CPU / RAM, live charts, real startup times and every scale event.
  render_device()   enter the machine (cores, RAM), the per-replica share, the app weight and the tick length; see the limits
                    that follow; Apply; run the capacity calibration.

Nothing here is simulated: every number comes from the gateway (/infra/...), data/infra/*.csv, or plain arithmetic on the form.
When a source is missing the panel says so instead of drawing something.
"""
from __future__ import annotations

import html
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import settings as S
from frontend import charts
from frontend import data_access as D
from infra import config as C
from infra import device as DV
from infra import runtime as R

GATEWAY = C.URL_GATEWAY
STATE_COLOR = {"ready": charts.TEAL, "starting": charts.AMBER, "draining": charts.VIOLET, "terminating": charts.VIOLET, "failed": charts.RED}
TZ = datetime.now().astimezone().tzinfo


def _time(df, col="ts"):
    return pd.to_datetime(df[col], unit="s", utc=True).dt.tz_convert(TZ)


def _timechart(fig, height=250, ytitle=""):
    charts._base(fig, height, ytitle)
    fig.update_layout(xaxis_title="time")
    return fig


# ================================================================== CLUSTER
def _tiles(pods):
    if not pods:
        return "<i>no replicas yet</i>"
    cells = []
    for p in pods:
        color = STATE_COLOR.get(p["state"], charts.INK)
        cpu_lim = (p.get("cpu_limit_cores") or 0) * 100
        cpu = p.get("cpu_pct")
        cpu_w = 0 if cpu is None or not cpu_lim else min(100, cpu / cpu_lim * 100)
        mem, mem_lim = p.get("mem_mb"), p.get("mem_limit_mb")
        mem_w = 0 if mem is None or not mem_lim else min(100, mem / mem_lim * 100)
        cpu_txt = "no data" if cpu is None else (f"{cpu:.0f}% of 1 core" + (f" (limit {cpu_lim:.0f}%)" if cpu_lim else ""))
        mem_txt = "no data" if mem is None else f"{mem:.0f} MB" + (f" / {mem_lim:.0f}" if mem_lim else "")
        extra = f"starting for {p['age_s']:.0f} s" if p["state"] == "starting" else (f"up in {p['startup_s']:.1f} s" if p.get("startup_s") else p["state"])
        cells.append(
            f'<div class="tile{" fresh" if p["age_s"] < 4 else ""}" style="border-top:4px solid {color}">'
            f'<b>{html.escape(p["name"][-10:])}</b><span class="st" style="color:{color}">{p["state"]}</span>'
            f'<div class="lab">CPU {cpu_txt}</div><div class="bar"><div style="width:{cpu_w:.0f}%;background:{charts.BLUE}"></div></div>'
            f'<div class="lab">memory {mem_txt}</div><div class="bar"><div style="width:{mem_w:.0f}%;background:{charts.VIOLET}"></div></div>'
            f'<div class="lab">{extra} | in flight {p.get("inflight", 0)}</div></div>')
    return '<div class="grid">' + "".join(cells) + "</div>"


CSS = """<style>
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px;margin:6px 0 10px}
.tile{background:#fff;border:1px solid #D9DEE3;border-radius:4px;padding:8px 10px;font-size:.82rem}
.tile.fresh{animation:pop .6s ease-out}.tile b{font-size:.9rem}.tile .st{float:right;font-weight:600;font-size:.78rem}
.tile .lab{color:#55616c;margin-top:6px;font-size:.76rem}.bar{height:7px;background:#E8ECEF;border-radius:3px;overflow:hidden;margin-top:2px}
.bar div{height:100%;transition:width .8s}
@keyframes pop{from{transform:scale(.85);opacity:.2}to{transform:scale(1);opacity:1}}
</style>"""


def _split_bars(state):
    dev = state["device"]
    ready = [p for p in state["pods"] if p["state"] in ("ready", "draining", "starting")]
    cpu_alloc = sum((p.get("cpu_limit_cores") or dev["cpu_per_replica"]) for p in ready)
    cpu_used = sum((p.get("cpu_pct") or 0) for p in ready) / 100.0
    mem_alloc = sum((p.get("mem_limit_mb") or dev["mem_per_replica_mb"]) for p in ready)
    mem_used = sum((p.get("mem_mb") or 0) for p in ready)
    a, b = st.columns(2)
    for col, title, reserve, alloc, used, total, unit in (
            (a, "CPU split (cores)", dev["reserve_cores"], cpu_alloc, cpu_used, dev["cores"], "cores"),
            (b, "Memory split (MB)", dev["reserve_ram_mb"], mem_alloc, mem_used, dev["ram_mb"], "MB")):
        fig = go.Figure()
        free = max(total - reserve - alloc, 0)
        for name, val, color in (("reserved for the other services", reserve, charts.GRID), ("replicas: really used", used, charts.BLUE),
                                 ("replicas: allocated, not used", max(alloc - used, 0), "#9DB7DA"), ("free", free, "#F4F6F8")):
            fig.add_trace(go.Bar(y=[title], x=[val], name=name, orientation="h", marker=dict(color=color, line=dict(color=charts.GRID, width=1)),
                                 hovertemplate=f"{name}: %{{x:.1f}} {unit}<extra></extra>"))
        fig.update_layout(barmode="stack", height=120, margin=dict(l=8, r=8, t=24, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          legend=dict(orientation="h", y=1.5, x=0, font=dict(size=10)), xaxis=dict(range=[0, total], gridcolor=charts.GRID),
                          yaxis=dict(visible=False), font=dict(family="Public Sans, sans-serif", color=charts.INK, size=11))
        col.plotly_chart(fig, width="stretch", key=f"split_{title}")


def render_cluster():
    st.markdown(CSS, unsafe_allow_html=True)
    minutes = st.select_slider("History shown", options=[1, 3, 5, 15, 30, 60], value=5, format_func=lambda m: f"{m} min", key="cl_win")

    @st.fragment(run_every=2)
    def panel():
        ok, state = D.api("GET", f"{GATEWAY}/infra/state", timeout=2)
        if not ok or not isinstance(state, dict) or "pods" not in state:
            st.info("The real-replica gateway is not running. Start the system with `python run_live.py` (instead of run_all.py).")
            return
        rt = R.load()
        u = [p for p in state["pods"] if p["state"] == "ready" and p["cpu_pct"] is not None]
        mean_cpu = sum(p["cpu_pct"] for p in u) / len(u) if u else None
        mean_mem = sum(p["mem_mb"] for p in u) / len(u) if u else None
        su = state["startup"]
        c = st.columns(6)
        c[0].metric("Replicas ready / wanted", f"{state['ready']} / {state['desired']}", f"{state['starting']} starting, {state['draining']} draining", delta_color="off")
        c[1].metric("Device limit", state["max_replicas"], f"limited by {state['limits']['binding']}", delta_color="off")
        c[2].metric("CPU per replica", "n/a" if mean_cpu is None else f"{mean_cpu:.0f}%", "% of one core, mean", delta_color="off")
        c[3].metric("Memory per replica", "n/a" if mean_mem is None else f"{mean_mem:.0f} MB")
        c[4].metric("Startup time", "n/a" if su["last"] is None else f"{su['last']:.1f} s", None if su["avg"] is None else f"avg {su['avg']:.1f} s ({su['n']} replicas)", delta_color="off")
        c[5].metric("Backend", state["backend"], "limits enforced" if state["isolated"] else "no CPU/RAM limits", delta_color="off")
        if state.get("last_error"):
            st.warning(f"Cluster manager: {state['last_error']}")
        if state["backend"] == "k8s":
            st.caption("Kubernetes: CPU / memory come from metrics-server, which refreshes only every 15-60 s.")
        st.markdown(_tiles(state["pods"]), unsafe_allow_html=True)
        _split_bars(state)

        since = datetime.now().timestamp() - minutes * 60
        res = D.read_csv(C.RESOURCES_CSV, 120 * max(state["max_replicas"], 1) * minutes // 1)
        ticks = D.read_csv(C.CLUSTER_TICKS_CSV, 720)
        a, b = st.columns(2)
        if res.empty:
            a.info("No CPU samples yet.")
        else:
            res = res[res["ts"] >= since]
            for col, ytitle, key, ycol, limcol in ((a, "CPU used per replica (cores)", "cpu", "cpu_pct", "cpu_limit_cores"),
                                                    (b, "memory per replica (MB)", "mem", "mem_mb", "mem_limit_mb")):
                fig = go.Figure()
                for name, g in res.groupby("replica"):
                    y = g[ycol] / 100.0 if key == "cpu" else g[ycol]
                    fig.add_trace(go.Scatter(x=_time(g), y=y, name=name[-6:], mode="lines", line=dict(width=1.4)))
                lim = pd.to_numeric(res[limcol], errors="coerce").dropna()
                if len(lim) and lim.iloc[-1] > 0:
                    fig.add_hline(y=lim.iloc[-1], line=dict(color=charts.RED, dash="dot", width=1), annotation_text="limit", annotation_position="top left")
                col.plotly_chart(_timechart(fig, 250, ytitle), width="stretch", key=f"cl_{key}")
        if ticks.empty:
            st.info("The gateway writes one row per tick (data/infra/cluster_ticks.csv); waiting for the first one.")
        else:
            ticks = ticks[ticks["ts"] >= since]
            cap = D.capacity_per_replica()
            a, b = st.columns(2)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=_time(ticks), y=ticks["desired"], name="wanted by the agent", mode="lines", line=dict(color=charts.INK, width=1.6, shape="hv")))
            fig.add_trace(go.Scatter(x=_time(ticks), y=ticks["ready"], name="really ready", mode="lines", line=dict(color=charts.TEAL, width=2.2, shape="hv")))
            fig.add_trace(go.Scatter(x=_time(ticks), y=ticks["starting"], name="starting", mode="lines", line=dict(color=charts.AMBER, width=1.2, shape="hv")))
            a.plotly_chart(_timechart(fig, 250, "replicas"), width="stretch", key="cl_rep")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=_time(ticks), y=ticks["requests"], name="traffic that arrived", mode="lines", line=dict(color=charts.INK, width=1.6)))
            fig.add_trace(go.Scatter(x=_time(ticks), y=ticks["ready"] * cap, name=f"real capacity (ready x {cap:,.0f})", mode="lines",
                                     line=dict(color=charts.BLUE, width=1.8, shape="hv")))
            b.plotly_chart(_timechart(fig, 250, "requests per tick"), width="stretch", key="cl_cap")
            a, b = st.columns(2)
            fig = go.Figure()
            for col, name, color in (("p50_ms", "p50", charts.TEAL), ("p95_ms", "p95", charts.AMBER), ("p99_ms", "p99", charts.RED)):
                fig.add_trace(go.Scatter(x=_time(ticks), y=ticks[col], name=name, mode="lines", line=dict(color=color, width=1.3)))
            fig.add_hline(y=state["device"]["slo_p95_ms"], line=dict(color=charts.RED, dash="dot", width=1), annotation_text="p95 goal", annotation_position="top left")
            a.plotly_chart(_timechart(fig, 250, "latency measured at the gateway (ms)"), width="stretch", key="cl_lat")
            fig = go.Figure()
            fig.add_trace(go.Bar(x=_time(ticks), y=ticks["errors"], name="failed requests", marker_color=charts.RED))
            fig.add_trace(go.Bar(x=_time(ticks), y=ticks["no_replica_errors"], name="of which: no ready replica", marker_color=charts.AMBER))
            fig.update_layout(barmode="overlay")
            b.plotly_chart(_timechart(fig, 250, "failed requests per tick"), width="stretch", key="cl_err")

        ok, ev = D.api("GET", f"{GATEWAY}/infra/events?tail=25", timeout=2)
        if ok and ev:
            st.markdown("**Scale events** (newest first; startup_s = real seconds from start request to Ready)")
            df = pd.DataFrame(ev).iloc[::-1]
            df["time"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(TZ).dt.strftime("%H:%M:%S")
            st.dataframe(df[["time", "event", "replica", "startup_s", "desired", "ready", "detail"]], width="stretch", hide_index=True, height=240)
        if rt.get("capacity_source") == "estimated":
            st.caption("Capacity per replica is still an estimate. Run the calibration on the 'Device & Timer' tab to measure it.")

    panel()


# ================================================================== DEVICE & TIMER
FIELDS = ["cores", "ram_mb", "reserve_cores", "reserve_ram_mb", "cpu_per_replica", "mem_per_replica_mb", "hard_max", "auto_fit", "burn_ms",
          "headroom", "target_util", "slo_p95_ms"]


def _load_form(dev: DV.Device):
    for f in FIELDS:
        st.session_state[f"dv_{f}"] = getattr(dev, f)
    st.session_state["dv_name"] = dev.name


def render_device():
    rt = R.load()
    if "dv_cores" not in st.session_state:
        _load_form(DV.load_device())
        st.session_state["dv_tick"] = float(rt["tick_seconds"])

    st.subheader("1. The machine")
    c = st.columns([3, 1, 1])
    choice = c[0].selectbox("Preset", list(DV.PRESETS), key="dv_preset")
    if c[1].button("Load preset", width="stretch"):
        _load_form(DV.preset(choice))
        st.rerun()
    if c[2].button("Detect this PC", width="stretch"):
        _load_form(DV.detect())
        st.rerun()
    a, b, c3, d = st.columns(4)
    a.number_input("CPU cores (logical)", 0.5, 256.0, step=1.0, key="dv_cores", help="Docker Desktop on Windows: the CPUs given to its VM (Settings > Resources).")
    b.number_input("RAM for Docker (MB)", 256, 1_048_576, step=512, key="dv_ram_mb", help="Docker Desktop's VM usually gets only part of your RAM; enter what Docker really has.")
    c3.number_input("CPU kept for other services (cores)", 0.0, 256.0, step=0.5, key="dv_reserve_cores", help="gateway, prediction, agent, dashboard, load sender, OS")
    d.number_input("RAM kept for other services (MB)", 0, 1_048_576, step=256, key="dv_reserve_ram_mb")
    a, b, c3 = st.columns(3)
    a.number_input("CPU limit per replica (cores)", 0.05, 8.0, step=0.05, key="dv_cpu_per_replica", help="A real Docker / Kubernetes limit. One replica is single-threaded, so above 1 core changes nothing.")
    b.number_input("Memory limit per replica (MB)", 64, 8192, step=32, key="dv_mem_per_replica_mb", help="The demo app holds ~103 MB; below ~160 the replica may be killed.")
    c3.number_input("Never more than (replicas)", 1, 100, step=1, key="dv_hard_max")

    st.subheader("2. How heavy is one request, and the latency goal")
    a, b, c3, d = st.columns(4)
    a.checkbox("Auto-fit app weight", key="dv_auto_fit", help="Choose the CPU cost per request so the whole machine can carry the training data's peak with some headroom.")
    b.number_input("App weight (CPU ms per request)", 0.5, 5000.0, step=1.0, key="dv_burn_ms", disabled=st.session_state["dv_auto_fit"])
    c3.number_input("Headroom (x training peak)", 0.5, 10.0, step=0.1, key="dv_headroom", disabled=not st.session_state["dv_auto_fit"])
    d.number_input("p95 latency goal (ms)", 10.0, 60000.0, step=50.0, key="dv_slo_p95_ms")
    st.slider("A replica counts as full at this share of its measured maximum", 0.3, 1.0, step=0.05, key="dv_target_util")

    st.subheader("3. Timer")
    t = st.columns([1, 3])
    t[0].number_input("Real seconds per tick", 1.0, 600.0, step=1.0, key="dv_tick",
                      help="1 tick = 1 simulated minute. 5 s = the speed of the training data. 60 s = real time.")
    tick = float(st.session_state["dv_tick"])
    t[1].info(f"1 simulated minute = **{tick:g} real seconds**. One simulated day takes **{1440 * tick / 3600:.1f} real hours**. "
              f"A replica that needs 10 s to start is **{10 / tick:.2f} ticks** late. The agent's 12-tick timer = **{12 * tick / 60:.1f} real minutes**.")

    dev = DV.Device.from_dict({**{f: st.session_state[f"dv_{f}"] for f in FIELDS}, "name": st.session_state.get("dv_name", "This PC")})
    lim = dev.limits()
    burn = DV.effective_burn_ms(dev, tick)
    cal = C.read_json(C.CALIBRATION_JSON)
    cap, source = DV.capacity_per_tick(dev, tick, burn, cal)
    est_rps = DV.estimate_rps_per_replica(dev, burn)

    st.subheader("What this gives")
    m = st.columns(5)
    m[0].metric("Max replicas", lim["max_replicas"], f"limited by {lim['binding']} (CPU {lim['by_cpu']}, RAM {lim['by_ram']})", delta_color="off")
    m[1].metric("Replicas use at most", f"{lim['alloc_cores_at_max']:.1f} cores", f"{lim['alloc_ram_at_max_mb']:,.0f} MB", delta_color="off")
    m[2].metric("App weight", f"{burn:.1f} ms", "auto-fit" if dev.auto_fit else "manual", delta_color="off")
    m[3].metric("One replica takes", f"{(cal['rps_per_replica'] if source == 'calibrated' else est_rps):.1f} req/s", source, delta_color="off")
    m[4].metric("Capacity per replica", f"{cap:,.0f} / tick", f"whole machine {cap * lim['max_replicas']:,.0f}", delta_color="off")
    peak = DV.training_peak_per_tick()
    if cap * lim["max_replicas"] < peak:
        st.warning(f"At full size the machine carries {cap * lim['max_replicas']:,.0f} requests per tick, below the training data's peak of {peak:,.0f}. "
                   "Spikes will really overload it (that is real behaviour on this machine).")
    for w in dev.warnings():
        st.warning(w)

    left, right = st.columns([1, 3])
    if left.button("Apply", type="primary", width="stretch"):
        with st.spinner("Rebuilding replicas and restarting collector, sender and agent ..."):
            ok, res = D.api("POST", f"{C.URL_SUPERVISOR}/apply", json={"tick_seconds": tick, "device": dev.to_dict()}, timeout=120)
        if ok and res.get("ok"):
            right.success(f"Applied. Max {res['limits']['max_replicas']} replicas, tick {tick:g} s. Restarted: {', '.join(res['restarted']) or 'nothing'}.")
        else:
            right.error(res if not ok else res.get("detail"))
    right.caption("Apply removes all replicas, starts the new ones with the new limits, and restarts the collector, request sender and agent. "
                  "Your history (CSV files) is kept. Use `python run_live.py` so the supervisor is running.")

    st.divider()
    st.subheader("4. Measure the real capacity of one replica")
    st.caption("Starts one extra replica and sends it growing request rates for about a minute. Stop the traffic sender first, and Apply before you calibrate. "
               "After it finishes, press Apply again so the agent uses the measured number.")
    b1, b2 = st.columns(2)
    if b1.button("Stop traffic", width="stretch"):
        D.api("POST", f"{S.URL_LOADGEN}/stop", json={"cancel_schedule": True})
    if b2.button("Run calibration", type="primary", width="stretch"):
        ok, res = D.api("POST", f"{GATEWAY}/infra/calibrate", timeout=5)
        if not ok:
            st.error(res)

    @st.fragment(run_every=2)
    def cal_status():
        ok, s = D.api("GET", f"{GATEWAY}/infra/calibrate/status", timeout=2)
        if not ok:
            st.caption("Gateway not reachable.")
            return
        if s["running"]:
            st.info(f"Calibrating: {s['message']}")
        elif s["message"] not in ("idle", "done"):
            st.error(s["message"])
        saved = C.read_json(C.CALIBRATION_JSON)
        if saved:
            st.write(f"Last measurement ({saved['measured_at']}, backend {saved['backend']}{'' if saved['isolated'] else ', no CPU limit enforced'}): "
                     f"**{saved['rps_per_replica']} requests/s per replica** (estimate was {saved['estimated_rps']}).")
            steps = pd.DataFrame(saved["steps"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=steps["rps"], y=steps["p95_ms"], mode="lines+markers", name="p95", line=dict(color=charts.AMBER)))
            fig.add_hline(y=saved["slo_p95_ms"], line=dict(color=charts.RED, dash="dot"), annotation_text="goal")
            fig.update_layout(height=230, margin=dict(l=8, r=8, t=20, b=8), xaxis_title="requests per second sent to one replica", yaxis_title="p95 (ms)",
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, width="stretch", key="cal_fig")

    cal_status()
