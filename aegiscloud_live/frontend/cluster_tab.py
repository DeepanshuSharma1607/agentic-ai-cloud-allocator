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
STATE_COLOR = {
    "ready": charts.INK,
    "starting": charts.ORANGE,
    "draining": charts.MUTED,
    "terminating": "#8E8E95",
    "failed": charts.ORANGE,
}
TZ = datetime.now().astimezone().tzinfo


def _time(df, col="ts"):
    return pd.to_datetime(df[col], unit="s", utc=True).dt.tz_convert(TZ)


def _timechart(fig, height=250, ytitle=""):
    charts._base(fig, height, ytitle)
    fig.update_layout(xaxis_title="time")
    return fig


def _beat_grid(state):
    max_slots = max(1, int(state.get("max_replicas", 1)))
    ready = int(state.get("ready", 0))
    starting = int(state.get("starting", 0))
    cells = []
    for idx in range(max_slots):
        if idx < ready:
            cls = "slot ready"
        elif idx < ready + starting:
            cls = "slot starting"
        else:
            cls = "slot free"
        cells.append(f'<div class="{cls}"></div>')
    return (
        f'<div class="beat-wrap">'
        f'<div class="beat-meta"><span>Replica allocation ({ready + starting} / {max_slots} slots)</span>'
        f'<span>{ready} ready · {starting} starting</span></div>'
        f'<div class="beat-grid" style="grid-template-columns:repeat({max_slots},minmax(0,1fr))">'
        + "".join(cells)
        + "</div></div>"
    )


# ================================================================== CLUSTER
def _tiles(pods):
    if not pods:
        return '<div class="aegis-empty">No replicas running yet. Adjust traffic or apply a device configuration.</div>'
    cells = []
    for p in pods:
        color = STATE_COLOR.get(p["state"], charts.INK)
        cpu_lim = (p.get("cpu_limit_cores") or 0) * 100
        cpu = p.get("cpu_pct")
        cpu_w = 0 if cpu is None or not cpu_lim else min(100, cpu / cpu_lim * 100)
        mem, mem_lim = p.get("mem_mb"), p.get("mem_limit_mb")
        mem_w = 0 if mem is None or not mem_lim else min(100, mem / mem_lim * 100)
        cpu_txt = "no data" if cpu is None else (f"{cpu:.0f}%" + (f" / {cpu_lim:.0f}%" if cpu_lim else ""))
        mem_txt = "no data" if mem is None else f"{mem:.0f}" + (f" / {mem_lim:.0f} MB" if mem_lim else " MB")
        extra = f"starting {p['age_s']:.0f}s" if p["state"] == "starting" else (f"up in {p['startup_s']:.1f}s" if p.get("startup_s") else p["state"])
        cells.append(
            f'<div class="tile{" fresh" if p["age_s"] < 4 else ""}">'
            f'<div class="tile-stripe" style="background:{color}"></div>'
            f'<div class="tile-body">'
            f'<div class="tile-head"><b>{html.escape(p["name"][-12:])}</b>'
            f'<span class="st" style="color:{color}">{html.escape(p["state"]).upper()}</span></div>'
            f'<div class="lab"><span>CPU</span><span class="val">{cpu_txt}</span></div>'
            f'<div class="bar"><div style="width:{cpu_w:.0f}%;background:{charts.INK}"></div></div>'
            f'<div class="lab"><span>Memory</span><span class="val">{mem_txt}</span></div>'
            f'<div class="bar"><div style="width:{mem_w:.0f}%;background:{charts.ORANGE}"></div></div>'
            f'<div class="tile-foot"><span>{extra}</span><span>in-flight: {p.get("inflight", 0)}</span></div>'
            f'</div></div>'
        )
    return '<div class="grid">' + "".join(cells) + "</div>"


