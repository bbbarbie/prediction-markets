"""Assemble one table of markets, listing-time text and dispute labels.

Inputs are the files ``resolution.pull`` writes (or ``synth.py`` imitates):
``gamma_markets.jsonl``, ``gamma_state.json``, ``resolutions.jsonl``,
``resolutions_q.jsonl`` and, if the chain step ran, ``dispute_logs.jsonl``,
``chain_state.json`` and ``block_anchors.json``.

Labels come from up to three sources and are combined the way
PREREGISTRATION.md fixes: a market counts as disputed if any source says so.

* ``api``: Data API ``was_disputed`` (and ``was_arbitrated``,
  ``new_version_q``) per condition.
* ``chain``: number of UMA ``DisputePrice`` events whose ancillary data hashes
  to the market's question id (or, failing that, whose listed title and rules
  match the market's). A market with no match counts as undisputed on chain
  only where a match was possible: inside the scan's coverage, not a neg-risk
  market (their Gamma question id is not the UMA one) and no requester filter.
* ``gamma``: "disputed" or "challenged" in Gamma's ``umaResolutionStatuses``,
  read only when it holds a history (two or more states).

A label is public once the market has resolved, so ``closed_time`` is the
latest of Gamma's ``closedTime``, the Data API's ``resolved_at`` and the last
on-chain dispute. Markets with none of the three are dropped.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import abi
from . import text as T
from .pull import read_jsonl

DISPUTE_STATES = {"disputed", "challenged"}
TEXT_JOIN_WINDOW_DAYS = 7


def _listish(v) -> list:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        try:
            out = json.loads(s)
            return out if isinstance(out, list) else [out]
        except json.JSONDecodeError:
            return [x.strip().strip('"') for x in s.strip("[]").split(",") if x.strip()]
    return [v]


def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True, errors="coerce", format="mixed")


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip() if isinstance(s, str) else ""


def _api_price(v) -> float:
    """Data API prices: '1', '0.5', '0', or 18-decimal integers; 69 means unset."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return np.nan
    if x == 69:
        return np.nan
    if abs(x) > 1.5:
        x = x / 1e18
    return x if -1e-9 <= x <= 1 + 1e-9 else np.nan


def _state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def load_gamma(data: Path) -> pd.DataFrame:
    rows = list(read_jsonl(data / "gamma_markets.jsonl"))
    if not rows:
        raise SystemExit(f"no markets in {data / 'gamma_markets.jsonl'}; run resolution.pull first")
    df = pd.DataFrame(rows).drop_duplicates("id", keep="last").reset_index(drop=True)
    for col in ("conditionId", "questionID", "resolvedBy"):
        df[col] = df[col].map(lambda v: v.lower() if isinstance(v, str) else None) \
            if col in df else None
    for col in ("createdAt", "startDate", "endDate", "closedTime", "updatedAt"):
        df[col] = _ts(df[col]) if col in df else pd.NaT
    df["created"] = df["createdAt"].fillna(df["startDate"])
    df["end"] = df["endDate"]
    df["volume"] = _num(df["volumeNum"]).fillna(0.0)
    ev = df["events"].apply(lambda e: e[0] if isinstance(e, list) and e else {})
    df["event_id"] = [str(e.get("id")) if e.get("id") is not None else f"m{i}"
                      for e, i in zip(ev, df["id"])]
    df["event_title"] = ev.apply(lambda e: e.get("title"))
    df["neg_risk"] = ev.apply(lambda e: bool(e.get("negRisk")))
    df["series"] = ev.apply(lambda e: (e.get("series") or [None])[0])
    tags = [list(dict.fromkeys([x for x in (t if isinstance(t, list) else []) +
                                (e.get("tags") or []) if isinstance(x, str)]))
            for t, e in zip(df["tags"], ev)]
    df["tag_list"] = tags
    cats = df["category"] if "category" in df else pd.Series(None, index=df.index)
    df["category_name"] = [T.category_of(t, c, q) for t, c, q in
                           zip(tags, cats, df["question"])]
    df["outcome_list"] = df["outcomes"].apply(_listish)
    prices = df["outcomePrices"].apply(_listish)
    df["final_price"] = [float(p[0]) if p and str(p[0]).replace(".", "", 1).isdigit() else np.nan
                         for p in prices]
    snapped = (df["final_price"] * 2).round() / 2
    df["final_price"] = snapped.where((df["final_price"] - snapped).abs() < 0.02)
    df["uma_statuses"] = df["umaResolutionStatuses"].apply(_listish)
    # audit only: the pull keeps markets above the volume floor, so this undercounts
    # an event's markets and is not used as a feature
    df["n_in_event_pulled"] = df.groupby("event_id")["id"].transform("count")
    return df


