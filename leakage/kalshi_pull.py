"""Pull settled Kalshi events, markets and public trades for chosen series.

    python3 -m leakage.kalshi_pull --discover mention,award,attend --out data/kalshi
    python3 -m leakage.kalshi_pull --series KXOSCARPIC,KXNOBELPEACE --since 2025-01-01
    python3 -m leakage.kalshi_pull --series-file my_series.txt --min-volume 500

Writes <out>/events.csv, markets.csv, trades.csv and cutoff.json. Re-running
resumes: markets listed in <out>/trades_done.txt are not fetched again.

Only public, unauthenticated GET endpoints are used, the same ones EventEdge's
python/kalshi.py uses, plus the historical tier Kalshi added for older data:
markets that settled before the cutoff are served by /historical/markets and
trades filled before it by /historical/trades. Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = os.environ.get("KALSHI_API_BASE",
                          "https://api.elections.kalshi.com/trade-api/v2").rstrip("/")
USER_AGENT = "prediction-market-portfolio-leakage/0.1 (+python urllib)"
MIN_INTERVAL_S = 0.12          # stay under ~8 requests per second

EVENT_FIELDS = ["event_ticker", "series_ticker", "title", "sub_title", "category",
                "mutually_exclusive", "strike_date"]
MARKET_FIELDS = ["ticker", "event_ticker", "series_ticker", "title", "subtitle",
                 "yes_sub_title", "no_sub_title", "open_time", "close_time",
                 "expected_expiration_time", "status", "result", "volume",
                 "can_close_early", "tier"]
TRADE_FIELDS = ["trade_id", "ticker", "created_time", "yes_price", "count",
                "taker_side", "tier"]


class KalshiError(RuntimeError):
    pass


_last_call = [0.0]


def _get(path: str, params: dict | None = None, *, retries: int = 4,
         timeout: float = 30.0) -> dict:
    """GET with retries on 429 / 5xx and a simple client-side rate limit."""
    query = {k: v for k, v in (params or {}).items() if v is not None}
    url = f"{BASE_URL}{path}" + ("?" + urllib.parse.urlencode(query) if query else "")
    delay = 1.0
    for attempt in range(retries + 1):
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 404:
                raise KalshiError(f"HTTP 404 for {url}") from err
            if not (err.code == 429 or err.code >= 500) or attempt == retries:
                body = err.read().decode("utf-8", "replace")[:300]
                raise KalshiError(f"HTTP {err.code} for {url}: {body}") from err
        except urllib.error.URLError as err:
            if attempt == retries:
                raise KalshiError(f"cannot reach {url}: {err.reason}") from err
        time.sleep(delay)
        delay *= 2
    raise KalshiError(f"unreachable: {url}")  # pragma: no cover


def _pages(path: str, key: str, params: dict, max_pages: int = 10_000):
    """Follow Kalshi's cursor pagination, yielding items under `key`."""
    cursor = None
    for _ in range(max_pages):
        page = _get(path, {**params, "cursor": cursor})
        yield from page.get(key, []) or []
        cursor = page.get("cursor")
        if not cursor:
            return


def leaf(obj: dict, key: str):
    """obj[key], preferring the *_dollars / *_fp sibling Kalshi now sends."""
    for suffix in ("_dollars", "_fp"):
        v = obj.get(key + suffix)
        if v not in (None, ""):
            return v
    return obj.get(key)


