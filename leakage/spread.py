"""From leaked information to the spread market makers must charge.

Glosten-Milgrom with insiders who know the outcome. A share mu of arriving
takers knows Y and buys the side that wins; the rest buy YES with probability
b (b > 1/2: uninformed flow leans YES). A competitive maker who breaks even
quotes the posterior given the trade:

    ask = P(Y=1 | taker buys YES) = q(mu + (1-mu) b) / (q(mu + (1-mu) b) + (1-q)(1-mu) b)
    bid = P(Y=1 | taker buys NO)  = q(1-mu)(1-b) / (q(1-mu)(1-b) + (1-q)(mu + (1-mu)(1-b)))

At q = 50c and b = 1/2 the half-spread is exactly mu/2: every 1% of order flow
that already knows the answer costs half a cent of half-spread.

Measured version. Net-of-spread taker markout N = markout + effective
half-spread is what takers earn beyond paying the spread. Uninformed takers
make N < 0 (they also pay any behavioural premium); informed takers make
N > 0. The rise in N from one to two weeks out to the day before the reveal
is the extra half-spread makers need in that day just to break even on what
leaked, before risk and fees. implied_mu() maps it back to an insider share.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import optimize


def gm_quotes(q: float, mu: float, b: float = 0.5) -> tuple[float, float]:
    """Break-even bid and ask (YES price) with insider share mu."""
    buy1, buy0 = mu + (1 - mu) * b, (1 - mu) * b              # P(YES taker | Y)
    sell1, sell0 = (1 - mu) * (1 - b), mu + (1 - mu) * (1 - b)  # P(NO taker | Y)
    ask = q * buy1 / (q * buy1 + (1 - q) * buy0)
    bid = q * sell1 / (q * sell1 + (1 - q) * sell0)
    return bid, ask


def gm_half_spread(q: float, mu: float, b: float = 0.5) -> float:
    bid, ask = gm_quotes(q, mu, b)
    return 0.5 * (ask - bid)


def implied_mu(extra_half_spread: float, q: float = 0.5, b: float = 0.5) -> float:
    """Insider share whose GM half-spread exceeds the mu = 0 one by the given amount."""
    if extra_half_spread <= 0:
        return 0.0
    base = gm_half_spread(q, 0.0, b)
    f = lambda mu: gm_half_spread(q, mu, b) - base - extra_half_spread
    if f(0.999) < 0:
        return float("nan")
    return float(optimize.brentq(f, 0.0, 0.999))


def leakage_tax(markouts: pd.DataFrame, pre: str = "24h-1h", base: str = "14d-7d",
                by=("family",), q: float = 0.5) -> pd.DataFrame:
    """Rise in net-of-spread taker markout from the baseline window to the
    pre-reveal window, in cents, with the GM insider share it implies."""
    p = markouts[markouts["window"] == pre].set_index(list(by))
    b = markouts[markouts["window"] == base].set_index(list(by))
    both = p.index.intersection(b.index)
    out = pd.DataFrame({
        "net_pre_c": p.loc[both, "net_of_spread_c"],
        "net_base_c": b.loc[both, "net_of_spread_c"],
    })
    out["tax_c"] = out["net_pre_c"] - out["net_base_c"]
    out["implied_insider_share"] = [implied_mu(max(t, 0) / 100, q) if pd.notna(t) else np.nan
                                    for t in out["tax_c"]]
    return out.reset_index()


if __name__ == "__main__":
    print("Glosten-Milgrom half-spread (cents) with insiders who know the outcome")
    print("  insider share   q=10c   q=30c   q=50c   (b = 0.5)")
    for mu in (0.005, 0.01, 0.02, 0.05, 0.10):
        cells = "  ".join(f"{100 * gm_half_spread(q, mu):6.2f}" for q in (0.1, 0.3, 0.5))
        print(f"  {mu:12.1%}  {cells}")
    print("\nSame at q=50c with YES-optimistic noise (b = 0.6):")
    for mu in (0.01, 0.05):
        bid, ask = gm_quotes(0.5, mu, 0.6)
        print(f"  mu={mu:.0%}: bid {100 * bid:.2f}c  ask {100 * ask:.2f}c  "
              f"half-spread {100 * 0.5 * (ask - bid):.2f}c")
