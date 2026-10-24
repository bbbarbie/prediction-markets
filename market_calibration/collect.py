"""Collect resolved binary markets and pre-close price histories.

Kalshi (https://api.elections.kalshi.com/trade-api/v2, public, no auth)
  1. GET /series                       series -> category catalogue (1 request)
  2. GET /events?status=settled        all settled events in the live API
  3. GET /markets?series_ticker=...    settled markets per sampled series,
                                       restricted to the study window
  4. GET /markets/candlesticks         hourly candles, up to 100 markets and
                                       10,000 candles per request

Polymarket (public, no auth)
  1. GET gamma /events/keyset          closed events (nested markets): all
                                       non-sports events, plus sports events
                                       in ten sampled one-day slices
  2. GET clob /prices-history          hourly price history of the YES token

Every response is cached under data/raw/ (see http_cache.py), so rerunning a
step resumes where it stopped and a complete rerun makes no network requests.

Usage:
  python collect.py kalshi        # all Kalshi steps
  python collect.py polymarket    # all Polymarket steps
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

from http_cache import Fetcher
import parsers as P

ROOT = Path(__file__).resolve().parent
INTERIM = ROOT / "data" / "interim"

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

SEED = 20261024


# ----------------------------------------------------------------------------
# Kalshi
# ----------------------------------------------------------------------------
def kalshi_series(f: Fetcher) -> dict:
    status, body = f.get(f"{KALSHI}/series", venue="kalshi", kind="series")
    assert status == 200, status
    return {s["ticker"]: s for s in body["series"]}


_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def ticker_date(event_ticker: str) -> float | None:
    """Date encoded in a Kalshi event ticker ('KXNBAGAME-26OCT24LALGSW' -> 2026-10-24)."""
    import re
    m = re.search(r"-(\d\d)([A-Z]{3})(\d\d)", event_ticker)
    if not m or m.group(2) not in _MONTHS:
        return None
    try:
        return pd.Timestamp(year=2000 + int(m.group(1)), month=_MONTHS[m.group(2)],
                            day=int(m.group(3)), tz="UTC").timestamp()
    except ValueError:
        return None


def kalshi_events(f: Fetcher, max_pages: int = 5000) -> list[dict]:
    """Page /events?status=settled (newest first) until the window is passed.

    The listing has no close-time filter but is ordered roughly newest first
    (a few long-dated events come first); we stop after ten consecutive pages
    whose median ticker date is more than one day before the window start.
    """
    import statistics

    events, cursor, pages, n_past = [], None, 0, 0
    while True:
        params = {"status": "settled", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        status, body = f.get(f"{KALSHI}/events", params, venue="kalshi", kind="events")
        assert status == 200, (status, body)
        page = body.get("events", [])
        events.extend(page)
        pages += 1
        cursor = body.get("cursor")
        if pages % 100 == 0:
            print(f"  kalshi events: {pages} pages, {len(events)} events", flush=True)
        dates = [d for d in (ticker_date(e["event_ticker"]) for e in page) if d]
        past = bool(dates) and statistics.median(dates) < P.WINDOW_START - P.DAY
        n_past = n_past + 1 if past else 0
        if not cursor or not page or pages >= max_pages or n_past >= 10:
            break
    print(f"kalshi events: {len(events)} events in {pages} pages", flush=True)
    return events


# ----------------------------------------------------------------------------
# Polymarket
# ----------------------------------------------------------------------------
# Gamma /markets cannot exclude tags, and closed markets in the window are
# dominated by 5-minute crypto "Up or Down" markets (not YES/NO) and sports
# props. /events/keyset can exclude tags and filter on event volume, and nests
# the full market objects, so we page events instead:
#   * non-sports: every closed event (minus sports and up-or-down)
#   * sports:     every closed sports event in sampled one-day end-date slices
POLY_EVENT_BASE = {"closed": "true", "limit": 100, "volume_min": 1000}
POLY_NONSPORT = dict(POLY_EVENT_BASE, end_date_min="2026-07-26T00:00:00Z",
                     exclude_tag_id=["1", "102127"])   # 1 = sports, 102127 = up-or-down
POLY_SPORT_TAG = "1"


def poly_event_chain(f: Fetcher, params: dict, label: str, max_pages: int = 2000) -> list[dict]:
    events, cursor, pages = [], None, 0
    while True:
        q = dict(params)
        if cursor:
            q["after_cursor"] = cursor
        status, body = f.get(f"{GAMMA}/events/keyset", q, venue="polymarket", kind="events")
        assert status == 200, (status, str(body)[:300])
        events.extend(body.get("events", []))
        pages += 1
        cursor = body.get("next_cursor")
        if pages % 20 == 0:
            print(f"  polymarket {label}: {pages} pages, {len(events)} events", flush=True)
        if not cursor or not body.get("events") or pages >= max_pages:
            break
    print(f"polymarket {label}: {len(events)} events in {pages} pages "
          f"(truncated={bool(cursor) and pages >= max_pages})", flush=True)
    return events


SPORT_DAYS = [f"2026-{d}" for d in ("08-26", "09-01", "09-07", "09-13", "09-19",
                                       "09-25", "10-01", "10-07", "10-13", "10-19")]


def poly_events(f: Fetcher) -> list[tuple[str, dict]]:
    out = [("non-sport", e) for e in poly_event_chain(f, POLY_NONSPORT, "non-sport")]
    for day in SPORT_DAYS:
        y, m, d = map(int, day.split("-"))
        nxt = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        params = dict(POLY_EVENT_BASE, tag_id=POLY_SPORT_TAG,
                      end_date_min=f"{day}T00:00:00Z", end_date_max=f"{nxt}T00:00:00Z")
        out += [(f"sport {day}", e) for e in poly_event_chain(f, params, f"sport {day}")]
    return out


def poly_universe(f: Fetcher) -> pd.DataFrame:
    rows, seen = [], set()
    for chain, e in poly_events(f):
        for m in e.get("markets") or []:
            r = P.parse_poly_market(m, event=e)
            if r["market_id"] in seen:
                continue
            seen.add(r["market_id"])
            r["chain"] = chain
            rows.append(r)
    return pd.DataFrame(rows)


def poly_price_window(r) -> tuple[int, int]:
    start = r["ref_ts"] - 8 * P.DAY - 2 * P.HOUR
    closed = r["closed_ts"] if pd.notna(r["closed_ts"]) else r["ref_ts"]
    end = max(r["ref_ts"], closed) + P.HOUR
    start = max(start, end - 60 * P.DAY)
    return int(start), int(end)


def poly_fetch_prices(f: Fetcher, sample: pd.DataFrame) -> None:
    n = len(sample)
    for i, (_, r) in enumerate(sample.iterrows(), 1):
        start, end = poly_price_window(r)
        f.get(f"{CLOB}/prices-history",
              {"market": r["yes_token"], "startTs": start, "endTs": end, "fidelity": 60},
              venue="polymarket", kind="prices")
        if i % 250 == 0:
            print(f"  polymarket prices: {i}/{n}", flush=True)


# ----------------------------------------------------------------------------
# Kalshi universe and candles
# ----------------------------------------------------------------------------
def kalshi_active_series(events: list[dict], series: dict) -> pd.DataFrame:
    n = defaultdict(int)
    for e in events:
        n[e["series_ticker"]] += 1
    rows = []
    for s, k in n.items():
        meta = series.get(s, {})
        rows.append({"series": s, "n_events": k, "category_raw": meta.get("category"),
                     "category": P.kalshi_category(meta.get("category")),
                     "frequency": meta.get("frequency")})
    return pd.DataFrame(rows).sort_values("series").reset_index(drop=True)


def choose_kalshi_series(active: pd.DataFrame, budget: int, seed: int) -> pd.DataFrame:
    """Seeded, category-balanced choice of series to list.

    Multivariate (KXMVE*) and 15-minute series are skipped up front: MVE
    markets are excluded by design and 15-minute markets do not exist 1 h
    (let alone 24 h) before their close.
    """
    a = active[~active["series"].str.startswith("KXMVE")
               & (active["frequency"] != "fifteen_min")].copy()
    a["event_id"] = a["series"]          # one "event" per series for the sampler
    a["market_id"] = a["series"]
    picked = P.stratified_sample(a, budget=budget, per_event_cap=1,
                                 per_series_cap=1, seed=seed)
    return picked[["series", "n_events", "category_raw", "category", "frequency"]]


def kalshi_list_series_markets(f: Fetcher, series_list: list[str]) -> tuple[list[dict], dict]:
    markets, truncated = [], {}
    for i, s in enumerate(series_list, 1):
        params = {"series_ticker": s, "status": "settled", "limit": 1000,
                  "mve_filter": "exclude",
                  "min_close_ts": int(P.WINDOW_START), "max_close_ts": int(P.WINDOW_END) - 1}
        status, body = f.get(f"{KALSHI}/markets", params, venue="kalshi", kind="markets")
        if status != 200:
            print(f"  kalshi markets {s}: HTTP {status}", flush=True)
            continue
        for m in body.get("markets", []):
            m["_series_ticker"] = s
            markets.append(m)
        truncated[s] = bool(body.get("cursor"))
        if i % 200 == 0:
            print(f"  kalshi series listed: {i}/{len(series_list)}, {len(markets)} markets",
                  flush=True)
    return markets, truncated


def kalshi_candle_batches(sample: pd.DataFrame, max_markets: int = 100,
                          max_candles: int = 10000) -> list[dict]:
    """Group markets with nearby close times into batch-candle requests.

    Every market in a batch shares [min close - 8 d - 2 h, max close]; the API
    counts markets x hours in that window against the 10,000-candle limit.
    """
    s = sample.sort_values(["close_ts", "market_id"])
    batches, cur = [], []
    for _, r in s.iterrows():
        trial = cur + [r]
        lo = min(x["close_ts"] for x in trial) - 8 * P.DAY - 2 * P.HOUR
        hi = max(x["close_ts"] for x in trial)
        hours = int((hi - lo) // P.HOUR) + 2
        if cur and (len(trial) > max_markets or len(trial) * hours > max_candles):
            batches.append(cur)
            cur = [r]
        else:
            cur = trial
    if cur:
        batches.append(cur)
    out = []
    for b in batches:
        lo = int(min(x["close_ts"] for x in b) - 8 * P.DAY - 2 * P.HOUR)
        hi = int(max(x["close_ts"] for x in b))
        out.append({"tickers": [x["market_id"] for x in b], "start_ts": lo, "end_ts": hi})
    return out


def kalshi_fetch_candles(f: Fetcher, batches: list[dict]) -> None:
    for i, b in enumerate(batches, 1):
        params = {"market_tickers": ",".join(b["tickers"]), "start_ts": b["start_ts"],
                  "end_ts": b["end_ts"], "period_interval": 60}
        status, body = f.get(f"{KALSHI}/markets/candlesticks", params,
                             venue="kalshi", kind="candles")
        if status != 200:
            print(f"  kalshi candles batch {i}: HTTP {status} {str(body)[:200]}", flush=True)
        if i % 50 == 0:
            print(f"  kalshi candle batches: {i}/{len(batches)}", flush=True)


# ----------------------------------------------------------------------------
# pipelines
# ----------------------------------------------------------------------------
KALSHI_SERIES_BUDGET = 2400
SAMPLE = {"kalshi": dict(budget=20000, per_event_cap=10, per_series_cap=150),
          "polymarket": dict(budget=5500, per_event_cap=10, per_series_cap=150)}


def write_steps(path: Path, steps: list[dict], extra: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"steps": steps, **(extra or {})}, indent=1))


def run_kalshi(f: Fetcher) -> pd.DataFrame:
    INTERIM.mkdir(parents=True, exist_ok=True)
    series = kalshi_series(f)
    events = kalshi_events(f)
    active = kalshi_active_series(events, series)
    active.to_csv(INTERIM / "kalshi_active_series.csv", index=False)
    chosen = choose_kalshi_series(active, KALSHI_SERIES_BUDGET, SEED)
    chosen.to_csv(INTERIM / "kalshi_series_listed.csv", index=False)
    print(f"kalshi: {len(active)} active series, listing {len(chosen)}", flush=True)
    raw, truncated = kalshi_list_series_markets(f, chosen["series"].tolist())
    cat = {s: m.get("category") for s, m in series.items()}
    uni = pd.DataFrame([P.parse_kalshi_market(m, cat) for m in raw])
    uni = uni.drop_duplicates("market_id").reset_index(drop=True)
    uni.to_csv(INTERIM / "kalshi_universe.csv", index=False)
    eligible, steps = P.filter_cascade(uni, "kalshi")
    sample = P.stratified_sample(eligible, seed=SEED, **SAMPLE["kalshi"])
    steps.append({"step": "stratified sample", "remaining": int(len(sample)),
                  "removed": int(len(eligible) - len(sample))})
    sample.to_csv(INTERIM / "kalshi_sample.csv", index=False)
    write_steps(INTERIM / "kalshi_filters.json", steps,
                {"n_events_listed": len(events), "n_active_series": int(len(active)),
                 "n_series_listed": int(len(chosen)),
                 "n_series_truncated_at_1000": int(sum(truncated.values()))})
    for s in steps:
        print(f"  {s['step']:<40} {s['remaining']:>8} (-{s['removed']})")
    batches = kalshi_candle_batches(sample)
    print(f"kalshi: {len(sample)} sampled markets in {len(batches)} candle batches", flush=True)
    kalshi_fetch_candles(f, batches)
    (INTERIM / "kalshi_candle_batches.json").write_text(json.dumps(batches))
    return sample


def run_polymarket(f: Fetcher) -> pd.DataFrame:
    INTERIM.mkdir(parents=True, exist_ok=True)
    uni = poly_universe(f)
    uni.to_csv(INTERIM / "polymarket_universe.csv", index=False)
    eligible, steps = P.filter_cascade(uni, "polymarket")
    sample = P.stratified_sample(eligible, seed=SEED, **SAMPLE["polymarket"])
    steps.append({"step": "stratified sample", "remaining": int(len(sample)),
                  "removed": int(len(eligible) - len(sample))})
    sample.to_csv(INTERIM / "polymarket_sample.csv", index=False)
    write_steps(INTERIM / "polymarket_filters.json", steps,
                {"sport_days": SPORT_DAYS})
    for s in steps:
        print(f"  {s['step']:<40} {s['remaining']:>8} (-{s['removed']})")
    print(f"polymarket: fetching price history for {len(sample)} markets", flush=True)
    poly_fetch_prices(f, sample)
    return sample


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("venue", choices=["kalshi", "polymarket", "kalshi-events", "poly-list"])
    ap.add_argument("--offline", action="store_true",
                    help="use only cached responses (no network)")
    args = ap.parse_args(argv)
    f = Fetcher(offline=args.offline)
    if args.venue == "kalshi-events":
        kalshi_series(f)
        kalshi_events(f)
    elif args.venue == "poly-list":
        poly_event_chain(f, POLY_NONSPORT, "non-sport")
    elif args.venue == "kalshi":
        run_kalshi(f)
    else:
        run_polymarket(f)
    print(f"http: {f.n_network} network requests, {f.n_cached} cache hits, "
          f"{f.n_retries} retries", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
