"""Tests for the forecast log. No network: venue payloads are fixtures."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "forecast_log"))
import pmlog  # noqa: E402

FUTURE = "2099-01-01T00:00:00Z"


def kalshi_payload(**overrides) -> dict:
    market = {"title": "Will X happen?", "status": "active", "result": "",
              "close_time": FUTURE, "yes_bid_dollars": "0.4100",
              "yes_ask_dollars": "0.4500", "last_price_dollars": "0.4300"}
    market.update(overrides)
    return {"market": market}


def polymarket_payload(**overrides) -> list:
    market = {"question": "Will Y happen?", "outcomes": '["Yes", "No"]',
              "outcomePrices": '["0.3", "0.7"]', "bestBid": 0.29, "bestAsk": 0.31,
              "lastTradePrice": 0.3, "closed": False, "active": True,
              "umaResolutionStatus": None, "endDate": FUTURE}
    market.update(overrides)
    return [market]


def fixed_fetch(quote: pmlog.MarketQuote):
    return lambda venue, market: quote


# ------------------------------------------------------------- parsing ---

def test_kalshi_quote_and_mid():
    quote = pmlog.parse_kalshi(kalshi_payload())
    assert (quote.bid, quote.ask, quote.last) == (0.41, 0.45, 0.43)
    assert quote.mid == pytest.approx(0.43)
    assert quote.is_open and quote.outcome == ""


def test_kalshi_empty_side_is_missing_not_zero():
    quote = pmlog.parse_kalshi(kalshi_payload(yes_bid_dollars="0.0000",
                                              yes_ask_dollars="1.0000"))
    assert quote.bid is None and quote.ask is None and quote.mid is None


@pytest.mark.parametrize("result, expected", [("yes", "1"), ("no", "0"), ("void", "void")])
def test_kalshi_resolution(result, expected):
    quote = pmlog.parse_kalshi(kalshi_payload(status="finalized", result=result))
    assert not quote.is_open and quote.outcome == expected


def test_polymarket_quote_and_resolution():
    open_quote = pmlog.parse_polymarket(polymarket_payload())
    assert open_quote.mid == pytest.approx(0.30) and open_quote.is_open
    resolved = pmlog.parse_polymarket(polymarket_payload(
        closed=True, active=True, umaResolutionStatus="resolved",
        outcomePrices='["1", "0"]'))
    assert resolved.outcome == "1" and not resolved.is_open
    no = pmlog.parse_polymarket(polymarket_payload(
        closed=True, umaResolutionStatus="resolved", outcomePrices='["0", "1"]'))
    assert no.outcome == "0"


def test_polymarket_rejects_non_binary_and_missing():
    with pytest.raises(ValueError):
        pmlog.parse_polymarket(polymarket_payload(outcomes='["Trump", "Harris"]'))
    with pytest.raises(LookupError):
        pmlog.parse_polymarket([])


def test_fetch_quote_url_encodes_market():
    seen = []

    def get_json(url):
        seen.append(url)
        return kalshi_payload()

    pmlog.fetch_quote("kalshi", "KX/ODD TICKER", get_json)
    assert seen == [pmlog.KALSHI_URL.format(market="KX%2FODD%20TICKER")]


# ----------------------------------------------------------------- add ---

def test_add_records_live_quote():
    rows = []
    quote = pmlog.parse_kalshi(kalshi_payload())
    row = pmlog.add_forecast(rows, venue="kalshi", market="KX1", prob=0.6,
                             fetch=fixed_fetch(quote))
    assert row["forecast_id"] == "F0001"
    assert row["market_mid"] == "0.4300"
    assert (row["market_bid"], row["market_ask"]) == ("0.4100", "0.4500")
    assert row["question"] == "Will X happen?" and row["outcome"] == ""


@pytest.mark.parametrize("kwargs, message", [
    ({"prob": 0.0}, "--prob"),
    ({"prob": 1.0}, "--prob"),
    ({"market_prob": 0.5}, "manual"),
])
def test_add_rejects_bad_input(kwargs, message):
    quote = pmlog.parse_kalshi(kalshi_payload())
    args = {"venue": "kalshi", "market": "KX1", "prob": 0.6, "fetch": fixed_fetch(quote)}
    args.update(kwargs)
    with pytest.raises(ValueError, match=message):
        pmlog.add_forecast([], **args)


def test_add_rejects_duplicate_market():
    quote = pmlog.parse_kalshi(kalshi_payload())
    rows = []
    pmlog.add_forecast(rows, venue="kalshi", market="KX1", prob=0.6, fetch=fixed_fetch(quote))
    with pytest.raises(ValueError, match="one forecast per market"):
        pmlog.add_forecast(rows, venue="kalshi", market="KX1", prob=0.7,
                           fetch=fixed_fetch(quote))


def test_add_rejects_closed_wide_or_one_sided_markets():
    closed = pmlog.parse_kalshi(kalshi_payload(status="finalized", result="yes"))
    wide = pmlog.parse_kalshi(kalshi_payload(yes_bid_dollars="0.10", yes_ask_dollars="0.90"))
    one_sided = pmlog.parse_kalshi(kalshi_payload(yes_bid_dollars="0.0000"))
    past = pmlog.parse_kalshi(kalshi_payload(close_time="2000-01-01T00:00:00Z"))
    for quote, message in ((closed, "not open"), (wide, "wider"),
                           (one_sided, "two-sided"), (past, "passed")):
        with pytest.raises(ValueError, match=message):
            pmlog.add_forecast([], venue="kalshi", market="KX1", prob=0.6,
                               fetch=fixed_fetch(quote))


def test_manual_forecast_needs_its_market_price():
    rows = []
    with pytest.raises(ValueError, match="manual"):
        pmlog.add_forecast(rows, venue="manual", market="m1", prob=0.6)
    row = pmlog.add_forecast(rows, venue="manual", market="m1", prob=0.6,
                             question="Q?", market_prob=0.55, close_utc=FUTURE)
    assert row["market_mid"] == "0.5500" and row["market_bid"] == ""


def test_csv_round_trip(tmp_path):
    rows = []
    pmlog.add_forecast(rows, venue="manual", market="m1", prob=0.6, question="Q, with comma?",
                       market_prob=0.55, close_utc=FUTURE, note='said "maybe"')
    path = tmp_path / "log.csv"
    pmlog.write_log(rows, path)
    assert pmlog.read_log(path) == rows


def test_resolve_from_venues_skips_manual_and_resolved():
    rows = []
    open_quote = pmlog.parse_kalshi(kalshi_payload())
    pmlog.add_forecast(rows, venue="kalshi", market="KX1", prob=0.6,
                       fetch=fixed_fetch(open_quote))
    pmlog.add_forecast(rows, venue="manual", market="m1", prob=0.6, question="Q?",
                       market_prob=0.5, close_utc=FUTURE)
    settled = pmlog.parse_kalshi(kalshi_payload(status="finalized", result="no"))
    assert pmlog.resolve_from_venues(rows, fixed_fetch(settled)) == ["F0001"]
    assert rows[0]["outcome"] == "0" and rows[1]["outcome"] == ""
    assert pmlog.resolve_from_venues(rows, fixed_fetch(settled)) == []


# ------------------------------------------------------------- scoring ---

def test_brier_and_log_loss_by_hand():
    forecasts = np.array([0.8, 0.3])
    outcomes = np.array([1.0, 0.0])
    assert pmlog.brier(forecasts, outcomes) == pytest.approx((0.04 + 0.09) / 2)
    assert pmlog.log_loss(forecasts, outcomes) == pytest.approx(
        -(np.log(0.8) + np.log(0.7)) / 2)


def test_murphy_identity_is_exact_when_bins_are_constant():
    forecasts = np.array([0.15, 0.15, 0.15, 0.75, 0.75])
    outcomes = np.array([0.0, 1.0, 0.0, 1.0, 1.0])
    parts = pmlog.murphy(forecasts, outcomes)
    rebuilt = parts["reliability"] - parts["resolution"] + parts["uncertainty"]
    assert rebuilt == pytest.approx(pmlog.brier(forecasts, outcomes))
    assert parts["within_bin"] == pytest.approx(0.0, abs=1e-12)


def test_murphy_reports_within_bin_gap():
    forecasts = np.array([0.11, 0.19, 0.6])
    outcomes = np.array([0.0, 1.0, 1.0])
    parts = pmlog.murphy(forecasts, outcomes)
    rebuilt = parts["reliability"] - parts["resolution"] + parts["uncertainty"]
    assert rebuilt + parts["within_bin"] == pytest.approx(pmlog.brier(forecasts, outcomes))
    assert parts["within_bin"] != pytest.approx(0.0)


@pytest.mark.parametrize("prob, outcome, expected", [
    (0.60, 1.0, 1 - 0.45),     # above the ask: buy YES at 0.45
    (0.60, 0.0, -0.45),
    (0.30, 0.0, 0.41),         # below the bid: sell YES at 0.41
    (0.30, 1.0, 0.41 - 1),
    (0.43, 1.0, None),         # inside the spread: no trade
])
def test_paper_pnl_signs(prob, outcome, expected):
    pnl = pmlog.paper_pnl(prob, 0.41, 0.45, outcome)
    assert pnl == (None if expected is None else pytest.approx(expected))


def test_paper_pnl_edge_threshold():
    assert pmlog.paper_pnl(0.47, 0.41, 0.45, 1.0, edge=0.03) is None
    assert pmlog.paper_pnl(0.49, 0.41, 0.45, 1.0, edge=0.03) == pytest.approx(0.55)


def test_score_compares_on_the_same_events():
    rows = []
    for i, (mine, market, outcome) in enumerate([(0.9, 0.6, "1"), (0.2, 0.5, "0"),
                                                 (0.7, 0.7, "void"), (0.5, 0.5, "")]):
        pmlog.add_forecast(rows, venue="manual", market=f"m{i}", prob=mine,
                           question="Q?", market_prob=market, close_utc=FUTURE)
        rows[-1]["outcome"] = outcome
    report = pmlog.score(rows)
    assert report["n"] == 2 and report["n_void"] == 1 and report["n_open"] == 1
    assert report["brier_me"] == pytest.approx((0.01 + 0.04) / 2)
    assert report["brier_market"] == pytest.approx((0.16 + 0.25) / 2)
    assert report["brier_skill_vs_market"] == pytest.approx(1 - 0.025 / 0.205)
    assert report["paper_trades"] == 0   # manual rows carry no bid/ask


def test_paired_bootstrap_is_seeded():
    diffs = np.array([-0.1, 0.05, -0.02, 0.0, -0.04])
    assert pmlog.paired_bootstrap(diffs) == pmlog.paired_bootstrap(diffs)
    lo, hi = pmlog.paired_bootstrap(diffs)
    assert lo <= diffs.mean() <= hi


# -------------------------------------------------------------- verify ---

def test_verify_flags_late_and_uncommitted_forecasts():
    rows = []
    for market in ("a", "b", "c"):
        pmlog.add_forecast(rows, venue="manual", market=market, prob=0.6, question="Q?",
                           market_prob=0.5, close_utc="2030-01-01T00:00:00Z",
                           created_utc="2029-06-01T00:00:00Z")
    rows[2]["created_utc"] = "2030-02-01T00:00:00Z"   # edited to look late
    commits = {"F0001": datetime(2029, 6, 1, 1, tzinfo=timezone.utc),
               "F0002": None,
               "F0003": datetime(2029, 6, 1, 1, tzinfo=timezone.utc)}
    problems = pmlog.verify(rows, commit_time=commits.get)
    assert problems == ["F0002: not in any git commit yet",
                        "F0003: created after the market closed"]


def test_verify_flags_commit_after_close():
    rows = []
    pmlog.add_forecast(rows, venue="manual", market="a", prob=0.6, question="Q?",
                       market_prob=0.5, close_utc="2030-01-01T00:00:00Z",
                       created_utc="2029-06-01T00:00:00Z")
    late = datetime(2030, 1, 2, tzinfo=timezone.utc)
    problems = pmlog.verify(rows, commit_time=lambda fid: late)
    assert len(problems) == 1 and "after close" in problems[0]


def test_parse_time_accepts_bare_dates():
    assert pmlog.parse_time("2026-12-01") == datetime(2026, 12, 1, tzinfo=timezone.utc)


def test_log_header_matches_columns():
    header = (Path(pmlog.__file__).parent / "forecasts.csv").read_text().splitlines()[0]
    assert header.split(",") == pmlog.COLUMNS