API_COLUMNS = ["api_found", "api_rows", "api_status", "api_reporter", "api_market_type",
               "api_resolution_source", "api_was_disputed", "api_was_arbitrated",
               "api_new_version_q", "api_price", "api_resolved_at"]
Q_COLUMNS = ["q_proposed_price", "q_reproposed_price", "q_price"]


def load_api(data: Path) -> pd.DataFrame:
    """One row per condition; several Data API rows for a condition are combined.

    Booleans are true if any row says so; text fields take the first row's
    value (the API orders native lifecycle, then UMA, then CTF state).
    """
    rows = list(read_jsonl(data / "resolutions.jsonl"))
    if not rows:
        return pd.DataFrame(columns=API_COLUMNS, index=pd.Index([], name="condition_id"))
    api = pd.DataFrame(rows)
    api["condition_id"] = api["condition_id"].str.lower()
    missing = (api["_missing"].astype("boolean").fillna(False).astype(bool)
               if "_missing" in api else pd.Series(False, index=api.index))
    ids = pd.Index(api["condition_id"].unique(), name="condition_id")
    real = api[~missing]
    g = real.groupby("condition_id", sort=False)
    out = pd.DataFrame(index=ids)
    out["api_found"] = ids.isin(real["condition_id"])
    out["api_rows"] = g.size().reindex(ids).fillna(0).astype(int)
    for col in ("status", "reporter", "market_type", "resolution_source"):
        out[f"api_{col}"] = (g[col].first() if col in real else pd.Series(dtype=object)
                             ).reindex(ids)
    for col in ("was_disputed", "was_arbitrated", "new_version_q"):
        if col in real:
            vals = real[col].map(lambda v: 1.0 if v is True else 0.0 if v is False else np.nan)
            out[f"api_{col}"] = vals.groupby(real["condition_id"]).max().reindex(ids)
        else:
            out[f"api_{col}"] = np.nan
        out[f"api_{col}"] = out[f"api_{col}"].map(
            lambda v: pd.NA if v != v else bool(v)).astype("boolean")
    out["api_price"] = (g["price"].first().apply(_api_price) if "price" in real
                        else pd.Series(dtype=float)).reindex(ids)
    out["api_resolved_at"] = (_ts(real["resolved_at"]).groupby(real["condition_id"]).max()
                              if "resolved_at" in real else pd.Series(dtype="datetime64[ns, UTC]")
                              ).reindex(ids)
    return out


def load_api_questions(data: Path) -> pd.DataFrame:
    rows = [r for r in read_jsonl(data / "resolutions_q.jsonl") if not r.get("_missing")]
    if not rows:
        return pd.DataFrame(columns=Q_COLUMNS, index=pd.Index([], name="question_id"))
    q = pd.DataFrame(rows)
    q["question_id"] = q["_question_id"].str.lower()
    q = q.drop_duplicates("question_id", keep="first").set_index("question_id")
    out = pd.DataFrame(index=q.index)
    for col in ("proposed_price", "reproposed_price", "price"):
        out[f"q_{col}"] = (q[col] if col in q else pd.Series(np.nan, index=q.index)
                           ).apply(_api_price)
    return out


