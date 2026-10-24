"""Calibration of Kalshi and Polymarket prices against realized outcomes.

Input : data/markets.csv (build_dataset.py)
Output: results/fit.json, results/*.csv tables, results/*.png charts.

Model (logistic recalibration, per venue x horizon [x category]):
    logit P(Y=1) = alpha + beta * logit(price),   price clipped to [0.01, 0.99]
beta < 1: prices too extreme; beta > 1: prices too compressed toward 0.5
(the favorite-longshot pattern: longshots resolve YES less often than priced,
favorites more often). alpha shifts all prices (alpha < 0: YES overpriced).

Fit by Newton/IRLS. 95% intervals by a cluster bootstrap over events: each
replicate draws events with replacement and gives every market of an event
the event's draw count as its weight, so correlated markets (brackets of one
event, both sides of one game) move together.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "markets.csv"
RESULTS = ROOT / "results"

CLIP = 0.01
HORIZONS = ["7d", "24h", "1h"]
B_MAIN = 1000
B_SENS = 400
SEED = 20261024
REL_EDGES = np.array([0, .05, .1, .2, .3, .4, .5, .6, .7, .8, .9, .95, 1.0000001])
FLB_EDGES = np.array([0, .1, .3, .7, .9, 1.0000001])
FLB_LABELS = ["<10%", "10-30%", "30-70%", "70-90%", ">90%"]
MIN_CAT_MARKETS, MIN_CAT_EVENTS = 200, 40
SCHED = "all, scheduled close"   # drops closes triggered by the outcome itself

INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]          # blue, orange, aqua
HORIZON_COLOR = {"24h": SERIES[0], "1h": SERIES[1], "7d": SERIES[2]}
VENUE_COLOR = {"kalshi": SERIES[0], "polymarket": SERIES[1]}
VENUE_NAME = {"kalshi": "Kalshi", "polymarket": "Polymarket"}


# ----------------------------------------------------------------------------
# core statistics
# ----------------------------------------------------------------------------
def logit(p):
    p = np.asarray(p, dtype=float)
    return np.log(p / (1 - p))


def expit(z):
    with np.errstate(over="ignore"):
        return 1.0 / (1.0 + np.exp(-np.asarray(z, dtype=float)))


def clip_prices(p, eps: float = CLIP):
    return np.clip(np.asarray(p, dtype=float), eps, 1 - eps)


def irls_logistic(x, y, w=None, max_iter: int = 100, tol: float = 1e-10):
    """Weighted logistic regression of y on [1, x] by Newton-Raphson (= IRLS).

    ``w`` may be a vector (n,) or a matrix (B, n) of frequency weights, in which
    case B independent fits are solved at once. Returns (alpha, beta) arrays
    (scalars for vector weights); non-converged fits are NaN.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    single = w is None or np.ndim(w) == 1
    W = np.ones((1, x.size)) if w is None else np.atleast_2d(np.asarray(w, dtype=float))
    a = np.zeros(W.shape[0])
    b = np.zeros(W.shape[0])
    done = np.zeros(W.shape[0], dtype=bool)
    with np.errstate(all="ignore"):   # separated bootstrap replicates diverge -> NaN
        a, b, done = _newton(x, y, W, a, b, done, max_iter, tol)
    a = np.where(done & np.isfinite(a), a, np.nan)
    b = np.where(done & np.isfinite(b), b, np.nan)
    return (a[0], b[0]) if single else (a, b)


def _newton(x, y, W, a, b, done, max_iter, tol):
    for _ in range(max_iter):
        eta = a[:, None] + b[:, None] * x[None, :]
        mu = expit(eta)
        v = W * mu * (1 - mu)
        r = W * (y[None, :] - mu)
        h00, h01, h11 = v.sum(1), (v * x).sum(1), (v * x * x).sum(1)
        g0, g1 = r.sum(1), (r * x).sum(1)
        det = h00 * h11 - h01 ** 2
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        da = np.where(done, 0, da)
        db = np.where(done, 0, db)
        a, b = a + da, b + db
        done |= (np.abs(da) < tol) & (np.abs(db) < tol)
        if done.all():
            break
    return a, b, done


def event_codes(event_ids):
    _, codes = np.unique(np.asarray(event_ids).astype(str), return_inverse=True)
    return codes


