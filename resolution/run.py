"""Run the dispute-risk study and write a report.

    python3 -m resolution.run --data data/pm --out resolution/report
    python3 -m resolution.run --synthetic --out resolution/demo_report

Reads what ``resolution.pull`` wrote, builds the population and labels the
pre-registration fixes, fits the models in ``model.py`` on markets closed
before ``--split`` and scores markets listed on or after it. Writes
``REPORT.md``, ``metrics.json``, ``top_risk.csv``, ``gains.png`` and
``model.pkl`` (for ``resolution.lint --model``).
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import data as D
from . import model as M
from . import plots, synth
from . import text as T

H3_C = 100.0  # nearly unpenalised: a strong penalty would pull rare flags' odds ratios to 1
H3_FLAGS = ["flag_consensus_undefined", "flag_event_vs_announcement", "flag_undefined_term",
            "flag_no_source"]
CASES = {
    "Iran peace deal": (r"\biran", r"peace|deal|agreement|cease-?fire|truce"),
    "Strategy bitcoin sale": (r"microstrategy|\bstrategy\b|\bmstr\b|saylor", r"\bsell|\bsale|\bsold"),
}


def prereg_link(out: Path) -> str:
    """Relative link from the report folder to PREREGISTRATION.md (repo root or package)."""
    here = Path(__file__).resolve().parent
    target = next((p for p in (here.parent / "PREREGISTRATION.md", here / "PREREGISTRATION.md")
                   if p.exists()), here.parent / "PREREGISTRATION.md")
    return os.path.relpath(target, Path(out).resolve()).replace(os.sep, "/")


def md_table(df: pd.DataFrame, floatfmt: str = ".3f") -> str:
    def fmt(v, is_int):
        if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
            return ""
        if isinstance(v, (bool, np.bool_)):
            return "yes" if v else "no"
        if is_int or (isinstance(v, (int, np.integer))):
            return f"{int(v):,}" if abs(int(v)) >= 10_000 else str(int(v))
        if isinstance(v, (float, np.floating)):
            return format(v, floatfmt)
        return str(v).replace("|", "/").replace("\n", " ")
    cols = list(df.columns)
    ints = {c: pd.api.types.is_integer_dtype(df[c]) or (
        pd.api.types.is_float_dtype(df[c]) and df[c].dropna().size > 0
        and bool((df[c].dropna() % 1 == 0).all()) and df[c].dropna().abs().max() >= 1)
        for c in cols}
    pcols = {c for c in cols if str(c) in ("p", "Holm p") or str(c).startswith("p (")}
    lines = ["| " + " | ".join(map(str, cols)) + " |",
             "|" + "|".join("---:" if pd.api.types.is_numeric_dtype(df[c]) else "---"
                            for c in cols) + "|"]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(
            "<0.001" if c in pcols and isinstance(v, (float, np.floating)) and 0 <= v < 0.001
            else fmt(v, ints[c]) for c, v in zip(cols, row)) + " |")
    return "\n".join(lines)


def _pct(x: float) -> str:
    return "" if x != x else f"{100 * x:.1f}%"


def fit_models(train: pd.DataFrame, test: pd.DataFrame, y_tr: np.ndarray, names, *,
               min_df: int, tune: bool = True, C: dict | None = None, log=print) -> dict:
    out = {}
    for name in names:
        spec = M.SPECS[name]
        if C and name in C:
            C_, grid = C[name], {}
        elif spec.text and tune:
            C_, grid = M.tune_C(train, y_tr, spec, min_df=min_df)
        else:
            C_, grid = 1.0, {}
        m = M.RiskModel(spec, C=C_, min_df=min_df).fit(train, y_tr)
        out[name] = {"model": m, "C": C_, "grid": grid, "test": m.predict(test)}
        log(f"  {name}: C={C_}")
    return out


def h_test(y, a, b, clusters, n_boot, seed, frac=0.05) -> dict:
    return {"PR-AUC": M.paired_bootstrap(y, a, b, clusters, lambda yy, s, w: M.ap(yy, s, w),
                                         n_boot=n_boot, seed=seed),
            f"recall@{frac:.0%}": M.paired_bootstrap(
                y, a, b, clusters, lambda yy, s, w: M.recall_at(yy, s, w, frac=frac),
                n_boot=n_boot, seed=seed + 1)}


def flag_effects(train: pd.DataFrame, y: np.ndarray, flags: list[str], n_boot: int,
                 seed: int) -> pd.DataFrame:
    """Each pre-registered flag added alone to M0: odds ratio, event-cluster bootstrap CI.

    One flag at a time, because the phrase counts in M1 overlap the flags and
    would split their weight between them.
    """
    codes, uniq = pd.factorize(train["event_id"].to_numpy())
    order = np.argsort(codes, kind="stable")
    members = np.split(order, np.cumsum(np.bincount(codes, minlength=len(uniq)))[:-1])
    rng = np.random.default_rng(seed)
    picks = [np.concatenate([members[c] for c in rng.integers(0, len(uniq), len(uniq))])
             for _ in range(n_boot)]
    rows = []
    for f in flags:
        spec = M.Spec(design=True, extra=(f,))
        point = M.RiskModel(spec, C=H3_C).fit(train, y).lr.coef_[0][-1]
        draws = []
        for r in picks:
            if y[r].sum() < 3 or train[f].to_numpy()[r].std() == 0:
                continue
            draws.append(M.RiskModel(spec, C=H3_C).fit(train.iloc[r], y[r]).lr.coef_[0][-1])
        d = np.array(draws) if draws else np.array([np.nan])
        se = float(np.nanstd(d, ddof=1)) if len(d) > 2 else np.nan
        rows.append({"flag": f.removeprefix("flag_"), "share flagged": float(train[f].mean()),
                     "odds ratio": float(np.exp(point)),
                     "95% CI low": float(np.exp(np.nanquantile(d, 0.025))),
                     "95% CI high": float(np.exp(np.nanquantile(d, 0.975))),
                     # normal approximation with the bootstrap standard error, so the
                     # p-value is not floored at 1/(draws + 1)
                     "p (one-sided)": float(norm.sf(point / se)) if se > 0 else np.nan})
    out = pd.DataFrame(rows)
    # Holm adjustment across the four flags
    order_p = np.argsort(out["p (one-sided)"].to_numpy())
    adj, running = np.empty(len(out)), 0.0
    for rank, i in enumerate(order_p):
        running = max(running, min(1.0, (len(out) - rank) * out["p (one-sided)"].iloc[i]))
        adj[i] = running
    out["Holm p"] = adj
    return out


def flag_rates(df: pd.DataFrame, y: np.ndarray) -> pd.DataFrame:
    rows = []
    for f in [c for c in M.DENSE if c.startswith("flag_")]:
        on = df[f].to_numpy() > 0
        rows.append({"flag": f.removeprefix("flag_"), "share flagged": on.mean(),
                     "dispute rate if flagged": y[on].mean() if on.any() else np.nan,
                     "if not": y[~on].mean() if (~on).any() else np.nan})
    out = pd.DataFrame(rows)
    out["ratio"] = out["dispute rate if flagged"] / out["if not"]
    return out


def event_level(test: pd.DataFrame, y: np.ndarray, scores: dict) -> dict:
    g = pd.DataFrame({"event": test["event_id"].to_numpy(), "y": y,
                      **{k: v for k, v in scores.items()}}).groupby("event").max()
    return {k: M.ap(g["y"].to_numpy(), g[k].to_numpy()) for k in scores} | \
        {"events": len(g), "disputed events": int(g["y"].sum())}


def run(data_dir: Path, out: Path, *, split: str, min_volume: float, since: str,
        n_boot: int, min_df: int, seed: int, synthetic_note: str | None = None,
        log=print) -> dict:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    df, audit = D.assemble(data_dir)
    mask, funnel = D.population(df, min_volume=min_volume, since=since)
    pop = D.add_template_history(df[mask])
    pop["quarter"] = pop["created"].dt.tz_convert(None).dt.to_period("Q").astype(str)
    pop = M.prepare(pop)
    tr, te = M.time_split(pop, split)
    train, test = pop[tr].copy(), pop[te].copy()
    y_tr = train["disputed"].astype(int).to_numpy()
    y_te = test["disputed"].astype(int).to_numpy()
    log(f"population {len(pop)}; train {len(train)} ({y_tr.sum()} disputed); "
        f"test {len(test)} ({y_te.sum()} disputed)")
    if y_tr.sum() < 10 or y_te.sum() < 5:
        raise SystemExit("too few disputed markets to fit and test; widen --since or lower "
                         "--min-volume")
    res: dict = {"audit": audit, "funnel": funnel, "split": split,
                 "n_train": len(train), "n_test": len(test),
                 "disputed_train": int(y_tr.sum()), "disputed_test": int(y_te.sum())}

    log("fitting models")
    fits = fit_models(train, test, y_tr, list(M.SPECS), min_df=min_df, log=log)
    scores = {k: v["test"] for k, v in fits.items()}
    table = pd.DataFrame([{"model": k, **M.metrics(y_te, s, test["volume"])}
                          for k, s in scores.items()])
    res["metrics"] = table.to_dict("records")
    res["C"] = {k: v["C"] for k, v in fits.items()}

    log("bootstrap tests")
    clusters = test["event_id"].to_numpy()
    res["H1"] = h_test(y_te, scores["M2"], scores["M0"], clusters, n_boot, seed)
    res["H2"] = h_test(y_te, scores["M2v"], scores["M0v"], clusters, n_boot, seed + 10)
    res["M3_vs_M2"] = h_test(y_te, scores["M3"], scores["M2"], clusters, n_boot, seed + 20)
    quint = M.by_quintile(y_te, {"M0": scores["M0"], "M2": scores["M2"]}, test["volume"])
    seen = test["template"].isin(set(train["template"])).to_numpy()
    templates = pd.DataFrame([{"test markets": label, "markets": int(m.sum()),
                               "disputed": int(y_te[m].sum()),
                               "M0 PR-AUC": M.ap(y_te[m], scores["M0"][m]),
                               "M2 PR-AUC": M.ap(y_te[m], scores["M2"][m]),
                               "M3 PR-AUC": M.ap(y_te[m], scores["M3"][m])}
                              for label, m in (("template seen in training", seen),
                                               ("new template", ~seen))])

    log("H3: flag coefficients")
    coefs = flag_effects(train, y_tr, H3_FLAGS, n_boot=max(50, n_boot // 5), seed=seed + 30)
    rates = flag_rates(test, y_te)
    m1, m2 = fits["M1"]["model"], fits["M2"]["model"]
    top_dense = m1.top_terms(12)
    top_words = m2.top_terms(15, prefix='"')

    log("checks: placebo, unstripped text, robustness")
    placebo = M.prepare(M.shuffle_text_within(pop, ["category_name", "quarter"], seed=seed))
    tuned = {"M2": fits["M2"]["C"]}
    p_fit = fit_models(placebo[tr], placebo[te], y_tr, ["M2"], min_df=min_df, C=tuned,
                       log=lambda *_: None)
    raw = M.prepare(pop, rules_col="description")
    r_fit = fit_models(raw[tr], raw[te], y_tr, ["M2"], min_df=min_df, C=tuned,
                       log=lambda *_: None)
    checks = pd.DataFrame([
        {"check": "M2 as fitted", "PR-AUC": M.ap(y_te, scores["M2"]),
         "what it should show": "the main result"},
        {"check": "M0 (no words)", "PR-AUC": M.ap(y_te, scores["M0"]),
         "what it should show": "the bar M2 must clear"},
        {"check": "placebo: each market gets another market's text (same category, quarter)",
         "PR-AUC": M.ap(y_te, p_fit["M2"]["test"]),
         "what it should show": "about M0: the words carry the signal, not the mix"},
        {"check": "unstripped: Gamma's current rules, clarifications included",
         "PR-AUC": M.ap(y_te, r_fit["M2"]["test"]),
         "what it should show": "above M2 if post-listing text leaks the label"},
    ])
    robust = []
    sub = {
        "rules never updated after listing": ~test["rules_updated"].fillna(False).astype(bool),
        "volume >= $100k": test["volume"] >= 100_000,
        "labels: API was_disputed only": test["api_was_disputed"].notna(),
        "labels: on-chain disputes only": test["chain_n"].notna(),
        "labels: Gamma statuses only": test["gamma_disputed"].notna(),
    }
    lab = {"labels: API was_disputed only": "api_was_disputed",
           "labels: on-chain disputes only": "chain_disputed",
           "labels: Gamma statuses only": "gamma_disputed"}
    for name, m in sub.items():
        m = m.to_numpy()
        yy = test[lab[name]].astype(float).to_numpy()[m].astype(int) if name in lab else y_te[m]
        if m.sum() < 50 or yy.sum() < 3:
            robust.append({"subset": name, "markets": int(m.sum()), "disputed": int(yy.sum())})
            continue
        hb = M.paired_bootstrap(yy, scores["M2"][m], scores["M0"][m], clusters[m],
                                lambda a, s, w: M.ap(a, s, w), n_boot=max(100, n_boot // 3),
                                seed=seed + 40)
        robust.append({"subset": name, "markets": int(m.sum()), "disputed": int(yy.sum()),
                       "M0 PR-AUC": M.ap(yy, scores["M0"][m]),
                       "M2 PR-AUC": M.ap(yy, scores["M2"][m]),
                       "diff": hb["diff"], "p": hb["p_one_sided"]})
    ev = event_level(test, y_te, {"M0": scores["M0"], "M2": scores["M2"]})
    robust.append({"subset": "event level (any market disputed; max score)",
                   "markets": ev["events"], "disputed": ev["disputed events"],
                   "M0 PR-AUC": ev["M0"], "M2 PR-AUC": ev["M2"], "diff": ev["M2"] - ev["M0"]})
    robust = pd.DataFrame(robust)

    log("secondary outcomes")
    secondary = []
    for label in ("escalated", "rules_updated"):
        ytr = train[label].astype(float).fillna(0).astype(int).to_numpy()
        yte = test[label].astype(float).fillna(0).astype(int).to_numpy()
        if ytr.sum() < 10 or yte.sum() < 3:
            secondary.append({"outcome": label, "markets": len(yte),
                              "positives": int(yte.sum())})
            continue
        f2 = fit_models(train, test, ytr, ["M0", "M2"], min_df=min_df, C=tuned,
                        log=lambda *_: None)
        secondary.append({"outcome": label, "markets": len(yte), "positives": int(yte.sum()),
                          "rate": yte.mean(), "M0 PR-AUC": M.ap(yte, f2["M0"]["test"]),
                          "M2 PR-AUC": M.ap(yte, f2["M2"]["test"])})
    disp = pop[pop["overturned"].notna()]
    secondary.append({"outcome": "overturned: first proposal lost (disputed markets, all years)",
                      "markets": len(disp),
                      "positives": int(disp["overturned"].astype(bool).sum()),
                      "rate": float(disp["overturned"].astype(float).mean())
                      if len(disp) else np.nan})
    secondary = pd.DataFrame(secondary)

    log("case studies and top-risk list")
    bundle = {"model": m2, "ref_scores": np.sort(scores["M2"]),
              "meta": {"name": "M2", "split": split, "train_rate": float(y_tr.mean()),
                       "reference": f"{len(test):,} markets listed on or after {split}",
                       "median_bond": float(np.nan_to_num(pd.to_numeric(
                           train.get("umaBond"), errors="coerce").median())),
                       "median_reward": float(np.nan_to_num(pd.to_numeric(
                           train.get("umaReward"), errors="coerce").median())),
                       **{f"median_{c}": float(train[c].median()) for c in M.HISTORY}}}
    with (out / "model.pkl").open("wb") as f:
        pickle.dump(bundle, f)
    cases = []
    for name, (a, b) in CASES.items():
        hit = pop[pop["question"].str.contains(a, case=False, regex=True)
                  & pop["question"].str.contains(b, case=False, regex=True)]
        hit = hit.sort_values("volume", ascending=False).head(6)
        if len(hit):
            s = m2.predict(hit)
            for (_, r), si in zip(hit.iterrows(), s):
                cases.append({"case": name, "market": r["question"][:90],
                              "listed": str(r["created"].date()), "volume": r["volume"],
                              "disputed": bool(r["disputed"]), "risk": si,
                              "percentile": 100 * (bundle["ref_scores"] <= si).mean(),
                              "in training set": bool(r["closed_time"] < pd.Timestamp(split,
                                                                                       tz="UTC")),
                              "flags": ", ".join(k.removeprefix("flag_") for k in M.DENSE
                                                 if k.startswith("flag_") and r[k] > 0)})
    cases = pd.DataFrame(cases)
    top = test.assign(risk=scores["M2"]).sort_values("risk", ascending=False).head(25)
    top_tbl = pd.DataFrame({
        "market": top["question"].str.slice(0, 80), "category": top["category_name"],
        "listed": top["created"].dt.date.astype(str), "volume": top["volume"].round(0),
        "risk": top["risk"], "disputed": top["disputed"].astype(bool),
        "flags": [", ".join(k.removeprefix("flag_") for k in M.DENSE
                            if k.startswith("flag_") and r[k] > 0) for _, r in top.iterrows()]})
    top_tbl.to_csv(out / "top_risk.csv", index=False)
    calib = M.calibration(y_te, scores["M2"])
    plots.gains_chart(out / "gains.png", y_te,
                      {"M2: words + category + design": scores["M2"],
                       "M0: category + design": scores["M0"]},
                      "Disputed test markets caught when the riskiest listings are flagged")

    by_cat = pop.assign(set=np.where(tr, "train", np.where(te, "test", "gap"))).groupby(
        ["category_name", "set"])["disputed"].agg(["size", "mean"]).unstack("set")
    by_cat.columns = [f"{b} {'markets' if a == 'size' else 'rate'}" for a, b in by_cat.columns]
    by_cat = by_cat[[c for c in ("train markets", "train rate", "test markets", "test rate",
                                 "gap markets", "gap rate") if c in by_cat.columns]]
    by_cat = by_cat.reset_index().rename(columns={"category_name": "category"})
    stripped = pd.DataFrame([{"markets": lbl, "count": int(m.sum()),
                              "with post-listing text removed": int((pop.loc[m, "post_listing_chars"]
                                                                     > 0).sum())}
                             for lbl, m in (("disputed", pop["disputed"].astype(bool)),
                                            ("not disputed", ~pop["disputed"].astype(bool)))])
    listing_cmp, listing_diff = None, pd.DataFrame()
    if pop["listing_description"].notna().any():
        has = pop[pop["listing_description"].notna()]
        same_raw = [D._norm(a) == D._norm(b) for a, b in zip(has["description"],
                                                            has["listing_description"])]
        same_stripped = [D._norm(a) == D._norm(b) for a, b in zip(has["rules"],
                                                                 has["listing_description"])]
        listing_cmp = {"markets with on-chain listing text": len(has),
                       "Gamma rules identical to listing text": int(np.sum(same_raw)),
                       "identical after stripping post-listing text": int(np.sum(same_stripped))}
        diff_rows = []
        for (_, r), ok in zip(has.iterrows(), same_stripped):
            if ok:
                continue
            a, b = D._norm(r["rules"]), D._norm(r["listing_description"])
            k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            diff_rows.append({"market": str(r["question"])[:70],
                              "stripped Gamma rules, from first difference": a[k:k + 90],
                              "on-chain listing text, from first difference": b[k:k + 90]})
        listing_diff = pd.DataFrame(diff_rows[:10])

    res.update({"quintiles": quint.to_dict("records"), "templates": templates.to_dict("records"),
                "H3": coefs.to_dict("records"), "checks": checks.to_dict("records"),
                "robustness": robust.to_dict("records"),
                "secondary": secondary.to_dict("records"), "listing_text": listing_cmp,
                "runtime_s": round(time.time() - t0, 1)})
    (out / "metrics.json").write_text(json.dumps(res, indent=1, default=str))

    # ------------------------------------------------------------------ report
    h1, h2 = res["H1"], res["H2"]

    def verdict(h):
        return "supported" if h["p_one_sided"] < 0.05 else "not supported"

    def line(h, key):
        return (f"{key} {h[key]['diff']:+.3f} (two-sided 95% CI {h[key]['lo']:+.3f} to "
                f"{h[key]['hi']:+.3f}; one-sided p = {h[key]['p_one_sided']:.3f})")
    pt = table.copy()
    pt["rate"] = pt["rate"].map(_pct)
    for c in ("recall@5%", "volume recall@5%"):
        pt[c] = pt[c].map(_pct)
    pt["lift@5%"] = pt["lift@5%"].map(lambda v: f"{v:.1f}x")
    rep = [f"# Which market rules end up disputed? Report", ""]
    if synthetic_note:
        rep += [f"> **Synthetic data.** {synthetic_note}", ""]
    rep += [f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC from `{data_dir}`. "
            f"Train: markets resolved before {split}. Test: markets listed on or after {split}. "
            f"Population and tests as in [PREREGISTRATION.md]({prereg_link(out)}).", "",
            "## Data", "",
            md_table(pd.DataFrame({"step": list(funnel), "markets": list(funnel.values())})), "",
            f"Train {len(train):,} markets ({y_tr.sum()} disputed, {_pct(y_tr.mean())}); "
            f"test {len(test):,} ({y_te.sum()} disputed, {_pct(y_te.mean())}).", "",
            "Label sources (markets with a value) and how they agree:", "",
            "```", json.dumps({k: v for k, v in audit.items() if k.startswith(("label", "crosstab",
                                                                             "chain_", "joined",
                                                                             "unmatched", "api_"))},
                              indent=1, default=str), "```", "",
            md_table(by_cat, ".3f"), "",
            "Post-listing text removed before modelling (clarification and update paragraphs):",
            "", md_table(stripped), ""]
    if listing_cmp:
        rep += ["Where the on-chain listing text exists (disputed markets):", "",
                md_table(pd.DataFrame({"": list(listing_cmp), "markets":
                                       list(listing_cmp.values())})), ""]
        if len(listing_diff):
            rep += ["Stripped rules that still differ from the listing text (first 10; "
                    "edits or clarification formats the stripper misses):", "",
                    md_table(listing_diff), ""]
    rep += ["## Do the words predict disputes?", "",
            md_table(pt.drop(columns=["markets", "disputed"]), ".3f"), "",
            f"**H1** (M2 beats M0; words add to category and market design): "
            f"{line(h1, 'PR-AUC')}; {line(h1, 'recall@5%')}. **{verdict(h1['PR-AUC'])}**.", "",
            f"**H2** (words add beyond realized volume, M2v vs M0v): {line(h2, 'PR-AUC')}. "
            f"**{verdict(h2['PR-AUC'])}**.", "",
            f"Template history (M3 vs M2): {line(res['M3_vs_M2'], 'PR-AUC')}.", "",
            "![gains](gains.png)", "",
            "Within volume quintiles (ROC-AUC; disputes rise with volume, so this checks the "
            "words are not a proxy for size):", "", md_table(quint), "",
            "Seen vs. new templates (a template is a series, or the rules with numbers, dates "
            "and quoted names masked):", "", md_table(templates), "",
            "## Which open questions matter (H3)", "",
            "Each pre-registered flag added alone to M0 (odds ratio of dispute when the flag is "
            "on, holding category and market design fixed; nearly unpenalised logistic "
            f"regression, C = {H3_C:g}; event-cluster bootstrap on the training set; one-sided "
            "p from the bootstrap standard error, Holm-adjusted across the four):", "",
            md_table(coefs), "",
            "Dispute rate with and without each flag, test set:", "", md_table(rates), "",
            "Largest M1 coefficients:", "", md_table(top_dense), "",
            "Words and pairs with the largest M2 weights:", "", md_table(top_words), "",
            "## Checks", "", md_table(checks), "", "Robustness (M2 vs M0 PR-AUC):", "",
            md_table(robust), "", "Calibration of M2 by test-score decile:", "",
            md_table(calib, ".4f"), "", "## Secondary outcomes", "", md_table(secondary), ""]
    rep += ["## Case studies", ""]
    rep += [md_table(cases) if len(cases) else "No market in the population matched the case "
            "patterns (`CASES` in run.py).", ""]
    rep += ["## Highest-risk test markets (M2)", "", md_table(top_tbl.head(20)), "",
            f"Full list: `top_risk.csv`. Model for the linter: `model.pkl` "
            f"(`python3 -m resolution.lint --model {out}/model.pkl --examples`).", "",
            f"Runtime {res['runtime_s']} s."]
    (out / "REPORT.md").write_text("\n".join(rep))
    log(f"wrote {out / 'REPORT.md'} in {time.time() - t0:.0f} s")
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Dispute-risk study.")
    ap.add_argument("--data", type=Path, default=Path("data/pm"))
    ap.add_argument("--out", type=Path, default=Path("resolution/report"))
    ap.add_argument("--split", default="2026-04-01")
    ap.add_argument("--min-volume", type=float, default=10_000)
    ap.add_argument("--since", default="2024-01-01")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--min-df", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--synthetic", action="store_true",
                    help="generate planted-signal data first (see synth.py) and run on it")
    ap.add_argument("--synthetic-dir", type=Path, default=Path("data/synthetic"))
    args = ap.parse_args(argv)
    note = None
    data_dir = args.data
    if args.synthetic:
        spec = synth.Spec(n_events=5000, seed=args.seed, text_effect=0.9, canary=0.5)
        summary = synth.generate(spec, args.synthetic_dir)
        data_dir = args.synthetic_dir
        note = (f"{summary['markets']:,} generated markets with planted dispute drivers "
                f"(open clauses raise dispute odds, closing clauses lower them; "
                f"text effect {spec.text_effect}) and clarifications appended after the fact, in "
                f"six shapes, to {spec.canary:.0%} of disputed markets. These numbers validate "
                "the pipeline; they say nothing about Polymarket.")
    run(data_dir, args.out, split=args.split, min_volume=args.min_volume, since=args.since,
        n_boot=args.n_boot, min_df=args.min_df, seed=args.seed, synthetic_note=note)


if __name__ == "__main__":
    main()
