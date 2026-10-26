"""Why the skip test recalibrates prices first.

    python3 -m leakage.recalibration_check --reps 40

Clean samples (no insiders) with a strong favourite-longshot bias whose shape
a two-parameter logistic recalibration cannot fit exactly (log-odds shrunk by
0.75, and by 0.375 beyond |logit| = 2), plus twice the usual number of
uninformed traders who sell long shots in baskets that skip the favourites.
The skip test runs twice on each sample: on raw prices and on cross-fitted
recalibrated prices. With raw prices, favourites win more often than their
prices say, so baskets that skip favourites look informed.
"""
from __future__ import annotations

import argparse
from multiprocessing import Pool

import numpy as np
import pandas as pd

from . import metrics, mirror, synth


def one(seed: int) -> dict:
    ds, _ = synth.dataset([synth.Spec(family="scheduled_reveal", n_events=400, me_share=0.6,
                                      leak_rate=0.0, flb=0.75, flb_tail=0.5,
                                      basket_rate=3.0, seed=seed)])
    tt = metrics.trade_table(ds, with_spread=False)
    calib = mirror.cross_fit_calibration(ds)
    raw = mirror.skip_test(mirror.skip_bursts(ds, tt, None), n_null=2000, seed=seed)
    cal = mirror.skip_test(mirror.skip_bursts(ds, tt, calib), n_null=2000, seed=seed)
    return {"seed": seed, "hit_raw": raw["hit_ratio"], "p_raw": raw["p_value"],
            "hit_recal": cal["hit_ratio"], "p_recal": cal["p_value"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=40)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", default="leakage/results/recalibration_check.csv")
    a = ap.parse_args(argv)
    with Pool(a.workers) as pool:
        df = pd.DataFrame(pool.map(one, [7000 + r for r in range(a.reps)]))
    df.to_csv(a.out, index=False)
    for name in ("raw", "recal"):
        print(f"{name:5s}: mean hit ratio {df[f'hit_{name}'].mean():.3f}, "
              f"false alarms {np.mean(df[f'p_{name}'] < 0.05):.1%} of {len(df)} clean samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