def cluster_bootstrap_weights(event_ids, n_boot: int, rng) -> np.ndarray:
    """(n_boot, n_markets) frequency weights from resampling events.

    Each replicate draws as many events as there are, with replacement; a
    market's weight is the number of times its event was drawn, so all
    markets of an event always share one weight.
    """
    codes = event_codes(event_ids)
    n_ev = codes.max() + 1
    draws = rng.multinomial(n_ev, np.full(n_ev, 1.0 / n_ev), size=n_boot)
    return draws[:, codes].astype(float)


def resample_events(event_ids, rng) -> np.ndarray:
    """Row indices of one cluster-bootstrap replicate (events with replacement)."""
    ids = np.asarray(event_ids).astype(str)
    uniq = np.unique(ids)
    pick = rng.choice(uniq, size=uniq.size, replace=True)
    groups = {e: np.flatnonzero(ids == e) for e in uniq}
    return np.concatenate([groups[e] for e in pick])


def pct_ci(samples, level: float = 0.95):
    s = np.asarray(samples, dtype=float)
    s = s[np.isfinite(s)]
    if s.size == 0:
        return [math.nan, math.nan]
    lo, hi = np.percentile(s, [50 * (1 - level), 100 - 50 * (1 - level)])
    return [float(lo), float(hi)]


def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def log_loss(p, y, eps: float = CLIP):
    p = clip_prices(p, eps)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def murphy(p, y, edges=np.linspace(0, 1.0000001, 11)):
    """Binned Murphy decomposition: BS = REL - RES + UNC + within-bin term."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    n, obar = p.size, y.mean()
    k = np.clip(np.digitize(p, edges) - 1, 0, len(edges) - 2)
    rel = res = 0.0
    for b in np.unique(k):
        m = k == b
        rel += m.sum() * (p[m].mean() - y[m].mean()) ** 2
        res += m.sum() * (y[m].mean() - obar) ** 2
    rel, res, unc = rel / n, res / n, obar * (1 - obar)
    bs = brier(p, y)
    return {"brier": bs, "reliability": rel, "resolution": res, "uncertainty": unc,
            "within_bin": bs - (rel - res + unc)}


def binned_table(p, y, event_ids, edges, labels=None, n_boot=B_MAIN, seed=SEED):
    """Per-bin n, events, mean price, realized frequency and their difference,
    with cluster-bootstrap 95% intervals for frequency and difference."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    k = np.clip(np.digitize(p, edges) - 1, 0, len(edges) - 2)
    nb = len(edges) - 1
    onehot = np.zeros((p.size, nb))
    onehot[np.arange(p.size), k] = 1
    W = cluster_bootstrap_weights(event_ids, n_boot, np.random.default_rng(seed))
    cnt = W @ onehot
    with np.errstate(invalid="ignore", divide="ignore"):
        freq_b = (W @ (onehot * y[:, None])) / cnt
        price_b = (W @ (onehot * p[:, None])) / cnt
    ev = np.asarray(event_ids).astype(str)
    rows = []
    for b in range(nb):
        m = k == b
        if not m.any():
            continue
        freq, price = y[m].mean(), p[m].mean()
        rows.append({
            "bin": labels[b] if labels else f"[{edges[b]:.2f},{min(edges[b + 1], 1):.2f})",
            "lo": float(edges[b]), "hi": float(min(edges[b + 1], 1.0)),
            "n_markets": int(m.sum()), "n_events": int(np.unique(ev[m]).size),
            "mean_price": float(price), "realized_freq": float(freq),
            "freq_ci": pct_ci(freq_b[:, b]),
            "freq_minus_price": float(freq - price),
            "diff_ci": pct_ci(freq_b[:, b] - price_b[:, b]),
        })
    return rows


def fit_with_ci(p, y, event_ids, n_boot=B_MAIN, seed=SEED, eps=CLIP):
    x = logit(clip_prices(p, eps))
    y = np.asarray(y, float)
    a, b = irls_logistic(x, y)
    rng = np.random.default_rng(seed)
    A, Bt = [], []
    for start in range(0, n_boot, 100):
        W = cluster_bootstrap_weights(event_ids, min(100, n_boot - start), rng)
        aa, bb = irls_logistic(x, y, W)
        A.append(aa)
        Bt.append(bb)
    A, Bt = np.concatenate(A), np.concatenate(Bt)
    grid = np.linspace(0.01, 0.99, 99)
    lg = logit(grid)
    curves = expit(A[:, None] + Bt[:, None] * lg[None, :])
    return {
        "alpha": float(a), "alpha_ci": pct_ci(A),
        "beta": float(b), "beta_ci": pct_ci(Bt),
        "p_beta_le_1": float(np.mean(Bt[np.isfinite(Bt)] <= 1)) if np.isfinite(Bt).any() else None,
        "n_boot_ok": int(np.isfinite(Bt).sum()),
        "_curve": {"price": grid.tolist(), "fit": expit(a + b * lg).tolist(),
                   "lo": np.nanpercentile(curves, 2.5, axis=0).tolist(),
                   "hi": np.nanpercentile(curves, 97.5, axis=0).tolist()},
    }


