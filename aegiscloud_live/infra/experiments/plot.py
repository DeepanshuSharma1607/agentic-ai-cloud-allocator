"""plot.py - figures and a table for the paper from data/experiments/ (run after run_experiment.py)."""
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import settings as S  # noqa: E402

EXP = S.DATA_DIR / "experiments"
COLORS = {"static": "#7A8794", "reactive": "#B8860B", "hpa": "#2F5D9B", "aegis": "#0B7A75"}


def main():
    res = pd.read_csv(EXP / "results.csv")
    cols = ["slo_miss_pct", "failed_pct", "replica_seconds", "mean_startup_s", "overload_ticks", "p95_peak_ms"]
    table = res.groupby("policy")[cols].agg(["mean", "std"]).round(2)
    table.to_csv(EXP / "summary_table.csv")
    print(table.to_string())

    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    for ax, (col, title) in zip(axes, [("slo_miss_pct", "Ticks that missed the latency goal (%)"), ("failed_pct", "Failed requests (%)"),
                                       ("replica_seconds", "Cost: replica-seconds")]):
        g = res.groupby("policy")[col].agg(["mean", "std"]).fillna(0)
        ax.bar(g.index, g["mean"], yerr=g["std"], color=[COLORS.get(p, "#444") for p in g.index], capsize=3)
        ax.set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(EXP / "fig_policy_comparison.png", dpi=170)

    runs = sorted(EXP.glob("*_rep1"))
    if runs:
        fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
        for run in runs:
            pol = run.name.split("_rep")[0]
            t = pd.read_csv(run / "ticks.csv")
            x = t["tick"] - t["tick"].iloc[0]
            axes[0].plot(x, t["ready"], label=pol, color=COLORS.get(pol), drawstyle="steps-post")
            axes[1].plot(x, t["p95_ms"], label=pol, color=COLORS.get(pol))
        axes[0].set_ylabel("ready replicas")
        axes[1].set_ylabel("p95 latency (ms)")
        axes[1].set_xlabel("tick")
        axes[0].legend()
        fig.suptitle("Response to the same spike (repetition 1)")
        fig.tight_layout()
        fig.savefig(EXP / "fig_spike_response.png", dpi=170)
    print(f"\nFigures and summary_table.csv are in {EXP}")


if __name__ == "__main__":
    main()