CSS = """<style>
.beat-wrap{padding:12px 0 16px;border-bottom:1px solid #E2E2E6;margin-bottom:16px}
.beat-meta{display:flex;justify-content:space-between;font-size:.75rem;color:#5A5A60;margin-bottom:6px;font-variant-numeric:tabular-nums}
.beat-grid{display:grid;gap:4px}
.beat-grid .slot{height:12px;border:1px solid #E2E2E6;background:#F7F7F8}
.beat-grid .slot.ready{background:#111111;border-color:#111111}
.beat-grid .slot.starting{background:#FF4F00;border-color:#FF4F00}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:1px;background:#E2E2E6;border:1px solid #E2E2E6;margin:10px 0 18px}
.tile{background:#FFFFFF;border:none;border-radius:0px;overflow:hidden;font-size:.82rem}
.tile-stripe{height:4px;width:100%}
.tile-body{padding:14px}
.tile.fresh{animation:pop .25s cubic-bezier(.16,1,.3,1)}
.tile-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.tile-head b{font-family:'Archivo Narrow','Helvetica Neue',sans-serif;font-size:.9rem;letter-spacing:.02em;color:#111111}
.tile .st{font-family:'Archivo Narrow','Helvetica Neue',sans-serif;font-weight:700;font-size:.74rem;letter-spacing:.05em}
.tile .lab{display:flex;justify-content:space-between;color:#5A5A60;margin-top:8px;font-size:.74rem}
.tile .lab .val{color:#111111;font-weight:600;font-variant-numeric:tabular-nums}
.bar{height:4px;background:#F7F7F8;border-radius:0px;overflow:hidden;margin-top:4px}
.bar div{height:100%;transition:width .4s ease}
.tile-foot{display:flex;justify-content:space-between;margin-top:10px;padding-top:8px;border-top:1px solid #E2E2E6;font-size:.72rem;color:#5A5A60;font-variant-numeric:tabular-nums}
.aegis-empty{padding:20px;border:1px solid #E2E2E6;border-radius:0px;text-align:left;color:#5A5A60;background:#F7F7F8;font-size:.86rem}
@keyframes pop{from{transform:scale(.97);opacity:.2}to{transform:scale(1);opacity:1}}
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
        (b, "Memory split (MB)", dev["reserve_ram_mb"], mem_alloc, mem_used, dev["ram_mb"], "MB"),
    ):
        fig = go.Figure()
        free = max(total - reserve - alloc, 0)
        for name, val, color in (
            ("Reserved", reserve, "#E2E2E6"),
            ("Active use", used, charts.INK),
            ("Headroom", max(alloc - used, 0), charts.ORANGE),
            ("Free", free, "#F7F7F8"),
        ):
            fig.add_trace(
                go.Bar(
                    y=[title],
                    x=[val],
                    name=name,
                    orientation="h",
                    marker=dict(color=color, line=dict(color=charts.GRID, width=1)),
                    hovertemplate=f"{name}: %{{x:.1f}} {unit}<extra></extra>",
                )
            )
        fig.update_layout(
            barmode="stack",
            height=130,
            margin=dict(l=8, r=8, t=28, b=8),
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#FFFFFF",
            legend=dict(orientation="h", y=1.55, x=0, font=dict(size=10, color=charts.MUTED)),
            xaxis=dict(range=[0, total], gridcolor=charts.GRID, tickfont=dict(family=charts.SWISS_FONT, size=10, color=charts.MUTED)),
            yaxis=dict(visible=False),
            font=dict(family=charts.SWISS_FONT, color=charts.INK, size=11),
        )
        col.plotly_chart(fig, width="stretch", key=f"split_{title}")


def render_cluster():
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown("### 02. Live Replica Fleet")
    st.caption("Real container states, per-replica CPU and memory usage, and startup durations from the gateway.")
    minutes = st.select_slider("History shown", options=[1, 3, 5, 15, 30, 60], value=5, format_func=lambda m: f"{m} min", key="cl_win")

    @st.fragment(run_every=D.REFRESH_SECONDS)
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
        st.markdown(_beat_grid(state), unsafe_allow_html=True)
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
            st.caption("Kubernetes: CPU / memory come from metrics-server, which refreshes every 15-60 s.")
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
            for col, ytitle, key, ycol, limcol in (
                (a, "CPU used per replica (cores)", "cpu", "cpu_pct", "cpu_limit_cores"),
                (b, "Memory per replica (MB)", "mem", "mem_mb", "mem_limit_mb"),
            ):
                fig = go.Figure()
                for name, g in res.groupby("replica"):
                    y = g[ycol] / 100.0 if key == "cpu" else g[ycol]
                    fig.add_trace(go.Scatter(x=_time(g), y=y, name=name[-6:], mode="lines", line=dict(width=1.6)))
                lim = pd.to_numeric(res[limcol], errors="coerce").dropna()
                if len(lim) and lim.iloc[-1] > 0:
                    fig.add_hline(y=lim.iloc[-1], line=dict(color=charts.ORANGE, dash="dot", width=1.2), annotation_text="limit", annotation_position="top left")
                col.plotly_chart(_timechart(fig, 250, ytitle), width="stretch", key=f"cl_{key}")
        if ticks.empty:
            st.info("The gateway writes one row per tick (data/infra/cluster_ticks.csv); waiting for the first one.")
        else:
            ticks = ticks[ticks["ts"] >= since]
            cap = D.capacity_per_replica()
            a, b = st.columns(2)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=_time(ticks), y=ticks["desired"], name="Wanted by agent", mode="lines", line=dict(color=charts.INK, width=1.8, shape="hv")))
            fig.add_trace(go.Scatter(x=_time(ticks), y=ticks["ready"], name="Really ready", mode="lines", line=dict(color=charts.ORANGE, width=2.3, shape="hv")))
            fig.add_trace(go.Scatter(x=_time(ticks), y=ticks["starting"], name="Starting", mode="lines", line=dict(color=charts.MUTED, width=1.4, shape="hv")))
            a.plotly_chart(_timechart(fig, 250, "replicas"), width="stretch", key="cl_rep")

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=_time(ticks), y=ticks["requests"], name="Traffic arrived", mode="lines", line=dict(color=charts.INK, width=1.8)))
            fig.add_trace(go.Scatter(x=_time(ticks), y=ticks["ready"] * cap, name=f"Real capacity (ready × {cap:,.0f})", mode="lines", line=dict(color=charts.ORANGE, width=2.0, shape="hv")))
            b.plotly_chart(_timechart(fig, 250, "requests per tick"), width="stretch", key="cl_cap")

            a, b = st.columns(2)
            fig = go.Figure()
            for col, name, color in (("p50_ms", "p50", charts.INK), ("p95_ms", "p95", charts.MUTED), ("p99_ms", "p99", charts.ORANGE)):
                fig.add_trace(go.Scatter(x=_time(ticks), y=ticks[col], name=name, mode="lines", line=dict(color=color, width=1.5)))
            fig.add_hline(y=state["device"]["slo_p95_ms"], line=dict(color=charts.ORANGE, dash="dot", width=1.2), annotation_text="p95 goal", annotation_position="top left")
            a.plotly_chart(_timechart(fig, 250, "gateway latency (ms)"), width="stretch", key="cl_lat")

            fig = go.Figure()
            fig.add_trace(go.Bar(x=_time(ticks), y=ticks["errors"], name="Failed requests", marker_color=charts.ORANGE))
            fig.add_trace(go.Bar(x=_time(ticks), y=ticks["no_replica_errors"], name="No ready replica", marker_color=charts.INK))
            fig.update_layout(barmode="overlay")
            b.plotly_chart(_timechart(fig, 250, "failed requests per tick"), width="stretch", key="cl_err")

        ok, ev = D.api("GET", f"{GATEWAY}/infra/events?tail=25", timeout=2)
        if ok and ev:
            st.markdown("**Scale events** (newest first; startup_s = real seconds from spawn request to Ready)")
            df = pd.DataFrame(ev).iloc[::-1]
            df["time"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(TZ).dt.strftime("%H:%M:%S")
            st.dataframe(df[["time", "event", "replica", "startup_s", "desired", "ready", "detail"]], width="stretch", hide_index=True, height=240)
        if rt.get("capacity_source") == "estimated":
            st.caption("Capacity per replica is still an estimate. Run calibration on the 'Device & Timer' tab to measure it.")

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

    st.subheader("01. Machine Hardware & Replica Limits")
    st.caption("Specify how many CPU cores and RAM Docker/Kubernetes has, and the per-replica container budgets.")
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

    st.subheader("02. Request Weight & Latency Goal")
    a, b, c3, d = st.columns(4)
    a.checkbox("Auto-fit app weight", key="dv_auto_fit", help="Choose the CPU cost per request so the whole machine can carry the training data's peak with some headroom.")
    b.number_input("App weight (CPU ms per request)", 0.5, 5000.0, step=1.0, key="dv_burn_ms", disabled=st.session_state["dv_auto_fit"])
    c3.number_input("Headroom (x training peak)", 0.5, 10.0, step=0.1, key="dv_headroom", disabled=not st.session_state["dv_auto_fit"])
    d.number_input("p95 latency goal (ms)", 10.0, 60000.0, step=50.0, key="dv_slo_p95_ms")
    st.slider("A replica counts as full at this share of its measured maximum", 0.3, 1.0, step=0.05, key="dv_target_util")

    st.subheader("03. Simulation Timer")
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
    st.subheader("04. Measure the Real Capacity of One Replica")
    st.caption("Starts one extra replica and sends it growing request rates for about a minute. Stop the traffic sender first, and Apply before you calibrate. "
               "After it finishes, press Apply again so the agent uses the measured number.")
    b1, b2 = st.columns(2)
    if b1.button("Stop traffic", width="stretch"):
        D.api("POST", f"{S.URL_LOADGEN}/stop", json={"cancel_schedule": True})
    if b2.button("Run calibration", type="primary", width="stretch"):
        ok, res = D.api("POST", f"{GATEWAY}/infra/calibrate", timeout=5)
        if not ok:
            st.error(res)

    @st.fragment(run_every=D.REFRESH_SECONDS)
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
            fig.add_trace(go.Scatter(x=steps["rps"], y=steps["p95_ms"], mode="lines+markers", name="p95", line=dict(color=charts.INK, width=2.2), marker=dict(color=charts.INK, size=6)))
            fig.add_hline(y=saved["slo_p95_ms"], line=dict(color=charts.ORANGE, dash="dot", width=1.2), annotation_text="SLO goal")
            fig.update_layout(
                height=240,
                margin=dict(l=12, r=12, t=24, b=12),
                xaxis_title="requests per second sent to one replica",
                yaxis_title="p95 (ms)",
                paper_bgcolor="#FFFFFF",
                plot_bgcolor="#FFFFFF",
                font=dict(family=charts.SWISS_FONT, color=charts.INK, size=12),
            )
            fig.update_xaxes(gridcolor=charts.GRID, linecolor=charts.GRID, tickfont=dict(family=charts.SWISS_FONT, size=11, color=charts.MUTED))
            fig.update_yaxes(gridcolor=charts.GRID, linecolor=charts.GRID, tickfont=dict(family=charts.SWISS_FONT, size=11, color=charts.MUTED))
            st.plotly_chart(fig, width="stretch", key="cal_fig")

    cal_status()
