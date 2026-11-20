"""
frontend/app.py - the dashboard (Streamlit). Run it with `python run_all.py` or:  streamlit run frontend/app.py

  Live     current traffic, forecasts for +10 and +20 minutes (drawn into the future), live forecast error, latency,
           CPU / memory, replicas vs capacity
  Control  start / stop the request sender, choose how many requests and when (timer / schedule)
  Agent    what the autoscaler decided and every alert
  Data     where the CSV files are and how big they are
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

import settings as S
from frontend import charts
from frontend import cluster_tab
from frontend import data_access as D
from infra import runtime as infra_runtime

S.TICK_SECONDS = infra_runtime.tick_seconds()          # the tick length can be changed on the Device & Timer tab
st.set_page_config(page_title="AegisCloud Live", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo+Narrow:wght@600;700&family=Archivo:wght@400;500;600;700;800&display=swap');

html, body, [class*="st-"], .stMarkdown {
  font-family: "Helvetica Neue", "Archivo", Helvetica, Arial, sans-serif;
  color: #111111;
}
.stApp {
  background-color: #FFFFFF;
}
.block-container {
  padding-top: 1.8rem;
  padding-bottom: 3rem;
  max-width: 1360px;
}
h1, h2, h3 {
  font-family: "Helvetica Neue", "Archivo", Helvetica, Arial, sans-serif !important;
  font-weight: 800 !important;
  letter-spacing: -0.025em !important;
  color: #111111 !important;
}
[data-testid="stMetric"] {
  background: #F7F7F8;
  border: 1px solid #E2E2E6;
  border-radius: 0px;
  padding: 14px 16px;
}
[data-testid="stMetricValue"] {
  font-family: "Helvetica Neue", "Archivo", Helvetica, Arial, sans-serif !important;
  font-variant-numeric: tabular-nums;
  font-weight: 800 !important;
  color: #111111 !important;
}
[data-testid="stMetricLabel"] p {
  font-size: 0.78rem !important;
  color: #5A5A60 !important;
  font-weight: 600 !important;
}
[data-testid="stTabs"] [role="tablist"] {
  gap: 1.5rem;
  border-bottom: 1px solid #111111;
  margin-bottom: 1.2rem;
}
[data-testid="stTabs"] button[role="tab"] {
  font-weight: 600;
  color: #5A5A60;
  padding-bottom: 0.7rem;
  border-radius: 0px !important;
  transition: color 0.15s ease;
}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
  color: #111111;
  border-bottom: 3px solid #FF4F00 !important;
}
.stButton > button, .stDownloadButton > button {
  border-radius: 0px !important;
  font-weight: 600 !important;
  transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease !important;
}
.stTextInput input, .stNumberInput input, .stSelectbox > div > div {
  border-radius: 0px !important;
}
.svc-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  align-items: center;
  padding: 10px 0 14px;
  margin-bottom: 12px;
  border-bottom: 1px solid #E2E2E6;
  font-size: 0.8rem;
}
.svc-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #111111;
}
.svc-up { color: #111111; font-family: "Archivo Narrow", "Helvetica Neue", sans-serif; font-weight: 700; }
.svc-down { color: #FF4F00; font-family: "Archivo Narrow", "Helvetica Neue", sans-serif; font-weight: 700; }
</style>""", unsafe_allow_html=True)

st.title("AegisCloud Live")
st.caption(f"Traffic in, LSTM forecast out, autoscaler decides ahead of spikes · 1 tick = {S.TICK_SECONDS:g} real seconds = 1 simulated minute.")


# ---------------------------------------------------------------- helpers
def chips():
    status = D.services()
    items = "".join(
        f'<span class="svc-item">{name.title()} '
        f'<span class="{"svc-up" if ok else "svc-down"}">· {"Up" if ok else "Down"}</span></span>'
        for name, ok in status.items()
    )
    st.markdown(f'<div class="svc-strip">{items}</div>', unsafe_allow_html=True)
    return status


def fmt(v, d=0):
    return "n/a" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:,.{d}f}"


tab_live, tab_cluster, tab_device, tab_ctrl, tab_agent, tab_data = st.tabs(
    ["01 Live", "02 Cluster", "03 Device & Timer", "04 Control", "05 Agent", "06 Data"]
)


