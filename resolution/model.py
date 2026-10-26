"""Dispute-risk models and the evaluation PREREGISTRATION.md fixes.

Every model is a logistic regression; they differ only in what they see.

=====  ==============================================================
prior  category only
M0     category + market design (horizon, neg-risk, outcome labels, UMA bond
       and reward, custom liveness): everything a listing team knows except
       the words
M1     M0 + phrase-family counts, the linter's flags and text structure
M2     M1 + TF-IDF on the question and rules (1-2 word n-grams)
M3     M2 + the template's dispute history (markets closed before listing)
M0v    M0 + log volume (volume is known only after the fact)
M2v    M2 + log volume
=====  ==============================================================
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

from . import text as T

DENSE = list(T.features("", "").keys())
DESIGN = ["log_horizon_days", "neg_risk", "named_outcomes", "log_uma_bond", "log_uma_reward",
          "custom_liveness"]
HISTORY = ["hist_rate", "hist_n"]


@dataclass(frozen=True)
class Spec:
    category: bool = True
    design: bool = False
    dense: bool = False
    text: bool = False
    history: bool = False
    volume: bool = False
    extra: tuple = ()          # raw (unscaled) columns, e.g. one 0/1 flag


SPECS = {
    "prior": Spec(),
    "M0": Spec(design=True),
    "M1": Spec(design=True, dense=True),
    "M2": Spec(design=True, dense=True, text=True),
    "M3": Spec(design=True, dense=True, text=True, history=True),
    "M0v": Spec(design=True, volume=True),
    "M2v": Spec(design=True, dense=True, text=True, volume=True),
}


def _float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def prepare(df: pd.DataFrame, rules_col: str = "rules") -> pd.DataFrame:
    """Add design, dense text features and the bag-of-words document."""
    df = df.copy()
    horizon = (df["end"] - df["created"]).dt.total_seconds() / 86400
    df["log_horizon_days"] = np.log1p(horizon.clip(lower=0).fillna(0))
    df["neg_risk"] = df["neg_risk"].astype(float)
    df["named_outcomes"] = [0.0 if [str(o).lower() for o in (x or [])] in (["yes", "no"], [])
                            else 1.0 for x in df["outcome_list"]]
    df["log_uma_bond"] = np.log1p(_float(df.get("umaBond", pd.Series(0, index=df.index)))
                                  .clip(lower=0).fillna(0))
    df["log_uma_reward"] = np.log1p(_float(df.get("umaReward", pd.Series(0, index=df.index)))
                                    .clip(lower=0).fillna(0))
    df["custom_liveness"] = (_float(df.get("customLiveness", pd.Series(0, index=df.index)))
                             .fillna(0) > 0).astype(float)
    titles = df["question"].fillna("")
    rules = df[rules_col].fillna("")
    feats = pd.DataFrame([T.features(q, r) for q, r in zip(titles, rules)], index=df.index)
    df[DENSE] = feats[DENSE]
    df["doc"] = [T.doc(q, r) for q, r in zip(titles, rules)]
    df["log_volume"] = np.log10(df["volume"].clip(lower=1))
    return df


class RiskModel:
    def __init__(self, spec: Spec, C: float = 1.0, min_df: int = 5,
                 max_features: int = 60_000):
        self.spec, self.C, self.min_df, self.max_features = spec, C, min_df, max_features

    def _blocks(self, df: pd.DataFrame, fit: bool):
        blocks, names = [], []
        sp = self.spec
        if sp.category:
            cat = pd.Categorical(df["category_name"], categories=T.CATEGORIES)
            blocks.append(sparse.csr_matrix(pd.get_dummies(cat).to_numpy(dtype=float)))
            names += [f"category={c}" for c in T.CATEGORIES]
        for flag, cols, attr in ((sp.design, DESIGN, "_s_design"), (sp.dense, DENSE, "_s_dense"),
                                 (sp.history, HISTORY, "_s_hist"),
                                 (sp.volume, ["log_volume"], "_s_vol")):
            if not flag:
                continue
            x = df[cols].to_numpy(dtype=float)
            x = np.nan_to_num(x)
            if fit:
                setattr(self, attr, StandardScaler().fit(x))
            scaler = getattr(self, attr)
            blocks.append(sparse.csr_matrix(np.clip(scaler.transform(x), -8, 8)))
            names += cols
        if sp.extra:
            blocks.append(sparse.csr_matrix(df[list(sp.extra)].to_numpy(dtype=float)))
            names += list(sp.extra)
        if sp.text:
            if fit:
                self._tfidf = TfidfVectorizer(ngram_range=(1, 2), min_df=self.min_df, max_df=0.6,
                                              sublinear_tf=True, max_features=self.max_features,
                                              dtype=np.float32)
                self._tfidf.fit(df["doc"])
            blocks.append(self._tfidf.transform(df["doc"]))
            names += [f'"{w}"' for w in self._tfidf.get_feature_names_out()]
        return sparse.hstack(blocks).tocsr(), names

    def fit(self, df: pd.DataFrame, y) -> "RiskModel":
        x, self.names = self._blocks(df, fit=True)
        self.lr = LogisticRegression(C=self.C, max_iter=5000)
        self.lr.fit(x, np.asarray(y, dtype=int))
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        x, _ = self._blocks(df, fit=False)
        return self.lr.predict_proba(x)[:, 1]

    def contributions(self, df: pd.DataFrame, top: int = 8) -> list[list[tuple[str, float, float]]]:
        """Largest positive terms of the linear score, per row: (feature, coef * x, x).

        Dense features are standardized, so x < 0 means "less than the average
        training market" (e.g. no definition clause where most markets have one).
        """
        x, _ = self._blocks(df, fit=False)
        coef = self.lr.coef_[0]
        out = []
        for i in range(x.shape[0]):
            row = x.getrow(i)
            vals = row.data * coef[row.indices]
            order = np.argsort(-vals)[:top]
            out.append([(self.names[row.indices[j]], float(vals[j]), float(row.data[j]))
                        for j in order if vals[j] > 0])
        return out

    def top_terms(self, k: int = 20, prefix: str | None = None) -> pd.DataFrame:
        coef = pd.Series(self.lr.coef_[0], index=self.names)
        if prefix is not None:
            coef = coef[[n.startswith(prefix) for n in coef.index]]
        return pd.DataFrame({"highest": coef.nlargest(k).index, "coef_hi": coef.nlargest(k).values,
                             "lowest": coef.nsmallest(k).index,
                             "coef_lo": coef.nsmallest(k).values})


def tune_C(train: pd.DataFrame, y: np.ndarray, spec: Spec, grid=(0.1, 0.3, 1.0, 3.0),
           min_df: int = 5) -> tuple[float, dict]:
    """Pick C on the last fifth of the training period (by listing time)."""
    cut = train["created"].quantile(0.8)
    fit_mask = (train["closed_time"] < cut).to_numpy()
    val_mask = (train["created"] >= cut).to_numpy()
    if y[val_mask].sum() < 5 or y[fit_mask].sum() < 5:
        return 1.0, {}
    scores = {}
    for C in grid:
        m = RiskModel(spec, C=C, min_df=min_df).fit(train[fit_mask], y[fit_mask])
        scores[C] = average_precision_score(y[val_mask], m.predict(train[val_mask]))
    return max(scores, key=scores.get), scores


# ------------------------------------------------------------------- evaluation

def _order(s: np.ndarray) -> np.ndarray:
    jitter = np.random.default_rng(12345).random(len(s)) * 1e-12
    return np.argsort(-(s + jitter), kind="stable")


def recall_at(y, s, w=None, frac: float = 0.05, value=None) -> float:
    """Share of positives (or of their ``value``) inside the top ``frac`` of scores."""
    y = np.asarray(y, dtype=float)
    w = np.ones_like(y) if w is None else np.asarray(w, dtype=float)
    v = np.ones_like(y) if value is None else np.asarray(value, dtype=float)
    o = _order(np.asarray(s, dtype=float))
    cw = np.cumsum(w[o])
    top = cw <= frac * cw[-1]
    pos = (w * y * v)[o]
    total = pos.sum()
    return float(pos[top].sum() / total) if total > 0 else np.nan


def ap(y, s, w=None) -> float:
    """Average precision with ties broken by the same fixed jitter for every model.

    Without it, a model whose inputs tie many markets (neg-risk siblings share
    every M0 input) is scored at the end of each tied block, while a model that
    breaks the ties on noise is not.
    """
    y = np.asarray(y, dtype=int)
    if y.sum() == 0 or (w is not None and (np.asarray(w) * y).sum() == 0):
        return np.nan
    s = np.asarray(s, dtype=float)
    s = s + np.random.default_rng(12345).random(len(s)) * 1e-12
    return float(average_precision_score(y, s, sample_weight=w))


def auc(y, s, w=None) -> float:
    y = np.asarray(y, dtype=int)
    if len(np.unique(y)) < 2:
        return np.nan
    return float(roc_auc_score(y, s, sample_weight=w))


def metrics(y, s, volume, frac: float = 0.05) -> dict:
    y = np.asarray(y, dtype=int)
    r = recall_at(y, s, frac=frac)
    return {"markets": len(y), "disputed": int(y.sum()), "rate": float(y.mean()),
            "ROC-AUC": auc(y, s), "PR-AUC": ap(y, s), f"recall@{frac:.0%}": r,
            f"volume recall@{frac:.0%}": recall_at(y, s, frac=frac, value=volume),
            f"lift@{frac:.0%}": r / frac if r == r else np.nan}


def paired_bootstrap(y, a, b, clusters, stat, n_boot: int = 1000, seed: int = 0) -> dict:
    """Cluster bootstrap of stat(a) - stat(b); one-sided p for 'a beats b'."""
    y = np.asarray(y)
    codes, uniq = pd.factorize(np.asarray(clusters))
    k = len(uniq)
    rng = np.random.default_rng(seed)
    point = stat(y, a, None) - stat(y, b, None)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        w = np.bincount(rng.integers(0, k, k), minlength=k)[codes].astype(float)
        diffs[i] = stat(y, a, w) - stat(y, b, w)
    diffs = diffs[~np.isnan(diffs)]
    return {"diff": float(point), "lo": float(np.quantile(diffs, 0.025)),
            "hi": float(np.quantile(diffs, 0.975)),
            "p_one_sided": float((np.sum(diffs <= 0) + 1) / (len(diffs) + 1)),
            "n_boot": int(len(diffs))}


def by_quintile(y, scores: dict, volume) -> pd.DataFrame:
    q = pd.qcut(pd.Series(volume).rank(method="first"), 5, labels=False)
    rows = []
    for k in range(5):
        m = (q == k).to_numpy()
        row = {"volume quintile": k + 1, "markets": int(m.sum()),
               "min volume": float(np.min(np.asarray(volume)[m])),
               "disputed": int(np.asarray(y)[m].sum())}
        for name, s in scores.items():
            row[f"{name} AUC"] = auc(np.asarray(y)[m], np.asarray(s)[m])
        rows.append(row)
    return pd.DataFrame(rows)


def calibration(y, s, bins: int = 10) -> pd.DataFrame:
    q = pd.qcut(pd.Series(s).rank(method="first"), bins, labels=False)
    return pd.DataFrame({"decile": q + 1, "predicted": s, "observed": np.asarray(y, float)}) \
        .groupby("decile").agg(markets=("observed", "size"), predicted=("predicted", "mean"),
                               observed=("observed", "mean")).reset_index()


def time_split(df: pd.DataFrame, split: str) -> tuple[np.ndarray, np.ndarray]:
    """Train: closed before the split. Test: listed on or after it.

    Markets listed before the split and closed after it are in neither set,
    so no test market's outcome is known when the model is trained and every
    test market lists after the model exists.
    """
    t = pd.Timestamp(split, tz="UTC")
    train = (df["closed_time"] < t).to_numpy()
    test = (df["created"] >= t).to_numpy()
    return train, test


def shuffle_text_within(df: pd.DataFrame, by: list[str], seed: int = 0) -> pd.DataFrame:
    """Placebo: give each market the question and rules of another market in its stratum."""
    rng = np.random.default_rng(seed)
    df = df.copy()
    for _, idx in df.groupby(by).groups.items():
        idx = np.asarray(list(idx))
        perm = rng.permutation(idx)
        df.loc[idx, ["question", "rules"]] = df.loc[perm, ["question", "rules"]].to_numpy()
    return df
