"""charts.py - Plotly figures styled with the strict Swiss grid palette."""
import pandas as pd
import plotly.graph_objects as go

from infra import runtime as _runtime

INK = "#111111"
ORANGE = "#FF4F00"
TEAL = "#111111"
VIOLET = "#5A5A60"
BLUE = "#FF4F00"
RED = "#FF4F00"
GRID = "#E2E2E6"
AMBER = "#5A5A60"
MUTED = "#5A5A60"

SWISS_FONT = "Helvetica Neue, Archivo, Helvetica, Arial, sans-serif"
FOLIO_FONT = "Archivo Narrow, Helvetica Neue, Helvetica, Arial, sans-serif"


def _base(fig, height, ytitle):
    fig.update_layout(
        height=height,
        margin=dict(l=12, r=12, t=34, b=12),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family=SWISS_FONT, color=INK, size=12),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=INK, font_color="#FFFFFF", font_family=SWISS_FONT, font_size=11),
        legend=dict(orientation="h", y=1.14, x=0, font=dict(size=11, color=MUTED)),
        yaxis_title=ytitle,
        xaxis_title=f"minute (1 minute = 1 tick = {_runtime.tick_seconds():g} s)",
    )
    fig.update_xaxes(
        gridcolor=GRID,
        linecolor=GRID,
        zeroline=False,
        tickfont=dict(family=SWISS_FONT, size=11, color=MUTED),
    )
    fig.update_yaxes(
        gridcolor=GRID,
        linecolor=GRID,
        zeroline=False,
        rangemode="tozero",
        tickfont=dict(family=SWISS_FONT, size=11, color=MUTED),
    )
    return fig


def forecast_chart(live: pd.DataFrame, pred: pd.DataFrame, horizons=(10, 20), height=390):
    """Actual traffic up to now; each forecast is drawn at the minute it is FOR, so the lines run into the future."""
    fig = go.Figure()
    if live.empty:
        return _base(fig, height, "requests per tick")
    now = live["minute"].iloc[-1]
    fig.add_trace(
        go.Scatter(
            x=live["minute"],
            y=live["requests"],
            name="Actual requests",
            mode="lines",
            line=dict(color=INK, width=2.2),
            fill="tozeroy",
            fillcolor="rgba(17, 17, 17, 0.04)",
        )
    )
    for h, color in zip(horizons, (ORANGE, MUTED)):
        c, t = f"forecast_h{h}", f"forecast_for_h{h}"
        if not pred.empty and c in pred and t in pred:
            p = pred.dropna(subset=[c, t])
            p = p[p[t].astype(float) >= live["minute"].iloc[0]]
            if len(p):
                fig.add_trace(
                    go.Scatter(
                        x=p[t],
                        y=p[c],
                        name=f"Forecast +{h} min",
                        mode="lines",
                        line=dict(color=color, width=2.0, dash="solid" if h == horizons[0] else "dash"),
                    )
                )
    fig.add_vrect(x0=now, x1=now + max(horizons), fillcolor=ORANGE, opacity=0.06, line_width=0)
    fig.add_vline(x=now, line=dict(color=INK, width=1.2, dash="dot"))
    fig.add_annotation(
        x=now,
        y=1.0,
        yref="paper",
        text="NOW",
        showarrow=False,
        xanchor="right",
        font=dict(family=FOLIO_FONT, size=11, color=ORANGE),
    )
    return _base(fig, height, "requests per tick")


def lines(df, cols, names_colors, height=240, ytitle=""):
    fig = go.Figure()
    for col, (name, color) in zip(cols, names_colors):
        if col in df:
            fig.add_trace(go.Scatter(x=df["minute"], y=df[col], name=name, mode="lines", line=dict(color=color, width=1.8)))
    return _base(fig, height, ytitle)


def replicas_chart(ticks: pd.DataFrame, capacity: float, height=270):
    fig = go.Figure()
    if not ticks.empty:
        fig.add_trace(
            go.Scatter(
                x=ticks["minute"],
                y=ticks["traffic_now"],
                name="Incoming traffic",
                mode="lines",
                line=dict(color=INK, width=1.8),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=ticks["minute"],
                y=ticks["replicas"] * capacity,
                name="Cluster capacity (replicas × per-replica)",
                mode="lines",
                line=dict(color=ORANGE, width=2.2, shape="hv"),
            )
        )
    return _base(fig, height, "requests per tick")