# ================================================================ LIVE
@st.fragment(run_every=D.REFRESH_SECONDS)
def live_panel(window):
    chips()
    live = D.read_csv(S.LIVE_CSV, window)
    pred_all = D.read_csv(S.PRED_CSV, max(window, 900))          # only the recent rows: the files grow all day
    pred = pred_all.tail(window)
    ticks = D.read_csv(S.AGENT_DIR / "agent_ticks.csv", window)
    if live.empty:
        st.info(f"Waiting for the first tick. The collector writes one row every {S.TICK_SECONDS:g} seconds.")
        return
    _, _, train_mean = D.training_range()
    last, lastp = live.iloc[-1], (pred.iloc[-1] if not pred.empty else None)
    live_acc = D.read_csv(S.LIVE_CSV, max(window, 900))
    acc10 = D.accuracy(pred_all, live_acc, 10)
    acc20 = D.accuracy(pred_all, live_acc, 20)

    c = st.columns(6)
    c[0].metric("Traffic now", fmt(last["requests"]), help="Requests in the last tick")
    c[1].metric(
        "Forecast +10 min",
        fmt(None if lastp is None else lastp.get("forecast_h10")),
        None if lastp is None or pd.isna(lastp.get("forecast_h10")) else f"{lastp['forecast_h10'] - last['requests']:+.0f} vs now",
    )
    c[2].metric("Forecast +20 min", fmt(None if lastp is None else lastp.get("forecast_h20")))
    c[3].metric(
        "Forecast error +10",
        "n/a" if not acc10 else f"{100 * acc10['wape']:.0f}%",
        None if not acc10 else f"naive {100 * acc10['naive_wape']:.0f}%",
        delta_color="off",
        help="WAPE over forecasts whose time has already come. 'naive' = assuming traffic stays as it is now. Lower is better.",
    )
    c[4].metric(
        "Replicas",
        "n/a" if ticks.empty else int(ticks["replicas"].iloc[-1]),
        None if ticks.empty else f"capacity {ticks['replicas'].iloc[-1] * D.capacity_per_replica():,.0f}",
        delta_color="off",
    )
    src = None if lastp is None else lastp.get("history_source")
    c[5].metric(
        "History used",
        "n/a" if src is None else ("100% live" if src == "live" else "seed + live"),
        help="'seed + live': the 24h history behind 'yesterday' features still includes training data (warm-up).",
    )

    if lastp is not None and float(lastp.get("drift_z", 0) or 0) > 3:
        st.warning(
            f"Live inputs look unlike the training data (`{lastp['drift_metric']}` is {lastp['drift_z']} standard deviations away). "
            "Forecasts may be unreliable until live traffic resembles the training range."
        )
    lo, hi, _ = D.training_range()
    if last["requests"] > hi * 1.1:
        st.warning(f"Traffic ({last['requests']:.0f}/tick) is above anything in the training data (max {hi:.0f}). The LSTM may under-predict.")

    st.plotly_chart(charts.forecast_chart(live, pred), width="stretch", key="fc")
    a, b = st.columns(2)
    a.plotly_chart(
        charts.lines(live, ["p50_ms", "p95_ms", "p99_ms"], [("p50", charts.INK), ("p95", charts.MUTED), ("p99", charts.ORANGE)], ytitle="latency (ms)"),
        width="stretch",
        key="lat",
    )
    b.plotly_chart(
        charts.lines(
            live,
            ["app_cpu_pct", "host_cpu_pct", "app_mem_mb"],
            [("App CPU %", charts.ORANGE), ("Host CPU %", charts.INK), ("App memory MB", charts.MUTED)],
            ytitle="CPU % / MB",
        ),
        width="stretch",
        key="res",
    )
    st.plotly_chart(charts.replicas_chart(ticks, D.capacity_per_replica()), width="stretch", key="rep")
    if acc20:
        st.caption(f"Forecast error +20 min: {100 * acc20['wape']:.0f}% (naive {100 * acc20['naive_wape']:.0f}%), measured on {acc20['n']} matured forecasts.")


with tab_live:
    window = st.select_slider("Window (ticks)", options=[60, 120, 240, 360, 720, 1440], value=240, key="win")
    live_panel(window)


# ================================================================ CLUSTER and DEVICE & TIMER (real replicas)
with tab_cluster:
    cluster_tab.render_cluster()
with tab_device:
    cluster_tab.render_device()


