"""charts.py - the Plotly figures. Palette: ink = what happened, teal = forecast +10, violet = forecast +20."""
import pandas as pd
import plotly.graph_objects as go

from infra import runtime as _runtime

INK, TEAL, VIOLET, BLUE, RED, GRID, AMBER = "#16212B", "#0B7A75", "#7A4FB5", "#2F5D9B", "#C23B2E", "#D9DEE3", "#B8860B"


def _base(fig, height, ytitle):
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=28, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Public Sans, sans-serif", color=INK, size=12), hovermode="x unified",
                      legend=dict(orientation="h", y=1.12, x=0), yaxis_title=ytitle, xaxis_title=f"minute (1 minute = 1 tick = {_runtime.tick_seconds():g} s)")
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, rangemode="tozero")
    return fig


def forecast_chart(live: pd.DataFrame, pred: pd.DataFrame, horizons=(10, 20), height=380):
    """Actual traffic up to now; each forecast is drawn at the minute it is FOR, so the lines run into the future."""
    fig = go.Figure()
    if live.empty:
        return _base(fig, height, "requests per tick")
    now = live["minute"].iloc[-1]
    fig.add_trace(go.Scatter(x=live["minute"], y=live["requests"], name="actual requests", mode="lines", line=dict(color=INK, width=1.8)))
    for h, color in zip(horizons, (TEAL, VIOLET)):
        c, t = f"forecast_h{h}", f"forecast_for_h{h}"
        if not pred.empty and c in pred and t in pred:
            p = pred.dropna(subset=[c, t])
            p = p[p[t].astype(float) >= live["minute"].iloc[0]]
            if len(p):
                fig.add_trace(go.Scatter(x=p[t], y=p[c], name=f"forecast +{h} min", mode="lines",
                                         line=dict(color=color, width=1.6, dash="dot" if h == horizons[0] else "dash")))
    fig.add_vrect(x0=now, x1=now + max(horizons), fillcolor=TEAL, opacity=0.07, line_width=0)
    fig.add_vline(x=now, line=dict(color=INK, width=1, dash="dot"))
    fig.add_annotation(x=now, y=1.0, yref="paper", text="now", showarrow=False, xanchor="right", font=dict(size=11))
    return _base(fig, height, "requests per tick")


def lines(df, cols, names_colors, height=230, ytitle=""):
    fig = go.Figure()
    for col, (name, color) in zip(cols, names_colors):
        if col in df:
            fig.add_trace(go.Scatter(x=df["minute"], y=df[col], name=name, mode="lines", line=dict(color=color, width=1.4)))
    return _base(fig, height, ytitle)


def replicas_chart(ticks: pd.DataFrame, capacity: float, height=260):
    fig = go.Figure()
    if not ticks.empty:
        fig.add_trace(go.Scatter(x=ticks["minute"], y=ticks["traffic_now"], name="traffic", mode="lines", line=dict(color=INK, width=1.4)))
        fig.add_trace(go.Scatter(x=ticks["minute"], y=ticks["replicas"] * capacity, name="capacity (replicas x per-replica)", mode="lines",
                                 line=dict(color=BLUE, width=1.8, shape="hv")))
    return _base(fig, height, "requests per tick")
