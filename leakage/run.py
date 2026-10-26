"""One command: data in, leakage report out.

    python3 -m leakage.run --data data/kalshi --out leakage/report
    python3 -m leakage.run --synthetic --out leakage/demo_report     # no network needed
    python3 -m leakage.run --data data/kalshi --split-date 2026-06-09

Reads a kalshi_pull folder (or a Becker-style parquet folder), assigns
contract families, and writes report.md with:
  1. the family table (check it before reading anything else),
  2. leak share by family and window before the reveal (H1, H4),
  3. taker markouts and the leakage tax in spread terms (H3),
  4. the skip test and the long-shot test, before and after --split-date (H2),
     with two placebos the skip test must pass,
plus leak_share.png and CSVs of every table.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, metrics, mirror, spread, synth

MAIN_FAMILIES = ("scheduled_reveal", "scheduled_data", "continuous_public")
MAX_START_AGE_H = 12.0          # pre-registered: drop stale window-start prices
COLORS = {"scheduled_reveal": "#2a78d6", "scheduled_data": "#eb6834",
          "continuous_public": "#1baf7a"}                 # categorical slots 1-3
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def fmt(df: pd.DataFrame, digits: int = 3) -> str:
    """DataFrame -> GitHub markdown table without extra dependencies."""
    if df.empty:
        return "_(no rows)_"
    cols = list(df.columns)
    def cell(v):
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else f"{v:.{digits}f}"
        return str(v)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def plot_leak_share(table: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    windows = [metrics.wlabel(w) for w in metrics.WINDOWS]
    fams = [f for f in MAIN_FAMILIES if f in set(table["family"])]
    fig, ax = plt.subplots(figsize=(7.2, 3.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    width = 0.22
    for k, fam in enumerate(fams):
        sub = table[table["family"] == fam].set_index("window").reindex(windows)
        x = np.arange(len(windows)) + (k - (len(fams) - 1) / 2) * width
        ax.errorbar(x, 100 * sub["leak_share"], yerr=[100 * (sub["leak_share"] - sub["ci_lo"]),
                    100 * (sub["ci_hi"] - sub["leak_share"])], fmt="o", ms=6, lw=1.5,
                    capsize=0, color=COLORS[fam], label=fam.replace("_", " "))
    ax.axhline(0, color=INK2, lw=1)
    ax.set_xticks(range(len(windows)), [w.replace("-", " to ") + " before" for w in windows],
                  color=INK2, fontsize=9)
    ax.set_ylabel("Share of remaining Brier score\nremoved in the window (%)", color=INK2, fontsize=9)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK)
    ax.set_title("Where the answer reaches the price before the reveal (95% CI, by event)",
                 color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def build_report(ds: data.Dataset, out: Path, split_date: str | None = None,
                 reps: int = 2000, truth: pd.DataFrame | None = None) -> str:
    out.mkdir(parents=True, exist_ok=True)
    m = ds.markets
    fam_table = (m.groupby(["family", "subfamily", "series"]).agg(
        events=("event_ticker", "nunique"), markets=("ticker", "size"),
        multi_outcome=("mutually_exclusive", "mean")).reset_index()
        .sort_values(["family", "markets"], ascending=[True, False]))
    fam_table.to_csv(out / "families.csv", index=False)

    windows = metrics.WINDOWS + (metrics.PRE_REVEAL,)
    wp = metrics.window_prices(ds, windows, max_start_age_hours=MAX_START_AGE_H)
    wp_any = metrics.window_prices(ds, (metrics.PRE_REVEAL,))
    leak = metrics.leak_share_table(wp, by=("family",), reps=reps)
    leak_any_age = metrics.leak_share_table(wp_any, by=("family",), reps=reps)
    leak_sub = metrics.leak_share_table(wp, by=("family", "subfamily"), reps=reps)
    mention = wp[wp["subfamily"] == "mention"]
    leak_script = metrics.leak_share_table(mention, by=("script",), reps=reps) \
        if len(mention) else pd.DataFrame()
    for name, df in (("leak_share", leak), ("leak_share_subfamily", leak_sub),
                     ("leak_share_mentions_by_script", leak_script),
                     ("leak_share_no_age_limit", leak_any_age)):
        df.to_csv(out / f"{name}.csv", index=False)
    plot_leak_share(leak[leak["window"] != metrics.wlabel(metrics.PRE_REVEAL)], out / "leak_share.png")

    tt = metrics.trade_table(ds)
    mk = metrics.markout_table(tt, windows=windows + (metrics.BASELINE,), by=("family",), reps=reps)
    tax = spread.leakage_tax(mk, pre=metrics.wlabel(metrics.PRE_REVEAL),
                             base=metrics.wlabel(metrics.BASELINE))
    legs = metrics.excess_markout_by_leg(tt)
    mk.to_csv(out / "markouts.csv", index=False)
    tax.to_csv(out / "leakage_tax.csv", index=False)
    legs.to_csv(out / "excess_markout_by_leg.csv", index=False)

    pre = metrics.wlabel(metrics.PRE_REVEAL)
    calib = mirror.cross_fit_calibration(ds)
    periods = [("all", None)]
    if split_date:
        cut = int(pd.Timestamp(split_date, tz="UTC").timestamp())
        periods += [(f"before {split_date}", ("lt", cut)), (f"after {split_date}", ("ge", cut))]
    mirror_rows = []
    reveal = m.drop_duplicates("event_ticker").set_index("event_ticker")["reveal_ts"]
    for label, rule in periods:
        sub = tt
        if rule:
            keep = reveal[reveal < rule[1]] if rule[0] == "lt" else reveal[reveal >= rule[1]]
            sub = tt[tt["event_ticker"].isin(keep.index)]
        sk = mirror.skip_test(mirror.skip_bursts(ds, sub, calib))
        ls = mirror.longshot_test(sub, calib)
        mirror_rows.append({"period": label,
                            "skip_events": sk.get("events", 0), "skip_bursts": sk.get("bursts", 0),
                            "skip_hit_ratio": sk.get("hit_ratio", np.nan),
                            "skip_p": sk.get("p_value", np.nan),
                            "longshot_markets": ls.get("markets", 0),
                            "longshot_hit_ratio": ls.get("hit_ratio", np.nan),
                            "longshot_p": ls.get("p_value", np.nan)})
    mirror_df = pd.DataFrame(mirror_rows)
    mirror_df.to_csv(out / "mirror_tests.csv", index=False)

    # Placebos: where no informed baskets are expected, the skip test should
    # be quiet. If it fires here, leftover mispricing or news reactions are
    # driving it, and the main result does not count (PREREGISTRATION.md).
    placebo_rows = []
    sched = tt[tt["family"] == "scheduled_reveal"]
    cont = tt[tt["family"] == "continuous_public"]
    for label, sub, window in (
            (f"scheduled reveal, {metrics.wlabel(metrics.BASELINE)} before", sched, metrics.BASELINE),
            (f"continuous public, {pre} before", cont, metrics.PRE_REVEAL)):
        sk = mirror.skip_test(mirror.skip_bursts(ds, sub, calib, window=window))
        placebo_rows.append({"placebo": label, "events": sk.get("events", 0),
                             "bursts": sk.get("bursts", 0),
                             "hit_ratio": sk.get("hit_ratio", np.nan),
                             "p": sk.get("p_value", np.nan)})
    placebo_df = pd.DataFrame(placebo_rows)
    placebo_df.to_csv(out / "skip_placebos.csv", index=False)

    lines = [
        "# Leakage report", "",
        f"Source: `{ds.source}`. {m['event_ticker'].nunique():,} settled events, "
        f"{len(m):,} markets, {len(ds.trades):,} trades. Reveal time = earliest close "
        "in the event. Intervals resample whole events.", "",
        "## 1. Families (check these first)", "",
        "Assigned from series tickers by `families.py`; override with `--families-csv`.", "",
        fmt(fam_table.head(40), 2), "",
        "## 2. Leak share before the reveal", "",
        "Share of the remaining Brier score that disappears inside each window. "
        "Where no public news is due before the reveal it should be near zero. "
        f"Markets whose last trade before a window is more than {MAX_START_AGE_H:g} hours old "
        "are left out of that window.", "",
        "![leak share](leak_share.png)", "",
        fmt(leak), "", "By subfamily:", "", fmt(leak_sub), "",
        f"Robustness, {metrics.wlabel(metrics.PRE_REVEAL)} with no age limit:", "",
        fmt(leak_any_age), "",
    ]
    if len(leak_script):
        lines += ["Mention markets, scripted vs unscripted events (H4):", "", fmt(leak_script), ""]
    lines += [
        "## 3. What takers earn, and the spread it implies", "",
        "Markout per contract to settlement (cents), mean effective half-spread, and "
        "their sum: what takers earn beyond paying the spread.", "",
        fmt(mk), "",
        f"Leakage tax: rise in net-of-spread markout from the {metrics.wlabel(metrics.BASELINE)} "
        f"window to the {pre} window, with the Glosten-Milgrom insider share it implies at 50c.", "",
        fmt(tax), "",
        "## 4. Mirror trade and long-shot tests (day before the reveal)", "",
        "Skip test: NO baskets across an event's outcomes; do the skipped outcomes win "
        "more often than recalibrated prices say? Long-shot test: large YES bets at 35c or "
        "less; do they win more often than prices say? One-sided p-values from simulated nulls.", "",
        fmt(mirror_df), "",
        "Placebos for the skip test (should not fire; if one does, the result above does not count):", "",
        fmt(placebo_df), "",
    ]
    if truth is not None:
        t = truth.assign(style=truth["style"].replace("", "none"))
        lines += ["## Planted truth (synthetic run)", "",
                  fmt(t.groupby(["family", "style"]).agg(events=("event_ticker", "size"))
                      .reset_index()), ""]
    text = "\n".join(lines)
    (out / "report.md").write_text(text)
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="kalshi_pull folder or Becker-style data folder")
    ap.add_argument("--synthetic", action="store_true", help="run on planted-leak synthetic data")
    ap.add_argument("--families-csv", help="series,family[,subfamily] overrides")
    ap.add_argument("--split-date", help="compare mirror tests before/after (YYYY-MM-DD)")
    ap.add_argument("--out", default="leakage/report")
    ap.add_argument("--reps", type=int, default=2000)
    a = ap.parse_args(argv)
    truth = None
    if a.synthetic:
        # A displacement story with known answers: insiders in 10% of
        # scheduled-reveal events buy YES on the answer before 2026-06-09 and
        # switch to NO baskets after it; continuous-public events are clean.
        ds, truth = synth.dataset([
            synth.Spec(family="scheduled_reveal", n_events=400, leak_rate=0.1,
                       leak_style="yes", start="2026-01-05", tag="A", seed=1),
            synth.Spec(family="scheduled_reveal", n_events=400, leak_rate=0.1,
                       leak_style="basket", start="2026-06-15", tag="B", seed=2),
            synth.Spec(family="continuous_public", n_events=400, leak_rate=0.0,
                       start="2026-01-05", tag="P", seed=3)])
        a.split_date = a.split_date or "2026-06-09"
    elif a.data:
        ds = data.load(a.data, a.families_csv)
    else:
        ap.error("give --data or --synthetic")
    build_report(ds, Path(a.out), a.split_date, a.reps, truth)
    print(f"wrote {Path(a.out) / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