# ================================================================ CONTROL
def plan_editor(prefix, allow_idle=False):
    """Widgets for one plan; returns the plan dict."""
    lo_t, hi_t, mean_t = D.training_range()
    modes = {
        "Daily pattern (like the training data)": "pattern",
        "Fixed number per tick": "fixed",
        "Random between two numbers": "random",
        "Replay the real training rows": "replay",
    }
    label = st.selectbox("Traffic type", list(modes), key=f"{prefix}_mode")
    mode, plan = modes[label], {}
    plan["mode"] = mode
    if mode == "fixed":
        plan["n"] = int(st.number_input("Requests per tick", 0, S.MAX_REQUESTS_PER_TICK, 150, 10, key=f"{prefix}_n"))
        st.caption(f"= {plan['n'] / S.TICK_SECONDS:.0f} requests per second. Training range: {lo_t:.0f} to {hi_t:.0f} per tick.")
        if plan["n"] > hi_t:
            st.warning("Above the training maximum: the LSTM has never seen this level.")
    elif mode == "random":
        c1, c2 = st.columns(2)
        plan["lo"] = int(c1.number_input("Minimum per tick", 0, S.MAX_REQUESTS_PER_TICK, 50, 10, key=f"{prefix}_lo"))
        plan["hi"] = int(c2.number_input("Maximum per tick", 0, S.MAX_REQUESTS_PER_TICK, 400, 10, key=f"{prefix}_hi"))
        plan["smooth"] = st.slider("Smoothness (0 = jumpy)", 0.0, 0.95, 0.5, 0.05, key=f"{prefix}_sm")
    elif mode == "pattern":
        plan["scale"] = st.slider("Size (1.0 = same average as the training data)", 0.1, 5.0, 1.0, 0.1, key=f"{prefix}_sc")
        c1, c2 = st.columns(2)
        plan["burst_prob"] = c1.slider("Chance of a burst per tick", 0.0, 0.1, 0.01, 0.005, key=f"{prefix}_bp")
        plan["burst_mult"] = c2.slider("Burst size (x)", 1.0, 8.0, 3.0, 0.5, key=f"{prefix}_bm")
        st.caption(f"Average about {mean_t * plan['scale']:.0f} requests per tick, following the daily curve of your data.")
    else:
        plan["start"] = int(st.number_input("Start at row of the seed file", 0, 10 ** 7, 0, 100, key=f"{prefix}_st"))
        plan["scale"] = st.slider("Size", 0.1, 5.0, 1.0, 0.1, key=f"{prefix}_rs")
    return plan


with tab_ctrl:
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.subheader("01. Send traffic now")
        base_plan = plan_editor("base")
        b1, b2 = st.columns(2)
        if b1.button("Start / apply", type="primary", width="stretch"):
            ok, res = D.api("POST", f"{S.URL_LOADGEN}/start", json=base_plan)
            st.success("Sender updated.") if ok else st.error(res)
        if b2.button("Stop all traffic", width="stretch"):
            ok, res = D.api("POST", f"{S.URL_LOADGEN}/stop", json={"cancel_schedule": True})
            st.success("Stopped. Idle ticks are still recorded as 0 requests.") if ok else st.error(res)

    with right:
        st.subheader("02. Timer: send this much, at this time")
        when = st.radio("Start", ["after a delay", "at a clock time"], horizontal=True, key="when")
        if when == "after a delay":
            delay_min = st.number_input("Start in (minutes)", 0.0, 1440.0, 1.0, 0.5, key="delay")
            start_in, start_at = delay_min * 60, None
        else:
            t = st.time_input("Clock time (today, or tomorrow if already passed)", (datetime.now() + timedelta(minutes=2)).time(), key="clock")
            when_dt = datetime.combine(datetime.now().date(), t)
            when_dt = when_dt if when_dt > datetime.now() else when_dt + timedelta(days=1)
            start_in, start_at = None, when_dt.isoformat(timespec="seconds")
        dur_min = st.number_input("Duration (minutes)", 0.5, 1440.0, 5.0, 0.5, key="dur")
        seg_plan = plan_editor("seg")
        if st.button("Schedule it", type="primary", width="stretch"):
            body = {"plan": seg_plan, "duration_s": dur_min * 60, "in_seconds": start_in, "start_at": start_at}
            ok, res = D.api("POST", f"{S.URL_LOADGEN}/schedule", json=body)
            st.success(f"Scheduled (#{res['id']}), starts in {res['starts_in_s']:.0f} s.") if ok else st.error(res)

    st.divider()

    @st.fragment(run_every=D.REFRESH_SECONDS)
    def sender_status():
        ok, s = D.api("GET", f"{S.URL_LOADGEN}/status", timeout=2)
        if not ok:
            st.error(f"Request sender not reachable: {s}")
            return
        lt = s["last_tick"]
        c = st.columns(4)
        c[0].metric("Sending now", s["active_label"])
        c[1].metric("Last tick: planned / ok / failed", f"{lt['planned']} / {lt['ok']} / {lt['failed']}",
                    help="failed = refused (503) or slower than 5 s")
        c[2].metric("Total sent", f"{s['totals']['sent']:,}")
        c[3].metric("Total failed", f"{s['totals']['failed']:,}")
        if s["segments"]:
            st.markdown("**Scheduled segments**")
            for seg in s["segments"]:
                a, b = st.columns([5, 1])
                state = f"running, {seg['remaining_s']:.0f} s left" if seg["status"] == "running" else f"starts in {seg['starts_in_s']:.0f} s"
                a.write(f"#{seg['id']} {seg['plan']['mode']} for {seg['duration_s'] / 60:.1f} min at {seg['start_at']} ({state})")
                if b.button("Cancel", key=f"cancel{seg['id']}"):
                    D.api("DELETE", f"{S.URL_LOADGEN}/schedule/{seg['id']}")
                    st.rerun(scope="fragment")
        else:
            st.caption("No scheduled segments.")

    sender_status()
    st.divider()
    st.subheader("03. Collector")
    ok, cs = D.api("GET", f"{S.URL_COLLECTOR}/status", timeout=2)
    if ok:
        c1, c2 = st.columns([3, 1])
        c1.write(f"{'Paused' if cs['paused'] else 'Collecting'}: {cs['rows_written']} rows this session, next minute {cs['next_minute']}, "
                 f"prediction service {'ok' if cs['prediction_service_ok'] else 'not confirmed'}.")
        if cs["paused"] and c2.button("Resume", width="stretch"):
            D.api("POST", f"{S.URL_COLLECTOR}/resume")
            st.rerun()
        if not cs["paused"] and c2.button("Pause", width="stretch"):
            D.api("POST", f"{S.URL_COLLECTOR}/pause")
            st.rerun()
    else:
        st.error(f"Collector not reachable: {cs}")


