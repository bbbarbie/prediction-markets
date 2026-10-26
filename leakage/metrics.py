"""Leak share, taker markouts and effective spreads, clustered by event.

Leak share of a window [R - a, R - b] before the reveal R:

    L = 1 - sum_j (Y_j - P_j(R - b))^2 / sum_j (Y_j - P_j(R - a))^2

the share of the remaining Brier score that disappears inside the window.
If prices are martingales, the expected drop equals the variance of the price
move, so L is the share of remaining uncertainty resolved in the window. Where
no public news is due before the reveal, L should be about zero; information
that reaches the price early pushes it above zero. Price noise of equal size
at both edges (bid-ask bounce) inflates both sums alike and pulls L toward
zero. Unequal noise does not: with noise variances s_a and s_b at the start
and end, L becomes (A - B + s_a - s_b) / (A + s_a), so a stale or noisier
start price pushes L up. window_prices() can drop stale start prices.

Taker markout of one trade, per contract, held to settlement:

    m = side * (Y - P)        side = +1 taker bought YES, -1 taker bought NO

Every statistic here is a ratio of sums over markets or trades. Markets in
the same event share one outcome draw, so uncertainty is computed by event:
a cluster-robust delta-method standard error, and a percentile bootstrap that
resamples whole events.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HOUR = 3600
WINDOWS = ((168.0, 24.0), (24.0, 6.0), (6.0, 1.0))    # hours before reveal
PRE_REVEAL = (24.0, 1.0)                               # the quiet day before
BASELINE = (336.0, 168.0)                              # two weeks to one week out
LONGSHOT, FAVORITE = 0.35, 0.65


def wlabel(w) -> str:
    def h(x):
        return f"{x / 24:g}d" if x >= 48 else f"{x:g}h"
    return f"{h(w[0])}-{h(w[1])}"


def price_before(ts: np.ndarray, price: np.ndarray, t) -> np.ndarray:
    """Last trade price strictly before t (vectorised over t); NaN if none."""
    idx = np.searchsorted(ts, np.atleast_1d(t), side="left") - 1
    out = np.where(idx >= 0, price[np.clip(idx, 0, None)], np.nan)
    return out


# --------------------------------------------------------------------------
# Cluster statistics for ratios of sums
# --------------------------------------------------------------------------

def ratio_by_cluster(num: np.ndarray, den: np.ndarray) -> tuple[float, float]:
    """R = sum(num)/sum(den) over clusters, with a cluster-robust SE."""
    num, den = np.asarray(num, float), np.asarray(den, float)
    n = len(num)
    D = den.sum()
    if n < 2 or D <= 0:
        return float("nan"), float("nan")
    R = num.sum() / D
    u = num - R * den
    se = np.sqrt(n / (n - 1) * np.sum(u ** 2)) / D
    return float(R), float(se)


def bootstrap_ratio(num, den, reps: int = 2000, seed: int = 7) -> tuple[float, float]:
    """95% percentile interval of sum(num)/sum(den), resampling clusters."""
    num, den = np.asarray(num, float), np.asarray(den, float)
    n = len(num)
    if n < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    w = rng.multinomial(n, np.full(n, 1.0 / n), size=reps)
    d = w @ den
    r = np.where(d > 0, (w @ num) / np.where(d > 0, d, 1), np.nan)
    lo, hi = np.nanpercentile(r, [2.5, 97.5])
    return float(lo), float(hi)


def diff_of_ratios(n1, d1, n2, d2) -> tuple[float, float]:
    """(sum n1/sum d1) - (sum n2/sum d2) over the same clusters, cluster SE."""
    n1, d1, n2, d2 = (np.asarray(x, float) for x in (n1, d1, n2, d2))
    n = len(n1)
    D1, D2 = d1.sum(), d2.sum()
    if n < 2 or D1 <= 0 or D2 <= 0:
        return float("nan"), float("nan")
    R1, R2 = n1.sum() / D1, n2.sum() / D2
    u = (n1 - R1 * d1) / D1 - (n2 - R2 * d2) / D2
    return float(R1 - R2), float(np.sqrt(n / (n - 1) * np.sum(u ** 2)))


# --------------------------------------------------------------------------
# Leak share
# --------------------------------------------------------------------------

def window_prices(ds, windows=WINDOWS, max_start_age_hours: float | None = None) -> pd.DataFrame:
    """One row per (market, window) with prices at both window edges.

    A start price can be stale: with no trade for a while before the window
    opens, news that arrived before the window first shows up in a trade
    inside it, and gets counted as resolved inside it. max_start_age_hours
    drops markets whose last trade before the window is older than that.
    (A stale end price is harmless: no trades in the window, no change.)"""
    paths = ds.paths()
    rows = []
    for m in ds.markets.itertuples(index=False):
        if m.ticker not in paths:
            continue
        ts, price, _, _ = paths[m.ticker]
        for w in windows:
            t = np.array([m.reveal_ts - w[0] * HOUR, m.reveal_ts - w[1] * HOUR])
            idx = np.searchsorted(ts, t, side="left") - 1
            if idx[0] < 0:
                continue
            age = (t[0] - ts[idx[0]]) / HOUR
            if max_start_age_hours is not None and age > max_start_age_hours:
                continue
            pa, pb = price[idx[0]], price[idx[1]]
            rows.append((m.ticker, m.event_ticker, m.family, m.subfamily, m.script,
                         bool(m.mutually_exclusive), wlabel(w), m.y, pa, pb, age))
    cols = ["ticker", "event_ticker", "family", "subfamily", "script",
            "mutually_exclusive", "window", "y", "p_start", "p_end", "start_age_h"]
    df = pd.DataFrame(rows, columns=cols)
    df["brier_start"] = (df["y"] - df["p_start"]) ** 2
    df["brier_end"] = (df["y"] - df["p_end"]) ** 2
    return df


def event_brier(wp: pd.DataFrame, by=("family",)) -> pd.DataFrame:
    """Per-event sums of start/end Brier terms (the clusters for L)."""
    keys = list(by) + ["window", "event_ticker"]
    return wp.groupby(keys, sort=False).agg(
        brier_start=("brier_start", "sum"), brier_end=("brier_end", "sum"),
        markets=("ticker", "size")).reset_index()


def leak_share_table(wp: pd.DataFrame, by=("family",), reps: int = 2000) -> pd.DataFrame:
    ev = event_brier(wp, by)
    out = []
    for key, g in ev.groupby(list(by) + ["window"], sort=False):
        R, se = ratio_by_cluster(g["brier_end"], g["brier_start"])
        lo, hi = bootstrap_ratio(g["brier_end"], g["brier_start"], reps)
        out.append((*key, len(g), int(g["markets"].sum()),
                    g["brier_start"].sum() / max(len(g), 1),
                    1 - R, se, 1 - hi, 1 - lo, (1 - R) / se if se > 0 else np.nan))
    cols = list(by) + ["window", "events", "markets", "brier_start_per_event",
                       "leak_share", "se", "ci_lo", "ci_hi", "z"]
    return pd.DataFrame(out, columns=cols)


# --------------------------------------------------------------------------
# Trades: markouts, legs, effective spread
# --------------------------------------------------------------------------

def leg_of(price: np.ndarray, side: np.ndarray) -> np.ndarray:
    """What the taker bought: '<yes|no>_<longshot|middle|favorite>' by the
    price paid for the contract bought (YES price, or 1 - YES price for NO)."""
    paid = np.where(side > 0, price, 1 - price)
    bucket = np.where(paid <= LONGSHOT, "longshot",
                      np.where(paid >= FAVORITE, "favorite", "middle"))
    return np.char.add(np.where(side > 0, "yes_", "no_"), bucket.astype(str))


def effective_half_spread(ts, price, side, lookback_s: int = 600) -> np.ndarray:
    """Per trade: half the gap between the latest YES-taker price (an ask) and
    the latest NO-taker price (a bid) in the previous lookback_s seconds.
    Signed: when prices moved between the two prints the gap can be negative;
    keeping those values makes the average unbiased (dropping them would bias
    it up). NaN when either side has no print in the lookback."""
    n = len(ts)
    out = np.full(n, np.nan)
    last_ask_t = last_bid_t = -np.inf
    last_ask = last_bid = np.nan
    for k in range(n):
        if ts[k] - last_ask_t <= lookback_s and ts[k] - last_bid_t <= lookback_s:
            out[k] = 0.5 * (last_ask - last_bid)
        if side[k] > 0:
            last_ask, last_ask_t = price[k], ts[k]
        else:
            last_bid, last_bid_t = price[k], ts[k]
    return out


def trade_table(ds, with_spread: bool = True) -> pd.DataFrame:
    """Trades joined to their market: hours before reveal, markout, leg."""
    m = ds.markets.set_index("ticker")
    t = ds.trades.join(m[["event_ticker", "family", "subfamily", "script",
                          "mutually_exclusive", "reveal_ts", "y"]], on="ticker",
                       how="inner").sort_values(["ticker", "ts"], kind="stable")
    t["hours_before"] = (t["reveal_ts"] - t["ts"]) / HOUR
    t["markout"] = t["side"] * (t["y"] - t["price"])
    t["leg"] = leg_of(t["price"].to_numpy(), t["side"].to_numpy())
    if with_spread:
        hs = np.full(len(t), np.nan)
        pos = 0
        for _, g in t.groupby("ticker", sort=False):
            k = len(g)
            hs[pos:pos + k] = effective_half_spread(g["ts"].to_numpy(), g["price"].to_numpy(),
                                                    g["side"].to_numpy())
            pos += k
        t["half_spread"] = hs
    return t.reset_index(drop=True)


def in_window(hours_before: pd.Series, w) -> pd.Series:
    return (hours_before <= w[0]) & (hours_before > w[1])


def markout_table(tt: pd.DataFrame, windows=WINDOWS + (BASELINE,), by=("family",),
                  reps: int = 2000) -> pd.DataFrame:
    """Contract-weighted taker markout (cents), the mean effective
    half-spread, and their sum: what takers earn beyond paying the spread.
    The half-spread estimate leans low when prices trend between prints,
    which makes the net figure conservative."""
    out = []
    for w in windows:
        sub = tt[in_window(tt["hours_before"], w)].copy()
        if sub.empty:
            continue
        sub["cm"] = sub["count"] * sub["markout"]
        for key, g in sub.groupby(list(by), sort=False):
            ev = g.groupby("event_ticker").agg(cm=("cm", "sum"), c=("count", "sum"))
            R, se = ratio_by_cluster(ev["cm"], ev["c"])
            lo, hi = bootstrap_ratio(ev["cm"], ev["c"], reps)
            hs = np.nan
            if "half_spread" in g and g["half_spread"].notna().any():
                hs = float(np.nanmean(g["half_spread"]))
            key = key if isinstance(key, tuple) else (key,)
            out.append((*key, wlabel(w), len(ev), len(g), float(g["count"].sum()),
                        100 * R, 100 * se, 100 * lo, 100 * hi, 100 * hs,
                        100 * (R + hs) if not np.isnan(hs) else np.nan))
    cols = list(by) + ["window", "events", "trades", "contracts", "markout_c", "se_c",
                       "ci_lo_c", "ci_hi_c", "half_spread_c", "net_of_spread_c"]
    return pd.DataFrame(out, columns=cols)


def excess_markout_by_leg(tt: pd.DataFrame, pre=PRE_REVEAL, base=BASELINE,
                          by=("family",)) -> pd.DataFrame:
    """Markout in the pre-reveal window minus the same leg's markout one to two
    weeks out, per contract and in total contracts x cents ('excess P&L').
    Uses only events that traded the leg in both windows."""
    rows = []
    tt = tt.assign(cm=tt["count"] * tt["markout"])
    pre_t = tt[in_window(tt["hours_before"], pre)]
    base_t = tt[in_window(tt["hours_before"], base)]
    keys = list(by) + ["leg"]
    for key, gp in pre_t.groupby(keys, sort=False):
        gb = base_t
        for k, v in zip(keys, key if isinstance(key, tuple) else (key,)):
            gb = gb[gb[k] == v]
        a = gp.groupby("event_ticker").agg(cm=("cm", "sum"), c=("count", "sum"))
        b = gb.groupby("event_ticker").agg(cm=("cm", "sum"), c=("count", "sum"))
        both = a.index.intersection(b.index)
        if len(both) < 2:
            continue
        a, b = a.loc[both], b.loc[both]
        d, se = diff_of_ratios(a["cm"], a["c"], b["cm"], b["c"])
        key = key if isinstance(key, tuple) else (key,)
        rows.append((*key, len(both), float(a["c"].sum()), 100 * d, 100 * se,
                     100 * d * float(a["c"].sum())))
    cols = keys + ["events", "pre_contracts", "excess_markout_c", "se_c", "excess_pnl_c"]
    return pd.DataFrame(rows, columns=cols)