# ----------------------------------------------------------------------------
# analysis
# ----------------------------------------------------------------------------
def horizon_frame(df, venue, h, extra=None):
    g = df[(df["venue"] == venue) & (df[f"status_{h}"] == "ok")].copy()
    if extra is not None:
        g = g[extra(g)]
    g["p"] = g[f"price_{h}"].astype(float)
    return g


def summary_block(g, n_boot=B_MAIN, seed=SEED, eps=CLIP):
    p, y, ev = g["p"].to_numpy(), g["outcome"].to_numpy(float), g["event_id"].astype(str).to_numpy()
    out = {"n_markets": int(len(g)), "n_events": int(np.unique(ev).size),
           "yes_rate": float(y.mean()), "mean_price": float(p.mean()),
           "log_loss": log_loss(p, y, eps)}
    out.update(murphy(p, y))
    out.update(fit_with_ci(p, y, ev, n_boot=n_boot, seed=seed, eps=eps))
    return out


SENSITIVITY = {
    "main": None,
    "volume >= 10x threshold": lambda g: g["volume"] >= 10 * (1000.0),
    "staleness <= 2 h": "fresh",
    "one random market per event": "one_per_event",
    "price in [0.02, 0.98]": lambda g: (g["p"] >= 0.02) & (g["p"] <= 0.98),
    "clip at 0.001 instead of 0.01": "clip001",
    "Kalshi: bid/ask mid instead of last trade": "mid",
    "scheduled close only (drop occurrence-triggered closes)": "scheduled",
    "same markets priced at both 24h and 1h": "both",
    "excluding sports": lambda g: g["category"] != "sports",
    "excluding weather": lambda g: g["category"] != "weather",
}


def sensitivity_rows(df, venue, h):
    rows = []
    for name, rule in SENSITIVITY.items():
        eps = CLIP
        if rule == "mid":
            if venue != "kalshi":
                continue
            g = df[(df["venue"] == venue) & (df[f"mid_status_{h}"] == "ok")].copy()
            g["p"] = g[f"mid_price_{h}"].astype(float)
        else:
            g = horizon_frame(df, venue, h)
            if rule == "fresh":
                g = g[g[f"staleness_h_{h}"] <= 2]
            elif rule == "one_per_event":
                g = g.sample(frac=1, random_state=SEED).drop_duplicates("event_id")
            elif rule == "clip001":
                eps = 0.001
            elif rule == "scheduled":
                g = g[g["scheduled_close"].astype(bool)]
            elif rule == "both":
                g = g[(g["status_24h"] == "ok") & (g["status_1h"] == "ok")]
            elif callable(rule):
                g = g[rule(g)]
        if len(g) < 100 or g["event_id"].nunique() < 30:
            continue
        p, y, ev = g["p"].to_numpy(), g["outcome"].to_numpy(float), g["event_id"].astype(str).to_numpy()
        fit = fit_with_ci(p, y, ev, n_boot=B_SENS, eps=eps)
        fit.pop("_curve")
        rows.append({"venue": venue, "horizon": h, "variant": name,
                     "n_markets": int(len(g)), "n_events": int(np.unique(ev).size),
                     "brier": brier(p, y), **fit})
    return rows


