"""Offline tests for the calibration study (no network).

Fixtures in tests/fixtures/ are trimmed copies of real responses fetched on
2026-10-24 from the public Kalshi and Polymarket endpoints.
"""
import json
import math
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")   # the repository's root requirements omit pandas

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import analyze as A  # noqa: E402
import parsers as P  # noqa: E402

FX = HERE / "fixtures"


def load(name):
    return json.loads((FX / name).read_text())


# ----------------------------------------------------------------------------
# logistic recalibration
# ----------------------------------------------------------------------------
def synthetic(alpha, beta, n, seed):
    rng = np.random.default_rng(seed)
    price = rng.uniform(0.02, 0.98, n)
    q = A.expit(alpha + beta * A.logit(price))
    y = (rng.uniform(size=n) < q).astype(float)
    return price, y


@pytest.mark.parametrize("alpha,beta", [(0.0, 1.0), (-0.3, 1.25), (0.4, 0.7)])
def test_irls_recovers_known_parameters(alpha, beta):
    price, y = synthetic(alpha, beta, 200_000, seed=1)
    a, b = A.irls_logistic(A.logit(price), y)
    assert a == pytest.approx(alpha, abs=0.03)
    assert b == pytest.approx(beta, abs=0.03)


def test_irls_matches_closed_form_score_equations():
    price, y = synthetic(-0.2, 1.1, 5_000, seed=2)
    x = A.logit(price)
    a, b = A.irls_logistic(x, y)
    mu = A.expit(a + b * x)
    # maximum-likelihood solution: score is zero
    assert abs(np.sum(y - mu)) < 1e-6
    assert abs(np.sum((y - mu) * x)) < 1e-6


def test_integer_weights_equal_row_duplication_and_batch_fits():
    price, y = synthetic(0.1, 1.3, 3_000, seed=3)
    x = A.logit(price)
    w = np.random.default_rng(4).integers(0, 4, size=x.size).astype(float)
    a_w, b_w = A.irls_logistic(x, y, w)
    rep = np.repeat(np.arange(x.size), w.astype(int))
    a_d, b_d = A.irls_logistic(x[rep], y[rep])
    assert a_w == pytest.approx(a_d, abs=1e-8)
    assert b_w == pytest.approx(b_d, abs=1e-8)
    # a (B, n) weight matrix solves B independent fits at once
    W = np.vstack([np.ones_like(w), w])
    aa, bb = A.irls_logistic(x, y, W)
    a1, b1 = A.irls_logistic(x, y)
    assert aa[0] == pytest.approx(a1, abs=1e-8) and bb[1] == pytest.approx(b_w, abs=1e-8)


# ----------------------------------------------------------------------------
# cluster bootstrap
# ----------------------------------------------------------------------------
def test_cluster_bootstrap_weights_are_shared_within_events():
    events = np.array(["e1", "e1", "e1", "e2", "e3", "e3", "e4"])
    W = A.cluster_bootstrap_weights(events, 500, np.random.default_rng(0))
    assert W.shape == (500, events.size)
    for e in np.unique(events):
        cols = W[:, events == e]
        assert np.all(cols == cols[:, :1])          # one weight per event
    # each replicate draws exactly n_events events
    n_ev = np.unique(events).size
    per_event = np.stack([W[:, np.flatnonzero(events == e)[0]] for e in np.unique(events)], 1)
    assert np.all(per_event.sum(1) == n_ev)
    assert set(np.unique(W)) <= set(range(n_ev + 1))


def test_resample_events_keeps_events_whole():
    events = np.array(["a", "a", "b", "c", "c", "c"])
    rng = np.random.default_rng(5)
    for _ in range(50):
        idx = A.resample_events(events, rng)
        drawn = events[idx]
        for e in np.unique(drawn):
            # an event's markets appear the same number of times each
            counts = np.bincount(idx[drawn == e], minlength=events.size)[events == e]
            assert len(set(counts)) == 1
        assert np.unique(events[idx]).size <= 3


def test_cluster_bootstrap_does_not_shrink_with_duplicated_markets():
    """Copying every market k times inside its event adds no information; the
    event bootstrap interval must stay about as wide, unlike an iid one."""
    price, y = synthetic(0.0, 1.0, 600, seed=6)
    ev = np.array([f"e{i}" for i in range(price.size)])
    base = A.fit_with_ci(price, y, ev, n_boot=300, seed=1)
    k = 4
    price4, y4, ev4 = np.repeat(price, k), np.repeat(y, k), np.repeat(ev, k)
    clus = A.fit_with_ci(price4, y4, ev4, n_boot=300, seed=1)
    iid = A.fit_with_ci(price4, y4, np.arange(price4.size).astype(str), n_boot=300, seed=1)
    width = lambda f: f["beta_ci"][1] - f["beta_ci"][0]
    assert clus["beta"] == pytest.approx(base["beta"], abs=1e-8)
    assert width(clus) == pytest.approx(width(base), rel=0.25)
    assert width(iid) < 0.7 * width(clus)


