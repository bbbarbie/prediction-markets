"""Synthetic Kalshi-shaped data with planted leaks, to test the tests.

    python3 -m leakage.synth --out demo/synth --leak-rate 0.1 --style mixed

Each event opens 14 days before its reveal R. The outcome is drawn first and
public information arrives as a Brownian signal whose drift depends on it, so
the public price is an exact posterior (a martingale):

  binary   logit P = logit(pi0) + delta * S(tau),  dS = delta (Y - 1/2) dtau + dW
  K-way    P_i  ~  prior_i * exp(delta * S_i(tau)), dS_i = delta (1{i = w} - 1/2) dtau + dW_i

tau(t) is information time. In 'scheduled_reveal' events public information
stops `quiet_hours` before R: the answer is settled and kept quiet. In
'continuous_public' events it keeps arriving and speeds up into the close.

Uninformed takers arrive as Poisson processes that intensify toward the
close, buy YES with probability yes_bias, and push the price a little
(impact that decays). Makers quote the displayed price +/- half_spread, and
displayed prices carry a favourite-longshot bias (log-odds shrunk by `flb`).
In K-way events some uninformed traders sell long shots in baskets that skip
the top one or two names, and some buy complete baskets (arbitrage).

In a share leak_rate of events an insider learns the outcome 2-48 hours before
R and trades until 15 minutes before it: the winning side in binary events;
in K-way events 'yes' (YES on the winner), 'basket' (NO on every other
outcome at once) or 'mixed'. Insider trades move the price toward the answer
and the move stays.
"""
from __future__ import annotations

import argparse
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import data as data_mod

HOUR = 3600


@dataclass
class Spec:
    family: str = "scheduled_reveal"      # or "continuous_public"
    n_events: int = 400
    me_share: float = 0.4                 # share of events with 3-8 outcomes
    leak_rate: float = 0.0
    leak_style: str = "mixed"             # yes | basket | mixed (K-way events)
    days: float = 14.0
    quiet_hours: float = 72.0
    info_scheduled: float = 1.5           # delta^2 x information time, scheduled
    info_continuous: float = 10.0         # same, continuous_public
    trades_per_market: float = 60.0
    yes_bias: float = 0.58
    flb: float = 0.88
    flb_tail: float = 1.0                 # extra log-odds shrink beyond |logit| > 2 (1 = none)
    basket_leg_gap: tuple = (1.0, 5.0)    # seconds between an insider basket's legs
    half_spread: float = 0.015
    kappa_u: float = 0.04
    decay_hours: float = 4.0
    kappa_i: float = 0.30
    insider_arrivals: float = 5.0
    insider_size: float = 150.0           # median contracts per insider trade (noise: 20)
    basket_rate: float = 1.5
    arb_rate: float = 0.5
    seed: int = 0
    start: str = "2026-01-05"
    tag: str = ""


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


_GRID = np.linspace(0.0, 1.0, 2001)
_CDF = (0.3 * _GRID + 0.9 * _GRID ** 3) / 1.2          # intensity 0.3 + 2.7 x^2


def _arrival_fractions(rng, n):
    """Arrival times as fractions of the market's life, denser near the close."""
    return np.interp(rng.random(n), _CDF, _GRID)


def _series(spec: Spec, k: int) -> str:
    if spec.family == "scheduled_reveal":
        return "SYNAWARD" if k > 1 else "SYNATTEND"
    return "SYNRACE" if k > 1 else "SYNGAME"