def run(df: pd.DataFrame, n_boot: int = B_MAIN) -> dict:
    fits, flb, rel, sens = [], [], [], []
    curves = {}
    for venue in sorted(df["venue"].unique()):
        for h in HORIZONS:
            g = horizon_frame(df, venue, h)
            if len(g) < 100:
                continue
            groups = [("all", g), (SCHED, g[g["scheduled_close"].astype(bool)])] + [
                (c, gc) for c, gc in g.groupby("category")
                if len(gc) >= MIN_CAT_MARKETS and gc["event_id"].nunique() >= MIN_CAT_EVENTS]
            for cat, gc in groups:
                s = summary_block(gc, n_boot=n_boot)
                curve = s.pop("_curve")
                if cat == "all":
                    curves[(venue, h)] = curve
                elif cat == SCHED:
                    curves[(venue, h, "sched")] = curve
                fits.append({"venue": venue, "horizon": h, "category": cat, **s})
            ev = g["event_id"].astype(str).to_numpy()
            for r in binned_table(g["p"], g["outcome"], ev, REL_EDGES, n_boot=n_boot):
                rel.append({"venue": venue, "horizon": h, **r})
            for r in binned_table(g["p"], g["outcome"], ev, FLB_EDGES, FLB_LABELS, n_boot=n_boot):
                flb.append({"venue": venue, "horizon": h, **r})
            gs = g[g["scheduled_close"].astype(bool)]
            for r in binned_table(gs["p"], gs["outcome"], gs["event_id"].astype(str), FLB_EDGES,
                                  FLB_LABELS, n_boot=n_boot):
                flb.append({"venue": venue, "horizon": h, "category": SCHED, **r})
            for c, gc in g.groupby("category"):
                if len(gc) >= MIN_CAT_MARKETS and gc["event_id"].nunique() >= MIN_CAT_EVENTS:
                    for r in binned_table(gc["p"], gc["outcome"], gc["event_id"].astype(str),
                                          FLB_EDGES, FLB_LABELS, n_boot=n_boot):
                        flb.append({"venue": venue, "horizon": h, "category": c, **r})
            if h in ("24h", "1h"):
                sens.extend(sensitivity_rows(df, venue, h))
    for r in flb:
        r.setdefault("category", "all")
    return {"fits": fits, "reliability": rel, "flb": flb, "sensitivity": sens,
            "curves": curves, "diagnostics": near_certain(df)}


def near_certain(df):
    """Share of prices at <= 2c or >= 98c and how often those resolve the
    'wrong' way, by venue, horizon and reference-time source. A jump in the
    share between 24 h and 1 h that comes with zero misses is the signature of
    an outcome already known before the reference close."""
    rows = []
    df = df.assign(close_source=np.where(df["scheduled_close"].astype(bool),
                                         df["close_source"] + " (scheduled)",
                                         df["close_source"] + " (triggered)"))
    for (venue, src), g0 in df.groupby(["venue", "close_source"]):
        for h in HORIZONS:
            g = g0[g0[f"status_{h}"] == "ok"]
            if len(g) < 50:
                continue
            p, y = g[f"price_{h}"].astype(float), g["outcome"].astype(float)
            ext = (p <= 0.02) | (p >= 0.98)
            wrong = ((p <= 0.02) & (y == 1)) | ((p >= 0.98) & (y == 0))
            rows.append({"venue": venue, "close_source": src, "horizon": h,
                         "n_markets": int(len(g)), "share_near_certain": float(ext.mean()),
                         "miss_rate_near_certain": float(wrong[ext].mean()) if ext.any() else None})
    return rows


# ----------------------------------------------------------------------------
# plots
# ----------------------------------------------------------------------------
def _style(ax, title, xlabel="Market price", ylabel="Realized YES frequency"):
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK2)
        ax.spines[s].set_linewidth(0.8)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title(title, color=INK, fontsize=11, loc="left")
    ax.set_xlabel(xlabel, color=INK2, fontsize=9)
    ax.set_ylabel(ylabel, color=INK2, fontsize=9)


def _diag(ax):
    ax.plot([0, 1], [0, 1], color=INK2, linewidth=1, linestyle=(0, (4, 3)),
            label="Perfect calibration", zorder=1)
    ax.set_xlim(-0.01, 1.01)
    ax.set_ylim(-0.01, 1.01)
    ax.set_aspect("equal")