# ----------------------------------------------------------------------------
# price at horizon and staleness
# ----------------------------------------------------------------------------
def test_price_at_uses_last_observation_at_or_before_horizon():
    s = [(1000.0, 0.30), (2000.0, 0.40), (3000.0, 0.90)]
    assert P.price_at(s, 2000.0)[:2] == (0.40, 0.0)          # exactly at the horizon
    p, stale, status = P.price_at(s, 2999.0)
    assert (p, stale, status) == (0.40, 999.0, "ok")          # never looks ahead
    p, stale, status = P.price_at(s, 999.0)
    assert math.isnan(p) and status == "none"


def test_price_at_drops_stale_observations():
    s = [(0.0, 0.25)]
    p, stale, status = P.price_at(s, P.DAY)                   # exactly 24 h old: kept
    assert (p, status) == (0.25, "ok")
    p, stale, status = P.price_at(s, P.DAY + 1)               # older than 24 h: dropped
    assert math.isnan(p) and status == "stale" and stale == P.DAY + 1
    p, _, status = P.price_at(s, 3 * P.HOUR, max_staleness=2 * P.HOUR)
    assert math.isnan(p) and status == "stale"


def test_kalshi_candles_keep_only_periods_with_a_trade():
    body = load("kalshi_batch_candles.json")
    candles = body["markets"][0]["candlesticks"]
    series = P.kalshi_trade_series(candles)
    # the fixture has five hourly candles and only the last one had a trade
    assert len(candles) == 5
    assert series == [(1792821600.0, 0.01)]
    # a horizon inside that trade's hour must not see it (candle ends later)
    p, _, status = P.price_at(series, 1792821600.0 - 60)
    assert status == "none"
    p, stale, status = P.price_at(series, 1792821600.0 + 1800)
    assert (p, stale, status) == (0.01, 1800.0, "ok")
    # a market with no candles at all
    assert P.kalshi_trade_series(body["markets"][1]["candlesticks"]) == []


def test_kalshi_mid_series_requires_two_sided_quotes():
    candles = load("kalshi_batch_candles.json")["markets"][0]["candlesticks"]
    mids = P.kalshi_mid_series(candles)
    for t, m in mids:
        assert 0 < m < 1
    # first candle has bid 0.04 / ask 0.74 -> mid 0.39
    assert mids[0] == (1792562400.0, pytest.approx(0.39))


def test_polymarket_history_parser_sorts_and_reads_points():
    hist = load("polymarket_prices_history.json")["history"]
    s = P.poly_series(list(reversed(hist)))
    assert [t for t, _ in s] == sorted(t for t, _ in s)
    assert s[0] == (1788901229.0, 0.455) and s[-1] == (1789588814.0, 0.0005)


# ----------------------------------------------------------------------------
# parsers on real payload shapes
# ----------------------------------------------------------------------------
def test_to_ts_handles_both_venues_formats():
    assert P.to_ts("2026-10-24T06:14:23Z") == P.to_ts("2026-10-24 06:14:23+00")
    assert P.to_ts("2026-10-24T06:54:20.20361Z") == pytest.approx(P.to_ts("2026-10-24T06:54:20Z") + 0.20361)
    assert P.to_ts("2026-09-16 20:02:43+00") == 1789588963.0
    assert P.to_ts(None) is None and P.to_ts("") is None


def test_parse_kalshi_market_fixture():
    m = load("kalshi_markets_settled.json")["markets"][0]
    r = P.parse_kalshi_market(m, {"KXEFOOTBALLGAME": "Sports"})
    assert r["market_id"] == "KXEFOOTBALLGAME-26OCT240158PABLJOSH-PABL"
    assert r["event_id"] == "KXEFOOTBALLGAME-26OCT240158PABLJOSH"
    assert r["series"] == "KXEFOOTBALLGAME" and r["category"] == "sports"
    assert r["outcome"] == 1 and r["status"] == "finalized" and r["market_type"] == "binary"
    assert r["volume"] == pytest.approx(1712.12)
    assert r["close_ts"] == P.to_ts("2026-10-24T06:14:23Z")
    assert r["is_mve"] is False


def test_parse_kalshi_mve_market_is_flagged():
    r = P.parse_kalshi_market(load("kalshi_market_mve.json"))
    assert r["is_mve"] is True


def test_parse_polymarket_event_fixture():
    ev = load("polymarket_events_keyset.json")["events"][0]
    rows = [P.parse_poly_market(m, event=ev) for m in ev["markets"]]
    btts, btts_1h, ou = rows
    assert btts["is_yes_no"] and btts["resolved"] and btts["outcome"] == 0
    assert btts["event_id"] == "941147" and btts["series"] == "efl-championship"
    assert btts["category"] == "sports"
    assert btts["yes_token"] == json.loads(ev["markets"][0]["clobTokenIds"])[0]
    # reference = earliest of closedTime, endDate, gameStartTime (kick-off here)
    assert btts["ref_ts"] == P.to_ts("2026-09-13T11:00:00Z")
    assert btts["ref_source"] in ("end", "game_start")
    assert btts["closed_ts"] == P.to_ts("2026-09-13 14:58:58+00")
    # Over/Under markets are binary but not YES/NO: excluded
    assert ou["is_yes_no"] is False and ou["outcome"] is None and ou["yes_token"] is None


