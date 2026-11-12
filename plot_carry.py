"""Plot the decision-time basis against the fixed 84-day entry hurdle."""
import csv
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from dated_carry import projected_edge

OUT = Path("research/carry")


def plot():
    horizon = 84
    with (OUT / "dated-opportunities.csv").open() as source:
        rows = [r for r in csv.DictReader(source) if int(r["days"]) == horizon and not r["issue"]]
    fig, ax = plt.subplots(figsize=(9, 4.4), constrained_layout=True)
    for coin, color, marker in (("BTC", "#156787", "o"), ("ETH", "#bd591c", "s")):
        subset = sorted((r for r in rows if r["coin"] == coin), key=lambda r: r["expiry"])
        ax.plot([date.fromisoformat(r["expiry"]) for r in subset],
                [float(r["decision_basis_bps"])/100 for r in subset],
                label=coin, marker=marker, linewidth=1.5, markersize=5, color=color)
    # For a positive premium the decision rule is linear in the futures price.
    zero = projected_edge(100, 100, horizon)
    slope = projected_edge(100, 101, horizon) - zero
    threshold = -zero/slope
    ax.axhline(threshold, color="#414141", linestyle="--", linewidth=1.4,
               label=f"Entry hurdle ({threshold:.2f}%)")
    ax.axvspan(date(2026, 1, 1), date(2026, 10, 1), color="#e9eef0", zorder=0)
    ax.text(date(2026, 5, 1), 4.8, "Later check", ha="center", color="#495b65")
    ax.set_title("BTC and ETH futures premiums 84 days before expiry", loc="left")
    ax.set_ylabel("Premium over spot")
    ax.set_xlabel("Contract expiry, UTC")
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(3, 9), bymonthday=25))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color="#b9bfc1", alpha=.35)
    ax.legend(loc="upper right", bbox_to_anchor=(1, -.18), ncol=3, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(OUT / "dated-premiums.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    plot()