def plot_all(res: dict, out: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    files = []
    rel = pd.DataFrame(res["reliability"])
    fits = pd.DataFrame(res["fits"])
    for venue in sorted(rel["venue"].unique()):
        # one reliability diagram per venue and horizon, with counts
        for h in HORIZONS:
            r = rel[(rel.venue == venue) & (rel.horizon == h)]
            if r.empty:
                continue
            fig, ax = plt.subplots(figsize=(5.2, 5.2), dpi=150)
            _style(ax, f"{VENUE_NAME[venue]}, {h} before close: reliability")
            _diag(ax)
            lo = r["realized_freq"] - r["freq_ci"].str[0]
            hi = r["freq_ci"].str[1] - r["realized_freq"]
            ax.errorbar(r["mean_price"], r["realized_freq"], yerr=[lo, hi], fmt="o",
                        color=HORIZON_COLOR[h], markersize=5, elinewidth=1.4, capsize=0,
                        markeredgecolor=SURFACE, markeredgewidth=1, zorder=3)
            for _, b in r.iterrows():   # count label on the side away from the diagonal
                below = b.realized_freq >= b.mean_price
                y_txt = b.freq_ci[0] - 0.015 if below else b.freq_ci[1] + 0.015
                ax.text(b.mean_price, min(max(y_txt, 0.005), 0.995), f"{b.n_markets}",
                        ha="center", va="top" if below else "bottom", fontsize=6.5, color=INK2)
            f = fits[(fits.venue == venue) & (fits.horizon == h) & (fits.category == "all")]
            if not f.empty:
                f = f.iloc[0]
                ax.text(0.02, 0.97, f"{f.n_markets} markets, {f.n_events} events\n"
                        f"beta = {f.beta:.2f} [{f.beta_ci[0]:.2f}, {f.beta_ci[1]:.2f}]\n"
                        f"alpha = {f.alpha:.2f} [{f.alpha_ci[0]:.2f}, {f.alpha_ci[1]:.2f}]",
                        transform=ax.transAxes, va="top", fontsize=8, color=INK)
            ax.text(0.98, 0.02, "bars: 95% event-cluster bootstrap\nlabels: markets per bin",
                    transform=ax.transAxes, ha="right", fontsize=7, color=INK2)
            name = f"reliability_{venue}_{h}.png"
            fig.tight_layout()
            fig.savefig(out / name)
            plt.close(fig)
            files.append(name)

        # horizons overlaid
        fig, ax = plt.subplots(figsize=(5.2, 5.2), dpi=150)
        _style(ax, f"{VENUE_NAME[venue]}: reliability by horizon")
        _diag(ax)
        for h in HORIZONS:
            r = rel[(rel.venue == venue) & (rel.horizon == h)]
            if r.empty:
                continue
            ax.plot(r["mean_price"], r["realized_freq"], "-o", color=HORIZON_COLOR[h],
                    linewidth=2, markersize=5, markeredgecolor=SURFACE, label=f"{h} before close")
        ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower right")
        name = f"reliability_{venue}_horizons.png"
        fig.tight_layout()
        fig.savefig(out / name)
        plt.close(fig)
        files.append(name)

        # recalibration curves by horizon
        fig, ax = plt.subplots(figsize=(5.2, 5.2), dpi=150)
        _style(ax, f"{VENUE_NAME[venue]}: logistic recalibration",
               ylabel="Fitted P(YES | price)")
        _diag(ax)
        for h in HORIZONS:
            c = res["curves"].get((venue, h))
            if not c:
                continue
            ax.fill_between(c["price"], c["lo"], c["hi"], color=HORIZON_COLOR[h], alpha=0.18,
                            linewidth=0)
            ax.plot(c["price"], c["fit"], color=HORIZON_COLOR[h], linewidth=2,
                    label=f"{h} before close")
        ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower right")
        name = f"recalibration_{venue}.png"
        fig.tight_layout()
        fig.savefig(out / name)
        plt.close(fig)
        files.append(name)

    # venues compared at 24h: recalibration curves
    fig, ax = plt.subplots(figsize=(5.2, 5.2), dpi=150)
    _style(ax, "Recalibration 24 h before close", ylabel="Fitted P(YES | price)")
    _diag(ax)
    for venue in sorted(rel["venue"].unique()):
        c = res["curves"].get((venue, "24h"))
        if not c:
            continue
        ax.fill_between(c["price"], c["lo"], c["hi"], color=VENUE_COLOR[venue], alpha=0.18,
                        linewidth=0)
        ax.plot(c["price"], c["fit"], color=VENUE_COLOR[venue], linewidth=2,
                label=VENUE_NAME[venue])
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower right")
    fig.tight_layout()
    fig.savefig(out / "recalibration_venues_24h.png")
    plt.close(fig)
    files.append("recalibration_venues_24h.png")

    # same fits as a deviation from the diagonal (easier to read), per horizon
    for h in ("24h", "1h"):
        fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150)
        _style(ax, f"Fitted P(YES) minus price, {h} before close",
               ylabel="Fitted - price (percentage points)")
        for venue in sorted(rel["venue"].unique()):
            c = res["curves"].get((venue, h))
            if not c:
                continue
            x = np.asarray(c["price"])
            ax.fill_between(x, 100 * (np.asarray(c["lo"]) - x), 100 * (np.asarray(c["hi"]) - x),
                            color=VENUE_COLOR[venue], alpha=0.18, linewidth=0)
            ax.plot(x, 100 * (np.asarray(c["fit"]) - x), color=VENUE_COLOR[venue], linewidth=2,
                    label=f"{VENUE_NAME[venue]}, all markets")
            cs = res["curves"].get((venue, h, "sched"))
            if cs:
                ax.plot(x, 100 * (np.asarray(cs["fit"]) - x), color=VENUE_COLOR[venue],
                        linewidth=1.6, linestyle=(0, (5, 2)),
                        label=f"{VENUE_NAME[venue]}, scheduled close only")
        ax.axhline(0, color=INK2, linewidth=1)
        ax.set_xlim(0, 1)
        ax.legend(frameon=False, fontsize=8, labelcolor=INK)
        ax.text(0.99, 0.02, "bands (all markets): 95% event-cluster bootstrap", transform=ax.transAxes,
                ha="right", fontsize=7, color=INK2)
        fig.tight_layout()
        fig.savefig(out / f"recalibration_deviation_{h}.png")
        plt.close(fig)
        files.append(f"recalibration_deviation_{h}.png")

    # favorite-longshot: realized minus price by bucket at 24h
    flb = pd.DataFrame(res["flb"])
    flb = flb[(flb.category == "all") & (flb.horizon == "24h")]
    if not flb.empty:
        fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150)
        _style(ax, "Realized frequency minus price, 24 h before close",
               xlabel="Price bucket", ylabel="Realized - price (percentage points)")
        venues = sorted(flb["venue"].unique())
        xs = np.arange(len(FLB_LABELS))
        for i, venue in enumerate(venues):
            r = flb[flb.venue == venue].set_index("bin").reindex(FLB_LABELS)
            off = (i - (len(venues) - 1) / 2) * 0.18
            d = 100 * r["freq_minus_price"]
            lo = d - 100 * r["diff_ci"].str[0]
            hi = 100 * r["diff_ci"].str[1] - d
            ax.errorbar(xs + off, d, yerr=[lo, hi], fmt="o", color=VENUE_COLOR[venue],
                        markersize=6, elinewidth=1.6, capsize=0, label=VENUE_NAME[venue],
                        markeredgecolor=SURFACE)
        ax.axhline(0, color=INK2, linewidth=1)
        ax.set_xticks(xs, FLB_LABELS)
        ax.legend(frameon=False, fontsize=8, labelcolor=INK)
        fig.tight_layout()
        fig.savefig(out / "favorite_longshot_24h.png")
        plt.close(fig)
        files.append("favorite_longshot_24h.png")
    return files