def load_chain(data: Path) -> tuple[pd.DataFrame | None, dict | None]:
    """Decoded dispute logs with approximate times, and what the scan covered."""
    state = _state(data / "chain_state.json")
    anchors = sorted((int(k), v) for k, v in _state(data / "block_anchors.json").items())
    if not state or len(anchors) < 2:
        return None, None
    rows = list(read_jsonl(data / "dispute_logs.jsonl"))
    logs = pd.DataFrame([r for r in rows if not r.get("_undecodable")])
    ab = np.array([a for a, _ in anchors], dtype=float)
    at = np.array([t for _, t in anchors], dtype=float)

    def when(blocks):
        return pd.to_datetime(np.interp(np.asarray(blocks, dtype=float), ab, at), unit="s",
                              utc=True)
    covered_to = state.get("next_block", state.get("to_block", 0)) - 1
    info = {"start": when([state["from_block"]])[0], "end": when([covered_to])[0],
            "requesters": state.get("requesters") or [],
            "undecodable": sum(1 for r in rows if r.get("_undecodable"))}
    if logs.empty:
        return logs, info
    logs = logs.drop_duplicates(["tx", "log_index"])
    t = pd.Series(when(logs["block"]), index=logs.index)
    if "block_timestamp" in logs and logs["block_timestamp"].notna().any():
        exact = pd.to_datetime(logs["block_timestamp"], unit="s", utc=True, errors="coerce")
        t = exact.fillna(t)
    logs["time"] = t
    logs["question_id"] = logs["question_id"].str.lower()
    return logs.sort_values(["block", "log_index"]), info


