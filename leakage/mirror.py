"""The mirror trade, and two tests for informed flow in anonymous trades.

In an event with N mutually exclusive outcomes priced p_1..p_N (sum about 1),
someone who knows the winner w can buy one YES on w: cost p_w, profit 1 - p_w.
Or one NO on every other outcome: cost sum_{i != w} (1 - p_i) = N - 2 + p_w,
payout N - 1, profit 1 - p_w. Same profit. Each NO leg costs 1 - p_i, a
favourite's price when i is a long shot, so a rule that flags large bets on
long shots ("$2,500 within an hour on an outcome priced at 35% or less") sees
the first trade and none of the legs of the second.

Skip test. Group an event's NO-taker trades into bursts (consecutive trades
less than gap_s apart) covering at least min_legs (default 2) outcomes. A burst that buys
NO on some outcomes and skips others says "the winner is among the skipped".
If burst composition carries no information beyond prices, the skipped set
wins with probability q_b, its share of recalibrated, renormalised prices.
U = sum_b (Z_b - q_b), with Z_b = 1{winner skipped}, then has mean zero; its
null distribution is simulated by redrawing each event's winner from prices,
which keeps the dependence between bursts of one event. Complete baskets
(nothing skipped) are arbitrage and carry no signal.

Long-shot test. Each market's largest YES bet at <= 35c, if it is large
(top 5% of trade sizes): Z = market settled YES, q = the recalibrated mid.
This is the trade that public screens for insider bets look for.

Recalibration matters: favourites win more often than their prices say
(favourite-longshot bias), and an uninformed trader who sells long shots
skips favourites. Prices are recalibrated per family with a logistic fit,
cross-fitted so no event's own outcome enters its calibration.
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from .metrics import HOUR, LONGSHOT, PRE_REVEAL, in_window, price_before

EPS = 1e-4


def logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, float)))


def fit_logistic(p, y, iters: int = 50, ridge: float = 1e-3) -> tuple[float, float]:
    """Y ~ sigmoid(a + b logit(p)) by Newton's method; identity if degenerate."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    ok = ~np.isnan(p)
    p, y = p[ok], y[ok]
    if len(p) < 30 or y.min() == y.max():
        return 0.0, 1.0
    X = np.column_stack([np.ones(len(p)), logit(p)])
    beta = np.array([0.0, 1.0])
    for _ in range(iters):
        mu = sigmoid(X @ beta)
        W = mu * (1 - mu)
        H = X.T @ (X * W[:, None]) + ridge * np.eye(2)
        step = np.linalg.solve(H, X.T @ (y - mu) - ridge * (beta - [0.0, 1.0]))
        beta = beta + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return float(beta[0]), float(beta[1])


def mirror_profits(prices, winner: int) -> tuple[float, float]:
    """Profit of one YES on the winner vs one NO on every other outcome.
    Equal when prices sum to 1; with an overround (sum > 1) the basket earns
    the YES profit plus the overround: sum_{i != w} p_i = (sum p - 1) + (1 - p_w)."""
    p = np.asarray(prices, float)
    yes = 1.0 - p[winner]
    others = np.delete(p, winner)
    basket = len(others) - np.sum(1.0 - others)
    return float(yes), float(basket)


def fold_of(event: str, k: int) -> int:
    return zlib.crc32(event.encode()) % k


def cross_fit_calibration(ds, anchor_hours: float = 24.0, folds: int = 5) -> dict:
    """event_ticker -> (a, b), fitted per family on other folds' markets using
    each market's last price before reveal - anchor_hours."""
    paths = ds.paths()
    rows = []
    for m in ds.markets.itertuples(index=False):
        if m.ticker in paths:
            ts, price, _, _ = paths[m.ticker]
            p = price_before(ts, price, m.reveal_ts - anchor_hours * HOUR)[0]
            rows.append((m.event_ticker, m.family, fold_of(m.event_ticker, folds), p, m.y))
    df = pd.DataFrame(rows, columns=["event_ticker", "family", "fold", "p", "y"])
    out = {}
    for family, g in df.groupby("family"):
        for f in range(folds):
            a, b = fit_logistic(g.loc[g["fold"] != f, "p"], g.loc[g["fold"] != f, "y"])
            for e in g.loc[g["fold"] == f, "event_ticker"].unique():
                out[e] = (a, b)
    return out


def calibrate(p, ab) -> np.ndarray:
    a, b = ab if ab is not None else (0.0, 1.0)
    return sigmoid(a + b * logit(p))


def bursts_of(ts: np.ndarray, gap_s: float) -> list[np.ndarray]:
    """Split time-sorted indices wherever consecutive trades are > gap_s apart."""
    if len(ts) == 0:
        return []
    cuts = np.flatnonzero(np.diff(ts) > gap_s) + 1
    return np.split(np.arange(len(ts)), cuts)


