"""Two static charts for the report (matplotlib, PNG)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
ACCENT, GRAY, LIGHT_GRAY = "#2a78d6", "#8a8984", "#c9c8c2"


def _axes(figsize=(7.2, 4.0)):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    return fig, ax, plt


def gains_chart(path: Path, y, curves: dict, title: str, max_share: float = 0.3) -> None:
    """Share of disputed markets caught vs. share of markets flagged, riskiest first.

    ``curves`` maps a label to scores; the first is drawn in the accent colour.
    """
    y = np.asarray(y, dtype=float)
    fig, ax, plt = _axes()
    shares = np.linspace(0, max_share, 121)
    colors = [ACCENT, GRAY, LIGHT_GRAY]
    for k, (label, s) in enumerate(curves.items()):
        order = np.argsort(-(np.asarray(s) + np.random.default_rng(1).random(len(s)) * 1e-12))
        caught = np.concatenate([[0], np.cumsum(y[order])]) / max(1, y.sum())
        xs = np.arange(len(y) + 1) / len(y)
        vals = np.interp(shares, xs, caught) * 100
        ax.plot(shares * 100, vals, color=colors[k % 3], lw=2, solid_capstyle="round", label=label)
        ax.text(shares[-1] * 100 + 0.4, vals[-1], f"{vals[-1]:.0f}%", color=INK, fontsize=8,
                va="center")
    ax.plot(shares * 100, shares * 100, color=INK2, lw=1, ls=(0, (3, 3)), label="Random order")
    ax.axvline(5, color=GRID, lw=1)
    ax.text(5.3, 2, "riskiest 5%", color=INK2, fontsize=8)
    ax.set_xlim(0, max_share * 100 + 3)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Markets flagged, riskiest first (%)", color=INK2, fontsize=9)
    ax.set_ylabel("Disputed markets caught (%)", color=INK2, fontsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    ax.set_title(title, color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def power_chart(path: Path, labels: list[str], series: dict, title: str,
                level: float = 5.0) -> None:
    """Columns: share of samples where the test fires, per scenario.

    ``series`` maps a name to one value per scenario (NaN where it does not
    apply); the columns present in each scenario are centred on its tick.
    """
    fig, ax, plt = _axes((7.2, 3.8))
    x = np.arange(len(labels))
    names = list(series)
    colors = dict(zip(names, [ACCENT, LIGHT_GRAY, GRAY]))
    width = 0.3
    drawn = set()
    for g in range(len(labels)):
        present = [n for n in names if np.isfinite(float(series[n][g]))]
        for k, n in enumerate(present):
            v = float(series[n][g])
            pos = x[g] + (k - (len(present) - 1) / 2) * width
            ax.bar(pos, v, width * 0.92, color=colors[n], label=None if n in drawn else n)
            drawn.add(n)
            ax.text(pos, max(v, level) + 1.5, f"{v:.0f}%", ha="center", va="bottom",
                    fontsize=8, color=INK)
    ax.axhline(level, color=INK2, lw=1, ls=(0, (3, 3)))
    ax.text(x[-1] + 0.55, level - 4.5, f"{level:.0f}% level", fontsize=8, color=INK2,
            ha="right")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9, color=INK2)
    ax.set_xlim(-0.6, len(labels) - 0.4)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Samples where H1 fires (%)", color=INK2, fontsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper left")
    ax.set_title(title, color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
