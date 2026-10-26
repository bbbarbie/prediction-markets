"""How often does the H1 test fire? Fresh synthetic samples per scenario.

    python3 -m resolution.power --reps 100 --out resolution/results

Each replication generates a new synthetic sample (``synth.py``), runs it
through the same assembly, population filter, time split and models as the
real run (M0 and M2, C fixed at 0.3 to save time) and applies the H1 test
(PR-AUC of M2 minus M0, event-cluster bootstrap, one-sided 5%).

Scenarios:

* no word effect: disputes depend on category, volume and an event effect only.
* planted word effect: open clauses raise the odds of a dispute.
* leaked clarifications: no word effect, but 60% of disputed markets get an
  "Update (date): ..." paragraph after the fact. Run twice on the same samples:
  with the post-listing text stripped (as the real run does) and without.
"""
from __future__ import annotations

import argparse
import tempfile
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from . import data as D
from . import model as M
from . import plots, synth

SCENARIOS = {
    "none": dict(text_effect=0.0, canary=0.0),
    "words": dict(text_effect=0.6, canary=0.0),
    "leak": dict(text_effect=0.0, canary=0.6),
}


def one(args) -> list[dict]:
    scenario, rep, n_events, n_boot = args
    spec = synth.Spec(n_events=n_events, seed=10_000 + rep, **SCENARIOS[scenario])
    with tempfile.TemporaryDirectory() as tmp:
        synth.generate(spec, Path(tmp))
        df, _ = D.assemble(Path(tmp))
    mask, _ = D.population(df, min_volume=10_000, since="2024-01-01")
    pop = df[mask]
    out = []
    for stripped in ((True, False) if scenario == "leak" else (True,)):
        p = M.prepare(pop, rules_col="rules" if stripped else "description")
        tr, te = M.time_split(p, "2026-04-01")
        y_tr = p[tr]["disputed"].astype(int).to_numpy()
        y_te = p[te]["disputed"].astype(int).to_numpy()
        s = {}
        for name in ("M0", "M2"):
            m = M.RiskModel(M.SPECS[name], C=0.3, min_df=3).fit(p[tr], y_tr)
            s[name] = m.predict(p[te])
        h = M.paired_bootstrap(y_te, s["M2"], s["M0"], p[te]["event_id"].to_numpy(),
                               lambda yy, sc, w: M.ap(yy, sc, w), n_boot=n_boot, seed=rep)
        out.append({"scenario": scenario, "stripped": stripped, "rep": rep,
                    "test_markets": len(y_te), "test_disputed": int(y_te.sum()),
                    "diff": h["diff"], "p": h["p_one_sided"],
                    "fires": bool(h["p_one_sided"] < 0.05)})
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=100)
    ap.add_argument("--n-events", type=int, default=3000)
    ap.add_argument("--n-boot", type=int, default=300)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", type=Path, default=Path("resolution/results"))
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--tag", default="", help="suffix for the output files, e.g. _large")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    scenarios = [s for s in args.scenarios.split(",") if s]
    jobs = [(sc, r, args.n_events, args.n_boot) for sc in scenarios for r in range(args.reps)]
    with Pool(args.workers) as pool:
        rows = [row for chunk in pool.imap_unordered(one, jobs) for row in chunk]
    runs = pd.DataFrame(rows).sort_values(["scenario", "stripped", "rep"])
    runs.to_csv(args.out / f"power_runs{args.tag}.csv", index=False)
    summary = runs.groupby(["scenario", "stripped"]).agg(
        samples=("fires", "size"), fires=("fires", "mean"), mean_diff=("diff", "mean"),
        test_markets=("test_markets", "mean"), test_disputed=("test_disputed", "mean")
    ).reset_index()
    summary["fires"] *= 100
    summary.to_csv(args.out / f"power{args.tag}.csv", index=False)
    print(summary.round(3).to_string(index=False))
    if set(scenarios) != set(SCENARIOS):
        return
    get = summary.set_index(["scenario", "stripped"])["fires"]
    labels = ["No word effect", "Planted word effect", "Clarifications leak\nthe label"]
    plots.power_chart(
        args.out / "power.png", labels,
        {"Post-listing text stripped (as run)": [get[("none", True)], get[("words", True)],
                                                 get[("leak", True)]],
         "Not stripped": [np.nan, np.nan, get[("leak", False)]]},
        f"How often H1 fires: {args.reps} fresh samples per scenario, "
        f"~{summary['test_markets'].mean():.0f} test markets each")


if __name__ == "__main__":
    main()