# ----------------------------------------------------------------------------
def _round(o, nd=4):
    if isinstance(o, float):
        return round(o, nd) if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v, nd) for v in o]
    if isinstance(o, (np.floating,)):
        return _round(float(o), nd)
    if isinstance(o, (np.integer,)):
        return int(o)
    return o


def write_outputs(res: dict, df: pd.DataFrame, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fits = res["fits"]
    sim = {}
    for f in fits:
        if f["category"] in ("all", SCHED):
            key = "all_markets" if f["category"] == "all" else "scheduled_close"
            sim.setdefault(f["venue"], {}).setdefault(f["horizon"], {})[key] = {
                "alpha": f["alpha"], "beta": f["beta"],
                "alpha_ci": f["alpha_ci"], "beta_ci": f["beta_ci"],
                # price as a function of the true probability q:
                # logit(price) = logit_bias + logit_slope * logit(q)
                "logit_bias": -f["alpha"] / f["beta"], "logit_slope": 1 / f["beta"]}
    doc = {
        "model": "logit P(Y=1) = alpha + beta * logit(clip(price, 0.01, 0.99))",
        "price_definition": {
            "kalshi": "last trade in the latest hourly candle ending at or before close_time - h",
            "polymarket": "last CLOB prices-history point (hourly) at or before ref - h, "
                          "ref = min(closedTime, endDate, gameStartTime)"},
        "max_staleness_hours": 24, "clip": CLIP,
        "bootstrap": {"unit": "event", "replicates": B_MAIN, "sensitivity_replicates": B_SENS,
                      "interval": "percentile 95%", "seed": SEED},
        "category_min": {"markets": MIN_CAT_MARKETS, "events": MIN_CAT_EVENTS},
        "simulator": sim,
        "fits": fits,
        "favorite_longshot": res["flb"],
        "sensitivity": res["sensitivity"],
        "near_certain_diagnostic": res["diagnostics"],
    }
    (out / "fit.json").write_text(json.dumps(_round(doc), indent=1))
    pd.DataFrame(res["reliability"]).to_csv(out / "reliability_bins.csv", index=False)
    pd.DataFrame(res["flb"]).to_csv(out / "favorite_longshot.csv", index=False)
    cols = ["venue", "horizon", "category", "n_markets", "n_events", "yes_rate", "mean_price",
            "alpha", "alpha_ci", "beta", "beta_ci", "brier", "log_loss", "reliability",
            "resolution", "uncertainty", "within_bin"]
    pd.DataFrame(fits)[cols].to_csv(out / "fits.csv", index=False)
    pd.DataFrame(res["sensitivity"]).to_csv(out / "sensitivity.csv", index=False)


def _ci(v, ci, nd=2, pct=False):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    k = 100 if pct else 1
    lo, hi = ci
    return f"{k * v:+.{nd}f} [{k * lo:+.{nd}f}, {k * hi:+.{nd}f}]" if pct else \
        f"{v:.{nd}f} [{lo:.{nd}f}, {hi:.{nd}f}]"


def _md(rows, cols):
    head = "| " + " | ".join(cols) + " |\n|" + "|".join("---" for _ in cols) + "|\n"
    return head + "".join("| " + " | ".join(str(r[c]) for c in cols) + " |\n" for r in rows)


def write_tables_md(res: dict, out: Path, summary_path: Path) -> None:
    """All report tables as markdown (results/tables.md), generated from the fits."""
    parts = []
    if summary_path.exists():
        summ = json.loads(summary_path.read_text())
        for venue, v in summ["venues"].items():
            rows = [{"step": s["step"], "remaining": s["remaining"], "removed": s["removed"]}
                    for s in v["filters"]["steps"]]
            for h, hv in v["horizons"].items():
                sc = hv["status_counts"]
                rows.append({"step": f"price available {h} before close (stale > 24 h: "
                                     f"{sc.get('stale', 0)}, no price: {sc.get('none', 0)})",
                             "remaining": hv["n_ok"], "removed": sc.get("stale", 0) + sc.get("none", 0)})
            parts.append(f"### Filters: {VENUE_NAME[venue]}\n\n" + _md(rows, ["step", "remaining", "removed"]))
    fits = [f for f in res["fits"] if f["category"] in ("all", SCHED)]
    rows = [{"venue": VENUE_NAME[f["venue"]], "h": f["horizon"],
             "sample": "all" if f["category"] == "all" else "scheduled close",
             "markets": f["n_markets"],
             "events": f["n_events"], "YES rate": f"{f['yes_rate']:.3f}",
             "Brier": f"{f['brier']:.4f}", "log loss": f"{f['log_loss']:.4f}",
             "REL": f"{f['reliability']:.4f}", "RES": f"{f['resolution']:.4f}",
             "UNC": f"{f['uncertainty']:.4f}",
             "alpha [95% CI]": _ci(f["alpha"], f["alpha_ci"]),
             "beta [95% CI]": _ci(f["beta"], f["beta_ci"])} for f in fits]
    parts.append("### Scores and recalibration fit, all categories\n\n" + _md(
        rows, ["venue", "h", "sample", "markets", "events", "YES rate", "Brier", "log loss", "REL",
               "RES", "UNC", "alpha [95% CI]", "beta [95% CI]"]))
    cats = [f for f in res["fits"] if f["category"] not in ("all", SCHED)]
    for h in ("24h", "1h", "7d"):
        rows = [{"venue": VENUE_NAME[f["venue"]], "category": f["category"],
                 "markets": f["n_markets"], "events": f["n_events"],
                 "Brier": f"{f['brier']:.4f}",
                 "alpha [95% CI]": _ci(f["alpha"], f["alpha_ci"]),
                 "beta [95% CI]": _ci(f["beta"], f["beta_ci"])}
                for f in cats if f["horizon"] == h]
        if rows:
            parts.append(f"### By category, {h} before close "
                         f"(categories with >= {MIN_CAT_MARKETS} markets and >= {MIN_CAT_EVENTS} events)\n\n"
                         + _md(rows, ["venue", "category", "markets", "events", "Brier",
                                      "alpha [95% CI]", "beta [95% CI]"]))
    for h in ("24h", "1h", "7d"):
        rows = [{"venue": VENUE_NAME[r["venue"]], "bucket": r["bin"], "markets": r["n_markets"],
                 "events": r["n_events"], "avg price": f"{r['mean_price']:.3f}",
                 "realized": f"{r['realized_freq']:.3f}",
                 "realized - price, pp [95% CI]": _ci(r["freq_minus_price"], r["diff_ci"], 1, True)}
                for r in res["flb"] if r["horizon"] == h and r["category"] in ("all", SCHED)]
        for r, src in zip(rows, [r for r in res["flb"] if r["horizon"] == h
                                 and r["category"] in ("all", SCHED)]):
            r["sample"] = "all" if src["category"] == "all" else "scheduled close"
        if rows:
            parts.append(f"### Favorite-longshot table, {h} before close\n\n" + _md(
                rows, ["venue", "sample", "bucket", "markets", "events", "avg price", "realized",
                       "realized - price, pp [95% CI]"]))
    rows = [{"venue": VENUE_NAME[r["venue"]], "category": r["category"], "h": r["horizon"],
             "bucket": r["bin"], "markets": r["n_markets"],
             "realized - price, pp [95% CI]": _ci(r["freq_minus_price"], r["diff_ci"], 1, True)}
            for r in res["flb"] if r["category"] not in ("all", SCHED) and r["horizon"] == "24h"
            and r["bin"] in ("<10%", ">90%")]
    if rows:
        parts.append("### Extreme buckets by category, 24h\n\n" + _md(
            rows, ["venue", "category", "h", "bucket", "markets", "realized - price, pp [95% CI]"]))
    for h in ("24h", "1h"):
        rows = [{"venue": VENUE_NAME[r["venue"]], "variant": r["variant"], "markets": r["n_markets"],
                 "events": r["n_events"], "alpha [95% CI]": _ci(r["alpha"], r["alpha_ci"]),
                 "beta [95% CI]": _ci(r["beta"], r["beta_ci"])}
                for r in res["sensitivity"] if r["horizon"] == h]
        if rows:
            parts.append(f"### Sensitivity, {h} before close ({B_SENS} bootstrap replicates)\n\n"
                         + _md(rows, ["venue", "variant", "markets", "events",
                                      "alpha [95% CI]", "beta [95% CI]"]))
    rows = [{"venue": VENUE_NAME[r["venue"]], "reference close": r["close_source"], "h": r["horizon"],
             "markets": r["n_markets"], "share at <=2c or >=98c": f"{r['share_near_certain']:.3f}",
             "of those, resolved against the price":
                 "n/a" if r["miss_rate_near_certain"] is None else f"{r['miss_rate_near_certain']:.4f}"}
            for r in res.get("diagnostics", [])]
    if rows:
        parts.append("### Near-certain prices by reference-close source (look-ahead diagnostic)\n\n"
                     + _md(rows, ["venue", "reference close", "h", "markets",
                                  "share at <=2c or >=98c", "of those, resolved against the price"]))
    for h in ("24h", "1h"):
        rows = [{"venue": VENUE_NAME[r["venue"]], "bin": r["bin"], "markets": r["n_markets"],
                 "events": r["n_events"], "avg price": f"{r['mean_price']:.3f}",
                 "realized [95% CI]": _ci(r["realized_freq"], r["freq_ci"], 3)}
                for r in res["reliability"] if r["horizon"] == h]
        if rows:
            parts.append(f"### Reliability bins, {h} before close\n\n" + _md(
                rows, ["venue", "bin", "markets", "events", "avg price", "realized [95% CI]"]))
    (out / "tables.md").write_text("# Generated tables (analyze.py)\n\n" + "\n".join(parts))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--out", type=Path, default=RESULTS)
    ap.add_argument("--boot", type=int, default=B_MAIN)
    args = ap.parse_args(argv)
    df = pd.read_csv(args.data, dtype={"event_id": str, "market_id": str})
    res = run(df, n_boot=args.boot)
    write_outputs(res, df, args.out)
    write_tables_md(res, args.out, args.out / "dataset_summary.json")
    files = plot_all(res, args.out)
    for f in res["fits"]:
        if f["category"] == "all":
            print(f"{f['venue']:<11} {f['horizon']:>3}  n={f['n_markets']:>6} ev={f['n_events']:>5}  "
                  f"alpha={f['alpha']:+.3f} [{f['alpha_ci'][0]:+.3f},{f['alpha_ci'][1]:+.3f}]  "
                  f"beta={f['beta']:.3f} [{f['beta_ci'][0]:.3f},{f['beta_ci'][1]:.3f}]  "
                  f"brier={f['brier']:.4f}")
    print(f"wrote {args.out}/fit.json and {len(files)} charts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