def simulate_event(rng, spec: Spec, idx: int, reveal: int):
    """Markets, trades and truth for one event."""
    K = 1 if rng.random() >= spec.me_share else int(rng.integers(3, 9))
    life = spec.days * 24 * HOUR
    open_ts = reveal - life
    series = _series(spec, K)
    event = f"{series}-{spec.tag}{spec.seed:02d}E{idx:05d}"
    if K == 1:
        pi0 = float(_sigmoid(rng.normal(-0.6, 1.3)))
        y = int(rng.random() < pi0)
        drift = np.array([y - 0.5])
        prior_logit = np.array([_logit(pi0)])
        winner = 0 if y else -1
        liq = rng.lognormal(0.0, 0.5, 1)
    else:
        prior = rng.dirichlet(np.full(K, 0.7))
        prior = np.clip(prior, 1e-4, None)
        prior /= prior.sum()
        winner = int(rng.choice(K, p=prior))
        drift = np.where(np.arange(K) == winner, 0.5, -0.5)
        prior_logit = np.log(prior)
        liq = rng.lognormal(0.0, 0.5, K) * (0.4 + 2.0 * prior)   # favourites trade more
    scheduled = spec.family == "scheduled_reveal"
    delta = np.sqrt(spec.info_scheduled if scheduled else spec.info_continuous)
    info_end = reveal - spec.quiet_hours * HOUR if scheduled else reveal

    def tau(t):
        x = np.clip((t - open_ts) / (info_end - open_ts), 0.0, 1.0)
        return x if scheduled else x ** 3

    # ---- exogenous schedule: (time, kind, market, side, size, skip) ----
    sched = []
    for i in range(K):
        n = rng.poisson(spec.trades_per_market * liq[i])
        times = open_ts + _arrival_fractions(rng, n) * life
        sides = np.where(rng.random(n) < spec.yes_bias, 1, -1)
        sizes = np.maximum(1, np.round(rng.lognormal(np.log(20), 1.0, n)))
        sched += [(float(t), "u", i, int(s), float(z), 0) for t, s, z in zip(times, sides, sizes)]
    if K > 1:
        for _ in range(rng.poisson(spec.basket_rate)):
            t = open_ts + rng.uniform(0.05, 0.995) * life
            sched.append((float(t), "ub", -1, -1, float(max(1, round(rng.lognormal(np.log(15), 0.7)))),
                          int(rng.integers(1, 3))))
        for _ in range(rng.poisson(spec.arb_rate)):
            t = open_ts + rng.uniform(0.05, 0.995) * life
            sched.append((float(t), "ub", -1, -1, float(max(1, round(rng.lognormal(np.log(15), 0.7)))), 0))
    leaked = rng.random() < spec.leak_rate
    t_leak = np.nan
    if leaked:
        t_leak = reveal - rng.uniform(2.0, 48.0) * HOUR
        n_i = 1 + rng.poisson(max(spec.insider_arrivals - 1, 0))
        for t in np.sort(rng.uniform(t_leak, reveal - 0.25 * HOUR, n_i)):
            size = float(max(1, round(rng.lognormal(np.log(spec.insider_size), 0.7))))
            if K == 1:
                sched.append((float(t), "i", 0, 1 if y else -1, size, 0))
            else:
                style = spec.leak_style if spec.leak_style != "mixed" else \
                    ("yes" if rng.random() < 0.5 else "basket")
                sched.append((float(t), "iy" if style == "yes" else "ib", -1, 0, size, 0))
    sched.sort(key=lambda r: r[0])

    # ---- public posterior at every scheduled time ----
    times = np.array([r[0] for r in sched]) if sched else np.zeros(0)
    taus = tau(times)
    dtau = np.diff(np.concatenate([[0.0], taus]))
    shocks = rng.normal(size=(len(times), K)) * np.sqrt(dtau)[:, None]
    S = np.cumsum(delta * drift[None, :] * dtau[:, None] + shocks, axis=0)
    if K == 1:
        pub = prior_logit[None, :] + delta * S                     # log-odds
    else:
        lw = prior_logit[None, :] + delta * S
        lw -= lw.max(axis=1, keepdims=True)
        post = np.exp(lw)
        post /= post.sum(axis=1, keepdims=True)
        pub = _logit(post)

    # ---- sequential pricing ----
    inf = np.zeros(K)
    noise = np.zeros(K)
    noise_t = np.full(K, open_ts, dtype=float)
    decay = spec.decay_hours * HOUR
    h = spec.half_spread
    trades = []

    def shrink(l):
        """Favourite-longshot bias: log-odds shrunk by flb, and by flb * flb_tail
        beyond |logit| = 2 (a bias a two-parameter recalibration cannot fit)."""
        core = np.clip(l, -2.0, 2.0)
        return spec.flb * (core + spec.flb_tail * (l - core))

    def price(i, t, row):
        n = noise[i] * np.exp(-(t - noise_t[i]) / decay)
        return float(_sigmoid(shrink(pub[row, i] + inf[i] + n)))

    def bump(i, t, amount):
        noise[i] = noise[i] * np.exp(-(t - noise_t[i]) / decay) + amount
        noise_t[i] = t

    def fill(i, t, side, size, p):
        px = float(np.clip(np.round(p + side * h, 2), 0.01, 0.99))
        trades.append((f"{event}-{i}", int(t), px, size, "yes" if side > 0 else "no"))

    for row, (t, kind, i, side, size, skip) in enumerate(sched):
        if kind == "u":
            fill(i, t, side, size, price(i, t, row))
            bump(i, t, spec.kappa_u * side)
        elif kind == "i":
            fill(i, t, side, size, price(i, t, row))
            inf[i] += spec.kappa_i * side
        elif kind == "iy":
            fill(winner, t, 1, size, price(winner, t, row))
            inf[winner] += spec.kappa_i
        else:  # baskets of NO: "ub" uninformed (skip top `skip`), "ib" insider (skip winner)
            ps = np.array([price(j, t, row) for j in range(K)])
            if kind == "ib":
                legs = [j for j in range(K) if j != winner]
            else:
                order = np.argsort(-ps)
                legs = sorted(order[skip:].tolist())
            rng.shuffle(legs)
            gap = spec.basket_leg_gap if kind == "ib" else (1.0, 5.0)
            tj = t
            for n, j in enumerate(legs):
                tj = t if n == 0 else tj + float(rng.uniform(*gap))
                fill(j, tj, -1, size, ps[j])
                if kind == "ib":
                    inf[j] -= spec.kappa_i
                else:
                    bump(j, tj, -spec.kappa_u)

    iso = lambda ts: pd.Timestamp(int(ts), unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    title = "Who will win the award?" if K > 1 else "Will the named person attend?"
    if spec.family != "scheduled_reveal":
        title = "Who will win the race?" if K > 1 else "Will the home team win the game?"
    markets = [{"ticker": f"{event}-{i}", "event_ticker": event, "series_ticker": series,
                "title": title, "yes_sub_title": f"Outcome {i}", "close_time": iso(reveal),
                "result": ("yes" if (i == winner) else "no"), "status": "finalized"}
               for i in range(K)]
    ev = {"event_ticker": event, "series_ticker": series, "title": title,
          "mutually_exclusive": K > 1}
    truth = {"event_ticker": event, "family": spec.family, "outcomes": K,
             "leaked": leaked, "t_leak": t_leak, "style": spec.leak_style if leaked else ""}
    return markets, trades, ev, truth


def generate(specs: list[Spec]):
    """DataFrames (markets, trades, events, truth) for a list of specs."""
    markets, trades, events, truth = [], [], [], []
    for spec in specs:
        rng = np.random.default_rng([spec.seed, zlib.crc32(spec.family.encode()),
                                     int(spec.leak_rate * 1e4)])
        base = int(pd.Timestamp(spec.start, tz="UTC").timestamp())
        for e in range(spec.n_events):
            reveal = base + 30 * 24 * HOUR + e * 6 * HOUR
            m, t, ev, tr = simulate_event(rng, spec, e, reveal)
            markets += m
            trades += t
            events.append(ev)
            truth.append(tr)
    tdf = pd.DataFrame(trades, columns=["ticker", "ts", "yes_price", "count", "taker_side"])
    tdf["created_time"] = pd.to_datetime(tdf["ts"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    tdf["trade_id"] = [f"T{i:08d}" for i in range(len(tdf))]
    tdf = tdf.drop(columns="ts")
    return (pd.DataFrame(markets), tdf, pd.DataFrame(events), pd.DataFrame(truth))


def dataset(specs: list[Spec]):
    """Normalised leakage.data.Dataset plus the truth table."""
    m, t, ev, truth = generate(specs)
    return data_mod.normalise(m, t, ev, source="synthetic"), truth


def default_specs(leak_rate: float = 0.1, style: str = "mixed", n: int = 600, seed: int = 0):
    """Leaky scheduled-reveal events next to clean scheduled and continuous ones."""
    return [Spec(family="scheduled_reveal", n_events=n, leak_rate=leak_rate,
                 leak_style=style, seed=seed, tag="L"),
            Spec(family="scheduled_reveal", n_events=n, leak_rate=0.0, seed=seed + 1, tag="C",
                 start="2026-06-01"),
            Spec(family="continuous_public", n_events=n, leak_rate=0.0, seed=seed + 2, tag="P")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="demo/synth")
    ap.add_argument("--events", type=int, default=600)
    ap.add_argument("--leak-rate", type=float, default=0.1)
    ap.add_argument("--style", default="mixed", choices=["yes", "basket", "mixed"])
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    m, t, ev, truth = generate(default_specs(a.leak_rate, a.style, a.events, a.seed))
    m.to_csv(out / "markets.csv", index=False)
    t.to_csv(out / "trades.csv", index=False)
    ev.to_csv(out / "events.csv", index=False)
    truth.to_csv(out / "truth.csv", index=False)
    print(f"{len(ev)} events, {len(m)} markets, {len(t)} trades -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