def chain_by_question(logs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for qid, g in logs.groupby("question_id", sort=False):
        first = g.iloc[0]
        parsed = abi.parse_ancillary(bytes.fromhex(first["ancillary_hex"][2:]))
        p = int(first["proposed_price"])
        rows.append({
            "question_id": qid, "chain_n": len(g), "chain_first_time": first["time"],
            "chain_last_time": g["time"].max(),
            "chain_first_proposed": abi.price_to_outcome(p) if p != abi.TOO_EARLY else np.nan,
            "chain_too_early": bool(g["too_early"].any()),
            "chain_requester": first["requester"],
            "chain_request_ts": pd.to_datetime(first["request_timestamp"], unit="s", utc=True),
            "listing_title": parsed["title"], "listing_description": parsed["description"],
        })
    return pd.DataFrame(rows)


def join_chain(markets: pd.DataFrame, per_q: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Attach chain disputes to markets: by question id, then by listed text.

    The text fallback needs the same normalised title, Gamma's rules starting
    with the listed rules (Gamma may have appended clarifications), and a
    listing time within TEXT_JOIN_WINDOW_DAYS of the oracle request; among
    several candidates the closest in time wins.
    """
    matched = per_q.merge(markets[["questionID"]].reset_index(), left_on="question_id",
                          right_on="questionID", how="inner")
    out = matched.set_index("index")
    out = out[~out.index.duplicated(keep="first")]
    stats = {"chain_questions": len(per_q), "joined_by_question_id": len(out)}
    rest = per_q[~per_q["question_id"].isin(matched["question_id"])]
    extra = []
    if len(rest):
        by_title: dict[str, list] = {}
        for i, k in markets["question"].map(_norm).items():
            if k:
                by_title.setdefault(k, []).append(i)
        desc = markets["description"].map(_norm)
        taken = set(out.index)
        window = TEXT_JOIN_WINDOW_DAYS * 86400
        for _, r in rest.iterrows():
            title, head = _norm(r["listing_title"]), _norm(r["listing_description"])[:200]
            if not title or not head:
                continue
            cands = [i for i in by_title.get(title, []) if i not in taken
                     and desc[i].startswith(head)]
            gaps = [abs((markets.at[i, "created"] - r["chain_request_ts"]).total_seconds())
                    if pd.notna(markets.at[i, "created"]) else np.inf for i in cands]
            ok = [(gap, i) for gap, i in zip(gaps, cands) if gap < window]
            if ok:
                best = min(ok)[1]
                taken.add(best)
                extra.append(pd.Series(r, name=best))
    if extra:
        out = pd.concat([out, pd.DataFrame(extra)])
    stats["joined_by_text"] = len(extra)
    stats["unmatched"] = stats["chain_questions"] - len(out)
    return out.drop(columns=["questionID"], errors="ignore"), stats


def _any_true(*cols: pd.Series) -> pd.Series:
    df = pd.concat([c.astype("boolean") for c in cols], axis=1)
    anyt = df.fillna(False).any(axis=1)
    known = df.notna().any(axis=1)
    return anyt.astype("boolean").where(known, pd.NA)


def assemble(data: Path) -> tuple[pd.DataFrame, dict]:
    """Markets with stripped rules text, labels from every source, and an audit dict."""
    data = Path(data)
    df = load_gamma(data)
    gstate = _state(data / "gamma_state.json")
    audit: dict = {"gamma_markets": len(df), "pulled_at": gstate.get("pulled_at")}
    stripped = df["description"].map(T.strip_post_listing)
    df["rules"] = [s for s, _ in stripped]
    df["post_listing_chars"] = [n for _, n in stripped]

    api = load_api(data)
    df = df.join(api, on="conditionId")
    df["api_found"] = df["api_found"].astype("boolean").fillna(False).astype(bool)
    for col in ("api_was_disputed", "api_was_arbitrated", "api_new_version_q"):
        df[col] = df[col].astype("boolean")
    audit["api_rows"] = int(df["api_found"].sum())
    audit["api_conditions_with_several_rows"] = int((df["api_rows"].fillna(0) > 1).sum())
    df = df.join(load_api_questions(data), on="questionID")

    logs, chain = load_chain(data)
    df["chain_n"] = pd.Series(pd.NA, index=df.index, dtype="Int64")
    chain_cols = ["chain_first_time", "chain_last_time", "chain_first_proposed",
                  "chain_too_early", "chain_requester", "chain_request_ts", "listing_title",
                  "listing_description"]
    if logs is not None:
        audit["chain_logs"] = len(logs)
        audit["chain_undecodable_logs"] = chain["undecodable"]
        audit["chain_coverage"] = [str(chain["start"]), str(chain["end"])]
        audit["chain_requester_filter"] = chain["requesters"]
    if logs is not None and len(logs):
        per_q, jstats = join_chain(df, chain_by_question(logs))
        audit.update(jstats)
        req = logs.drop_duplicates("question_id")["requester"].map(
            lambda a: abi.KNOWN_ADAPTERS.get(a, "other"))
        audit["chain_requesters"] = req.value_counts().to_dict()
        df = df.join(per_q[chain_cols])
        df.loc[per_q.index, "chain_n"] = per_q["chain_n"].astype("Int64")
    else:
        for c in chain_cols:
            df[c] = np.nan
    df["chain_last_time"] = pd.to_datetime(df["chain_last_time"], utc=True, errors="coerce")

    # when the outcome became public
    df["closed_time"] = pd.concat([df["closedTime"], df["api_resolved_at"],
                                   df["chain_last_time"]], axis=1).max(axis=1)
    if logs is not None:
        can_see = ((df["created"] >= chain["start"])
                   & (df["closed_time"] <= chain["end"] - pd.Timedelta(days=1))
                   & ~df["neg_risk"])
        if not chain["requesters"]:
            df.loc[can_see & df["chain_n"].isna(), "chain_n"] = 0

    gamma_known = df["uma_statuses"].map(len) >= 2
    df["gamma_disputed"] = pd.Series(
        [any(str(s).lower() in DISPUTE_STATES for s in st) for st in df["uma_statuses"]],
        index=df.index, dtype="boolean").where(gamma_known, pd.NA)
    df["chain_disputed"] = (df["chain_n"] > 0).astype("boolean")
    df["disputed"] = _any_true(df["api_was_disputed"], df["chain_disputed"], df["gamma_disputed"])
    df["escalated"] = _any_true(df["api_was_arbitrated"],
                                (df["chain_n"] >= 2).astype("boolean"))
    df["rules_updated"] = df["api_new_version_q"].astype("boolean")
    first = df["q_proposed_price"].astype(float).fillna(df["chain_first_proposed"].astype(float))
    final = df["final_price"].fillna(df["api_price"].astype(float))
    df["overturned"] = pd.Series((first != final), dtype="boolean").where(
        df["disputed"].fillna(False).astype(bool) & first.notna() & final.notna(), pd.NA)

    src = pd.DataFrame({"api": df["api_was_disputed"].notna(), "chain": df["chain_n"].notna(),
                        "gamma": df["gamma_disputed"].notna()})
    audit["label_sources"] = {k: int(v) for k, v in src.sum().items()}
    both = df[["api_was_disputed", "chain_disputed", "gamma_disputed"]].dropna()
    if len(both):
        audit["label_agreement_all_three"] = {
            "rows": len(both),
            "crosstab": both.astype(int).astype(str).agg("".join, axis=1).value_counts().to_dict()}
    for a, b in (("api_was_disputed", "chain_disputed"), ("api_was_disputed", "gamma_disputed"),
                 ("chain_disputed", "gamma_disputed")):
        pair = df[[a, b]].dropna()
        if len(pair):
            ct = pd.crosstab(pair[a].astype(bool), pair[b].astype(bool))
            audit[f"crosstab {a} x {b}"] = {f"{i}/{j}": int(ct.loc[i, j]) for i in ct.index
                                            for j in ct.columns}
    df.attrs["pulled_at"] = audit["pulled_at"]
    return df, audit


def population(df: pd.DataFrame, *, min_volume: float, since: str,
               maturity_days: int = 21) -> tuple[pd.Series, dict]:
    """Markets resolved through UMA, closed, mature, traded and with rules text.

    UMA evidence: the Data API says ``UMA_OO``; or, without a Data API row, an
    on-chain dispute, a Gamma resolution-status history, or ``resolvedBy`` a
    known UMA adapter. Being inside the chain scan's range is not evidence.
    Maturity is measured from the pull date (``gamma_state.json``).
    """
    pulled = df.attrs.get("pulled_at")
    data_end = (pd.Timestamp(pulled) if pulled else df["closed_time"].max())
    if data_end.tzinfo is None:
        data_end = data_end.tz_localize("UTC")
    reporter = df.get("api_reporter", pd.Series(None, index=df.index))
    reporter = reporter.map(lambda v: v.upper() if isinstance(v, str) else "")
    no_api = reporter.eq("")
    evidence = ((df["chain_n"].fillna(0) > 0) | (df["uma_statuses"].map(len) >= 2)
                | df["resolvedBy"].isin(list(abi.KNOWN_ADAPTERS)))
    steps = {
        "closed (resolution time known)":
            df["closed"].fillna(True).astype(bool) & df["closed_time"].notna(),
        "resolved through UMA": reporter.eq("UMA_OO") | (no_api & evidence),
        f"volume >= {min_volume:,.0f}": df["volume"] >= min_volume,
        f"listed on or after {since}": df["created"] >= pd.Timestamp(since, tz="UTC"),
        f"resolved {maturity_days}+ days before the pull":
            df["closed_time"] <= data_end - pd.Timedelta(days=maturity_days),
        "has rules text": df["rules"].str.len() > 20,
        "label known": df["disputed"].notna(),
    }
    mask = pd.Series(True, index=df.index)
    counts = {"all markets": int(len(df))}
    for name, m in steps.items():
        mask &= m.fillna(False).astype(bool)
        counts[name] = int(mask.sum())
    return mask, counts


def add_template_history(df: pd.DataFrame, *, label: str = "disputed",
                         strength: float = 5.0) -> pd.DataFrame:
    """As-of dispute rate of the market's template among markets closed before it listed.

    Only markets whose resolution was public before this market listed count,
    so the feature is available at listing time. The rate is shrunk toward the
    overall rate of the earlier markets with ``strength`` pseudo-markets.
    """
    df = df.copy()
    df["template"] = [s if isinstance(s, str) and s else T.template_key(r)
                      for s, r in zip(df.get("series", [None] * len(df)), df["rules"])]
    y = df[label].astype(float)
    hist = pd.DataFrame({"template": df["template"], "t": df["closed_time"], "y": y}).dropna()
    hist = hist.sort_values("t")
    hist["n"] = hist.groupby("template").cumcount() + 1
    hist["k"] = hist.groupby("template")["y"].cumsum()
    glob = hist[["t", "y"]].copy()
    glob["gn"] = np.arange(1, len(glob) + 1)
    glob["gk"] = glob["y"].cumsum()
    q = df[["template", "created"]].reset_index().dropna(subset=["created"]).sort_values("created")
    m = pd.merge_asof(q, hist[["template", "t", "n", "k"]], left_on="created", right_on="t",
                      by="template", allow_exact_matches=False)
    g = pd.merge_asof(q[["index", "created"]], glob[["t", "gn", "gk"]], left_on="created",
                      right_on="t", allow_exact_matches=False)
    m = m.set_index("index")
    g = g.set_index("index")
    n = m["n"].fillna(0)
    k = m["k"].fillna(0)
    base = (g["gk"].fillna(0) + 1) / (g["gn"].fillna(0) + 50)
    df["hist_n"] = np.log1p(n).reindex(df.index).fillna(0.0)
    df["hist_rate"] = ((k + strength * base) / (n + strength)).reindex(df.index)
    df["hist_rate"] = df["hist_rate"].fillna(df["hist_rate"].median())
    return df
