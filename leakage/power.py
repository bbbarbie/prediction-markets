"""Which test flags which kind of insider, on fresh simulated samples.

    python3 -m leakage.power --out leakage/results --reps 200 --events 400

Each replication simulates a new sample of `events` scheduled-reveal events
(half binary, half 3-8 outcomes) and runs three one-sided tests at the 5%
level on the day before the reveal (24h to 1h out):

  leak share   is L > 0?  (z from the event-clustered standard error)
  skip test    do skipped outcomes in NO baskets win more than prices say?
  long-shot    do large YES bets at <= 35c win more than prices say?

Scenarios, insiders in `share` of events:
  none          no insiders: the share of samples flagged is the false-alarm rate
  yes           insiders buy YES on the answer
  basket        insiders buy NO on every other outcome, legs seconds apart
  basket_slow   the same basket, legs 2-10 minutes apart (past the 60 s burst rule)
In binary events every insider simply buys the winning side. An insider makes
about 5 trades of median 150 contracts (noise traders: 20), each moving the
price 0.30 in log-odds for good, starting 2-48 hours before the reveal.

Every replication is a fresh sample, so a false-alarm rate is not tied to the
luck of one resampled pool. Prices are recalibrated inside each sample.
"""
from __future__ import annotations

import argparse
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from . import metrics, mirror, synth

Z_CRIT = 1.6448536269514722
SCENARIOS = {
    "none": {"leak_rate": 0.0},
    "yes": {"leak_style": "yes"},
    "basket": {"leak_style": "basket"},
    "basket_slow": {"leak_style": "basket", "basket_leg_gap": (120.0, 600.0)},
}
LABELS = {"none": "No insiders", "yes": "Insiders buy YES",
          "basket": "Insiders buy the NO basket", "basket_slow": "NO basket, legs minutes apart"}


def one_rep(job: tuple) -> dict:
    scenario, events, share, seed = job
    kw = {"leak_rate": share, **SCENARIOS[scenario]}
    ds, truth = synth.dataset([synth.Spec(family="scheduled_reveal", n_events=events,
                                          me_share=0.5, seed=seed, **kw)])
    tt = metrics.trade_table(ds)
    wp = metrics.window_prices(ds, (metrics.PRE_REVEAL,), max_start_age_hours=12)
    eb = metrics.event_brier(wp, by=())
    R, se = metrics.ratio_by_cluster(eb["brier_end"], eb["brier_start"])
    calib = mirror.cross_fit_calibration(ds)
    sk = mirror.skip_test(mirror.skip_bursts(ds, tt, calib), n_null=2000, seed=seed)
    ls = mirror.longshot_test(tt, calib, n_null=2000, seed=seed)
    return {"scenario": scenario, "events": events, "share": share, "seed": seed,
            "leaked": int(truth["leaked"].sum()),
            "leak_share": 1 - R, "leak_z": (1 - R) / se if se > 0 else np.nan,
            "flag_leak_share": bool(se > 0 and (1 - R) / se > Z_CRIT),
            "skip_bursts": sk.get("bursts", 0), "skip_hit_ratio": sk.get("hit_ratio", np.nan),
            "flag_skip": sk.get("p_value", 1.0) < 0.05,
            "longshot_markets": ls.get("markets", 0), "longshot_hit_ratio": ls.get("hit_ratio", np.nan),
            "flag_longshot": ls.get("p_value", 1.0) < 0.05}


def run(scenarios=tuple(SCENARIOS), events: int = 400, share: float = 0.05,
        reps: int = 200, workers: int = 2) -> tuple[pd.DataFrame, pd.DataFrame]:
    jobs = [(s, events, share, 100_000 * k + r)
            for k, s in enumerate(scenarios, start=1) for r in range(reps)]
    with Pool(workers) as pool:
        rows = pool.map(one_rep, jobs, chunksize=4)
    raw = pd.DataFrame(rows)
    out = []
    for s, g in raw.groupby("scenario", sort=False):
        row = {"scenario": s, "label": LABELS[s], "events": events,
               "insider_share": 0.0 if s == "none" else share, "reps": len(g)}
        for test in ("leak_share", "skip", "longshot"):
            p = g[f"flag_{test}"].mean()
            row[f"flagged_{test}"] = p
            row[f"se_{test}"] = float(np.sqrt(p * (1 - p) / len(g)))
        out.append(row)
    return pd.DataFrame(out), raw


def plot(table: pd.DataFrame, path: Path) -> None:
    """Grouped bars: share of samples each test flags, by scenario."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, ink2, grid, surface = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    tests = [("flagged_skip", "Skip test", "#2a78d6"),
             ("flagged_leak_share", "Leak share", "#8a8984"),
             ("flagged_longshot", "Long-shot YES bets", "#c9c8c2")]
    fig, ax = plt.subplots(figsize=(7.4, 3.8), dpi=150)
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)
    x = np.arange(len(table))
    width = 0.26
    for k, (col, label, color) in enumerate(tests):
        vals = 100 * table[col].to_numpy()
        pos = x + (k - 1) * (width + 0.02)
        ax.bar(pos, vals, width, color=color, label=label)
        for xi, v in zip(pos, vals):
            ax.text(xi, v + 1.5, f"{v:.0f}", ha="center", va="bottom", fontsize=8, color=ink)
    ax.axhline(5, color=ink2, lw=1, ls=(0, (3, 3)))
    ax.set_xlim(-0.55, x[-1] + 0.75)
    ax.text(x[-1] + 0.72, 6.5, "5% level", fontsize=8, color=ink2, ha="right")
    ax.set_xticks(x, [l.replace("Insiders buy the NO basket", "Insiders buy\nthe NO basket")
                       .replace("NO basket, legs minutes apart", "NO basket, legs\nminutes apart")
                       .replace("Insiders buy YES", "Insiders buy\nYES") for l in table["label"]],
                  fontsize=9, color=ink2)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Samples flagged (%)", color=ink2, fontsize=9)
    ax.tick_params(colors=ink2, labelsize=9)
    ax.grid(axis="y", color=grid, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(grid)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    n, share, reps = table["events"].iloc[0], table["insider_share"].max(), table["reps"].min()
    ax.set_title(f"{n} events per sample, insiders in {share:.0%} of them, {reps} fresh samples per scenario",
                 color=ink, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(path, facecolor=surface)
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="leakage/results")
    ap.add_argument("--reps", type=int, default=200)
    ap.add_argument("--events", type=int, default=400)
    ap.add_argument("--share", type=float, default=0.05)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--plot-only", action="store_true", help="redraw power.png from power.csv")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.plot_only:
        plot(pd.read_csv(out / "power.csv"), out / "power.png")
        return 0
    table, raw = run(events=a.events, share=a.share, reps=a.reps, workers=a.workers)
    table.to_csv(out / "power.csv", index=False)
    raw.to_csv(out / "power_runs.csv", index=False)
    plot(table, out / "power.png")
    print(table.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