# ================================================================ AGENT
with tab_agent:
    @st.fragment(run_every=D.REFRESH_SECONDS)
    def agent_panel():
        acts = D.read_csv(S.AGENT_DIR / "actions.csv")                     # small file, parsed again only when it changes
        n_ticks = D.count_rows(S.AGENT_DIR / "agent_ticks.csv")            # counted once per file change: the file now keeps growing across runs
        if n_ticks == 0:
            st.info("The agent has not written anything yet. Start it with `python run_all.py` or `python -m agent.run`.")
            return
        c = st.columns(4)
        c[0].metric("Ticks handled", f"{n_ticks:,}")
        c[1].metric("Decisions logged", len(acts))
        changes = 0 if acts.empty or "action" not in acts else int(acts["action"].isin(["scale_up", "scale_down"]).sum())
        c[2].metric("Replica changes", changes)
        alerts = sorted((S.AGENT_DIR / "alerts").glob("alert_*.txt"), key=lambda f: f.stat().st_mtime)
        c[3].metric("Alerts", len(alerts))
        st.markdown("**Latest decisions**")
        st.dataframe(acts.tail(25).iloc[::-1] if not acts.empty else acts, width="stretch", hide_index=True)
        if alerts:
            st.markdown("**Latest alert**")
            st.code(alerts[-1].read_text(encoding="utf-8")[:2500])

    agent_panel()


# ================================================================ DATA
with tab_data:
    st.caption("Everything is plain CSV, so you can open it in Excel or load it into a notebook.")
    files = [
        ("Seed (your training data)", S.SEED_CSV),
        ("Live metrics (collector)", S.LIVE_CSV),
        ("Predictions (LSTM)", S.PRED_CSV),
        ("Agent ticks", S.AGENT_DIR / "agent_ticks.csv"),
        ("Agent actions", S.AGENT_DIR / "actions.csv"),
        ("Sender ticks", S.LOADGEN_DIR / "load_ticks.csv"),
        ("Sender events", S.LOADGEN_DIR / "events.csv"),
    ]
    for name, path in files:
        a, b, c = st.columns([3, 1, 1])
        a.write(f"**{name}**  \n`{path.relative_to(S.ROOT) if path.is_relative_to(S.ROOT) else path}`")
        if path.exists() and path.stat().st_size:
            b.write(f"{D.count_rows(path):,} rows")
            c.download_button("Download", D.file_bytes(path), file_name=path.name, key=f"dl_{path.name}_{name}")
        else:
            b.write("not created yet")