def test_parse_polymarket_markets_endpoint_shape():
    m = load("polymarket_markets.json")[0]
    r = P.parse_poly_market(m)          # event taken from m["events"][0]
    assert r["event_id"] == "481717"
    assert r["outcome"] == 0 and r["resolved"]
    assert r["category"] == "economics"
    # endDate (00:00) precedes closedTime (20:02, after the FOMC decision)
    assert r["ref_source"] == "end" and r["ref_ts"] == P.to_ts("2026-09-16T00:00:00Z")


def test_unresolved_or_partial_polymarket_prices_are_not_outcomes():
    m = dict(load("polymarket_markets.json")[0])
    m["outcomePrices"] = json.dumps(["0.9995", "0.0005"])
    r = P.parse_poly_market(m)
    assert r["outcome"] is None and not r["resolved"]
    m["outcomePrices"] = json.dumps(["1", "0"])
    m["umaResolutionStatus"] = "proposed"
    r = P.parse_poly_market(m)
    assert r["outcome"] == 1 and not r["resolved"]


# ----------------------------------------------------------------------------
# filters, sampling, scores
# ----------------------------------------------------------------------------
def test_filter_cascade_counts_add_up():
    m = load("kalshi_markets_settled.json")["markets"][0]
    mve = load("kalshi_market_mve.json")
    mid_window = 0.5 * (P.WINDOW_START + P.WINDOW_END)
    rows = [dict(P.parse_kalshi_market(m), close_ts=mid_window),
            dict(P.parse_kalshi_market(mve), close_ts=mid_window)]
    low = dict(rows[0], market_id="low", volume=10.0)
    scalar = dict(rows[0], market_id="scalar", outcome=None, result="scalar")
    late = dict(rows[0], market_id="late", close_ts=P.WINDOW_END)   # fixture's own close
    df = pd.DataFrame(rows + [low, scalar, late])
    out, steps = P.filter_cascade(df, "kalshi")
    assert list(out["market_id"]) == [rows[0]["market_id"]]
    assert steps[0]["remaining"] == 5
    assert {s["step"]: s["removed"] for s in steps}["close in 2026-08-25..2026-10-21"] == 1
    for prev, cur in zip(steps, steps[1:]):
        assert prev["remaining"] - cur["removed"] == cur["remaining"]


def test_stratified_sample_respects_caps_and_is_seeded():
    rng = np.random.default_rng(0)
    rows = []
    for c, n_ev in [("sports", 300), ("politics", 40), ("weather", 5)]:
        for e in range(n_ev):
            for k in range(rng.integers(1, 15)):
                rows.append({"category": c, "series": f"{c}-s{e % 7}", "event_id": f"{c}{e}",
                             "market_id": f"{c}{e}-{k}"})
    df = pd.DataFrame(rows)
    s1 = P.stratified_sample(df, budget=400, per_event_cap=5, per_series_cap=60, seed=1)
    s2 = P.stratified_sample(df, budget=400, per_event_cap=5, per_series_cap=60, seed=1)
    assert s1["market_id"].tolist() == s2["market_id"].tolist()
    assert len(s1) <= 400
    assert s1.groupby("event_id").size().max() <= 5
    assert s1.groupby("series").size().max() <= 60
    assert set(s1["category"]) == {"sports", "politics", "weather"}


def test_murphy_decomposition_sums_to_brier():
    price, y = synthetic(0.2, 1.2, 20_000, seed=7)
    d = A.murphy(price, y)
    assert d["reliability"] - d["resolution"] + d["uncertainty"] + d["within_bin"] == \
        pytest.approx(d["brier"], abs=1e-12)
    assert d["reliability"] >= 0 and d["resolution"] >= 0
    assert d["brier"] == pytest.approx(np.mean((price - y) ** 2))


def test_binned_table_recovers_favorite_longshot_sign():
    # beta > 1 -> longshots resolve less often than priced, favorites more often
    price, y = synthetic(0.0, 1.5, 60_000, seed=8)
    ev = np.arange(price.size).astype(str)
    rows = A.binned_table(price, y, ev, A.FLB_EDGES, A.FLB_LABELS, n_boot=100)
    by = {r["bin"]: r for r in rows}
    assert by["<10%"]["freq_minus_price"] < 0 and by["<10%"]["diff_ci"][1] < 0
    assert by[">90%"]["freq_minus_price"] > 0 and by[">90%"]["diff_ci"][0] > 0