def price_to_prob(value) -> float | None:
    """Cents (1-99), a dollar string ("0.4200") or a float in [0, 1]."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, str):
        p = float(value)
    elif isinstance(value, int) or (isinstance(value, float) and value > 1.0):
        p = value / 100.0
    else:
        p = float(value)
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"price {value!r} is not a probability")
    return p


def parse_ts(value) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        frac, off = tail, ""
        for sign in ("+", "-"):
            if sign in tail:
                frac, rest = tail.split(sign, 1)
                off = sign + rest
                break
        text = f"{head}.{frac[:6]}{off}"
    t = datetime.fromisoformat(text)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return int(t.timestamp())


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

def get_cutoff() -> dict:
    """{market_settled_ts, trades_created_ts, ...} as epoch seconds; {} if absent."""
    try:
        raw = _get("/historical/cutoff")
    except KalshiError:
        return {}
    out = {}
    for k, v in raw.items():
        ts = parse_ts(v) if isinstance(v, (str, int, float)) else None
        if ts is not None:
            out[k] = ts
    return out


def list_series(category: str | None = None) -> list[dict]:
    return list(_pages("/series", "series", {"category": category}))


def events_for_series(series: str) -> list[dict]:
    return list(_pages("/events", "events",
                       {"series_ticker": series, "status": "settled", "limit": 200}))


def markets_for_series(series: str) -> list[dict]:
    """Settled markets from the live tier plus the historical tier, deduplicated."""
    seen: dict[str, dict] = {}
    for tier, path, params in (
            ("live", "/markets", {"series_ticker": series, "status": "settled", "limit": 1000}),
            ("historical", "/historical/markets", {"series_ticker": series, "limit": 1000})):
        try:
            for m in _pages(path, "markets", params):
                m = dict(m, tier=tier)
                seen.setdefault(m["ticker"], m)
        except KalshiError as err:
            if tier == "live":
                raise
            print(f"  historical markets unavailable for {series}: {err}", file=sys.stderr)
    return list(seen.values())


def trades_for_market(market: dict, cutoff: dict) -> list[dict]:
    """Public trades for one market from whichever tier holds them."""
    open_ts = parse_ts(market.get("open_time")) or 0
    close_ts = parse_ts(market.get("close_time")) or 2**62
    cut = cutoff.get("trades_created_ts")
    tiers = []
    if cut is None or close_ts >= cut:
        tiers.append(("live", "/markets/trades"))
    if cut is not None and open_ts < cut:
        tiers.append(("historical", "/historical/trades"))
    out: dict[str, dict] = {}
    for tier, path in tiers:
        try:
            for t in _pages(path, "trades", {"ticker": market["ticker"], "limit": 1000}):
                out.setdefault(t.get("trade_id") or f"{tier}-{len(out)}", dict(t, tier=tier))
        except KalshiError as err:
            if tier == "live" and len(tiers) == 1:
                raise
            print(f"  {tier} trades unavailable for {market['ticker']}: {err}", file=sys.stderr)
    return list(out.values())


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------

def event_row(e: dict) -> dict:
    return {k: e.get(k, "") for k in EVENT_FIELDS}


def market_row(m: dict, series: str) -> dict:
    row = {k: m.get(k, "") for k in MARKET_FIELDS}
    row["series_ticker"] = m.get("series_ticker") or series
    row["volume"] = leaf(m, "volume") or ""
    return row


def trade_row(t: dict) -> dict:
    p = price_to_prob(leaf(t, "yes_price"))
    return {"trade_id": t.get("trade_id", ""), "ticker": t.get("ticker", ""),
            "created_time": t.get("created_time", ""),
            "yes_price": "" if p is None else f"{p:.4f}",
            "count": leaf(t, "count") or "", "taker_side": t.get("taker_side", ""),
            "tier": t.get("tier", "")}


def _append(path: Path, fields: list[str], rows: list[dict]) -> None:
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def discover(keywords: list[str], category: str | None, limit: int) -> list[str]:
    keys = [k.strip().lower() for k in keywords if k.strip()]
    found = []
    for s in list_series(category):
        text = " ".join(str(s.get(k, "")) for k in ("ticker", "title", "category", "tags")).lower()
        if any(k in text for k in keys):
            found.append(s["ticker"])
    return sorted(set(found))[:limit]


def pull(series_list: list[str], out: Path, *, since: int | None = None,
         until: int | None = None, min_volume: float = 0.0,
         max_markets: int | None = None, dry_run: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    cutoff = get_cutoff()
    (out / "cutoff.json").write_text(json.dumps(cutoff, indent=2))
    done_path = out / "trades_done.txt"
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    stats = {"series": 0, "events": 0, "markets": 0, "trades": 0}
    budget = max_markets
    for series in series_list:
        print(f"[{series}]", file=sys.stderr)
        events = events_for_series(series)
        markets = markets_for_series(series)
        keep = []
        for m in markets:
            close_ts = parse_ts(m.get("close_time"))
            vol = float(leaf(m, "volume") or 0)
            if (m.get("result") or "").lower() not in ("yes", "no"):
                continue
            if since and (close_ts or 0) < since or until and (close_ts or 0) > until:
                continue
            if vol < min_volume or m["ticker"] in done:
                continue
            keep.append(m)
        if budget is not None:
            keep = keep[:max(budget, 0)]
            budget -= len(keep)
        print(f"  {len(events)} events, {len(markets)} settled markets, "
              f"{len(keep)} to fetch", file=sys.stderr)
        stats["series"] += 1
        if dry_run:
            continue
        _append(out / "events.csv", EVENT_FIELDS, [event_row(e) for e in events])
        _append(out / "markets.csv", MARKET_FIELDS, [market_row(m, series) for m in keep])
        stats["events"] += len(events)
        stats["markets"] += len(keep)
        for m in keep:
            rows = [trade_row(t) for t in trades_for_market(m, cutoff)]
            _append(out / "trades.csv", TRADE_FIELDS, rows)
            with open(done_path, "a") as f:
                f.write(m["ticker"] + "\n")
            stats["trades"] += len(rows)
        if budget is not None and budget <= 0:
            break
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", default="", help="comma-separated series tickers")
    ap.add_argument("--series-file", help="file with one series ticker per line")
    ap.add_argument("--discover", default="",
                    help="comma-separated keywords matched against series ticker/title/category")
    ap.add_argument("--category", help="restrict --discover to one Kalshi category")
    ap.add_argument("--max-series", type=int, default=60)
    ap.add_argument("--out", default="data/kalshi")
    ap.add_argument("--since", help="keep markets closing on/after YYYY-MM-DD")
    ap.add_argument("--until", help="keep markets closing on/before YYYY-MM-DD")
    ap.add_argument("--min-volume", type=float, default=100.0)
    ap.add_argument("--max-markets", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    series = [s.strip() for s in a.series.split(",") if s.strip()]
    if a.series_file:
        series += [s.strip() for s in Path(a.series_file).read_text().split() if s.strip()]
    if a.discover:
        series += discover(a.discover.split(","), a.category, a.max_series)
    series = list(dict.fromkeys(series))
    if not series:
        ap.error("give --series, --series-file or --discover")
    day = lambda s: parse_ts(s + "T00:00:00Z") if s else None
    stats = pull(series, Path(a.out), since=day(a.since), until=day(a.until),
                 min_volume=a.min_volume, max_markets=a.max_markets, dry_run=a.dry_run)
    print(json.dumps(stats), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