def skip_bursts(ds, tt: pd.DataFrame, calib: dict | None, window=PRE_REVEAL,
                gap_s: float = 60.0, min_legs: int = 2) -> dict:
    """event -> {'family', 'tickers', 'pi', 'k', 'Q', 'z', 'q', 'n'} for the
    skip test. pi: winner draw probabilities at the first burst; k: how often
    each ticker was skipped; Q: sum of q_b; z: observed sum of Z_b."""
    paths = ds.paths()
    mk = ds.markets.set_index("ticker")
    me = tt[tt["mutually_exclusive"] & (tt["side"] < 0)
            & in_window(tt["hours_before"], window)]
    events = {}
    for event, g in me.groupby("event_ticker", sort=False):
        tickers = mk.index[mk["event_ticker"] == event].to_numpy()
        winners = tickers[mk.loc[tickers, "y"].to_numpy() == 1]
        if len(tickers) < 3 or len(winners) != 1:
            continue
        winner = winners[0]
        close = mk.loc[tickers, "close_ts"].to_numpy()
        ab = calib.get(event) if calib else None
        g = g.sort_values("ts", kind="stable")
        ts = g["ts"].to_numpy()
        rec = None
        for idx in bursts_of(ts, gap_s):
            covered = set(g["ticker"].to_numpy()[idx])
            if len(covered) < min_legs:
                continue
            t0 = ts[idx[0]]
            prices = np.array([price_before(*paths[x][:2], t0)[0] if x in paths else np.nan
                               for x in tickers])
            open_ = ~np.isnan(prices) & (close > t0)
            if not open_[tickers == winner][0]:
                continue
            skipped = open_ & ~np.isin(tickers, list(covered))
            if not skipped.any():
                continue                       # complete basket: arbitrage
            c = np.where(open_, calibrate(np.nan_to_num(prices, nan=0.5), ab), 0.0)
            c = c / c.sum()
            q = float(c[skipped].sum())
            if rec is None:
                rec = {"family": g["family"].iloc[0], "tickers": tickers, "pi": c,
                       "k": np.zeros(len(tickers)), "Q": 0.0, "z": 0.0, "n": 0}
            rec["k"] += skipped
            rec["Q"] += q
            rec["z"] += float(skipped[tickers == winner][0])
            rec["n"] += 1
        if rec is not None:
            events[event] = rec
    return events


def skip_test(events: dict, n_null: int = 5000, seed: int = 11) -> dict:
    """Observed U, its simulated null, and the hit ratio sum Z / sum q."""
    if not events:
        return {"events": 0, "bursts": 0}
    rng = np.random.default_rng(seed)
    U = sum(e["z"] - e["Q"] for e in events.values())
    null = np.zeros(n_null)
    per_event = []
    for name, e in events.items():
        w = rng.choice(len(e["pi"]), size=n_null, p=e["pi"])
        null += e["k"][w] - e["Q"]
        per_event.append((name, e["family"], e["n"], e["z"], e["Q"]))
    z_sum = sum(e["z"] for e in events.values())
    q_sum = sum(e["Q"] for e in events.values())
    u_e = np.array([e["z"] - e["Q"] for e in events.values()])
    return {
        "events": len(events), "bursts": int(sum(e["n"] for e in events.values())),
        "skipped_won": z_sum, "expected": q_sum,
        "hit_ratio": z_sum / q_sum if q_sum > 0 else np.nan,
        "U": U, "z": float(U / np.sqrt(np.sum(u_e ** 2))) if np.any(u_e) else 0.0,
        "p_value": float((1 + np.sum(null >= U - 1e-12)) / (1 + n_null)),
        "per_event": pd.DataFrame(per_event, columns=["event_ticker", "family",
                                                      "bursts", "skipped_won", "expected"]),
    }


def longshot_obs(tt: pd.DataFrame, calib: dict | None, window=PRE_REVEAL,
                 size_quantile: float = 0.95, min_size: float | None = None) -> pd.DataFrame:
    """One row per market: its largest YES-taker trade at <= 35c in the window,
    if that trade is large (in the top 5% of trade sizes by default).
    q is the recalibrated mid: trade price less the mean effective
    half-spread of the trade's family."""
    if min_size is None:
        min_size = float(np.quantile(tt["count"], size_quantile)) if len(tt) else 1.0
    sel = tt[(tt["side"] > 0) & (tt["price"] <= LONGSHOT) & (tt["count"] >= min_size)
             & in_window(tt["hours_before"], window)]
    if sel.empty:
        return pd.DataFrame(columns=["ticker", "event_ticker", "y", "q"])
    big = sel.sort_values(["count", "ts"], ascending=[False, True]) \
             .groupby("ticker", sort=False).first().reset_index()
    if "half_spread" in tt:
        fam_hs = tt.groupby("family")["half_spread"].mean()
        hs = big["family"].map(fam_hs).fillna(0.0).clip(lower=0.0)
    else:
        hs = 0.0
    mid = np.clip(big["price"] - hs, 0.005, 1.0)
    q = [float(calibrate(p, calib.get(e) if calib else None))
         for p, e in zip(mid, big["event_ticker"])]
    return pd.DataFrame({"ticker": big["ticker"], "event_ticker": big["event_ticker"],
                         "y": big["y"].astype(float), "q": q})


def longshot_test(tt: pd.DataFrame, calib: dict | None, window=PRE_REVEAL,
                  size_quantile: float = 0.95, n_null: int = 5000, seed: int = 12,
                  obs: pd.DataFrame | None = None) -> dict:
    """Large YES bets on long shots: do they win more than prices say?
    The null draws each market's outcome from its q."""
    obs = longshot_obs(tt, calib, window, size_quantile) if obs is None else obs
    if obs.empty:
        return {"markets": 0, "p_value": 1.0}
    q, y = obs["q"].to_numpy(float), obs["y"].to_numpy(float)
    rng = np.random.default_rng(seed)
    null = (rng.random((n_null, len(q))) < q).sum(axis=1) - q.sum()
    U = float(y.sum() - q.sum())
    ev = obs.assign(u=y - q).groupby("event_ticker")["u"].sum().to_numpy()
    return {"markets": len(obs), "events": int(obs["event_ticker"].nunique()),
            "won": float(y.sum()), "expected": float(q.sum()),
            "hit_ratio": float(y.sum() / q.sum()) if q.sum() > 0 else np.nan,
            "U": U, "z": float(U / np.sqrt(np.sum(ev ** 2))) if np.any(ev) else 0.0,
            "p_value": float((1 + np.sum(null >= U - 1e-12)) / (1 + n_null))}
