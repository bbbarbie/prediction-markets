"""Build data/markets.csv (one row per sampled market) from cached responses.

Runs offline: it only reads data/interim/ (written by collect.py) and the
response cache under data/raw/. A market missing from the cache is reported,
never fetched.

Price at horizon h (7d, 24h, 1h before the reference close):
  Kalshi      last traded price in the latest hourly candle that ENDS at or
              before close - h (candles without a trade are skipped). Staleness
              = horizon - candle end, so the true trade age is between that
              and that + 1 h. The bid/ask midpoint of the same candle rule is
              kept as a secondary price (mid_*).
  Polymarket  last point of the CLOB /prices-history series (hourly fidelity,
              Polymarket's displayed price: midpoint, or last trade when the
              spread is wide) at or before ref - h. Staleness = horizon -
              point time. Polymarket gives no per-point trade flag, so this is
              the age of the price observation, not of the last trade.
A market is dropped at a horizon when staleness > 24 h (status 'stale') or
there is no observation at or before the horizon (status 'none').
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

import parsers as P
from http_cache import Fetcher

ROOT = Path(__file__).resolve().parent
INTERIM = ROOT / "data" / "interim"
OUT_CSV = ROOT / "data" / "markets.csv"
SUMMARY = ROOT / "results" / "dataset_summary.json"

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
CLOB = "https://clob.polymarket.com"


def horizon_columns(series, ref_ts, prefix=""):
    out = {}
    for name, secs in P.HORIZONS.items():
        price, stale, status = P.price_at(series, ref_ts - secs)
        out[f"{prefix}price_{name}"] = price
        out[f"{prefix}staleness_h_{name}"] = stale / 3600 if not math.isnan(stale) else math.nan
        out[f"{prefix}status_{name}"] = status
    return out


def build_kalshi(f: Fetcher) -> pd.DataFrame:
    sample = pd.read_csv(INTERIM / "kalshi_sample.csv")
    batches = json.loads((INTERIM / "kalshi_candle_batches.json").read_text())
    candles, missing_batches = {}, 0
    for b in batches:
        params = {"market_tickers": ",".join(b["tickers"]), "start_ts": b["start_ts"],
                  "end_ts": b["end_ts"], "period_interval": 60}
        status, body = f.get(f"{KALSHI}/markets/candlesticks", params,
                             venue="kalshi", kind="candles")
        if status != 200:
            missing_batches += 1
            continue
        for m in body.get("markets", []):
            candles[m["market_ticker"]] = m.get("candlesticks", [])
    rows = []
    for _, r in sample.iterrows():
        c = candles.get(r["market_id"])
        row = {
            "venue": "kalshi", "market_id": r["market_id"], "event_id": r["event_id"],
            "series": r["series"], "category": r["category"],
            "category_raw": r["category_raw"], "title": r["title"],
            "close_time": P.iso(r["close_ts"]), "close_ts": r["close_ts"],
            "close_source": "close_time", "actual_close_time": P.iso(r["close_ts"]),
            # Kalshi publishes no original close time. Scheduled closes fall on a
            # whole minute; closes triggered by an occurrence ("closes early if
            # X happens") fall on arbitrary seconds. Sports close when the game
            # ends, which does not depend on who wins, so they count as scheduled.
            "scheduled_close": bool(r["close_ts"] % 60 == 0 or r["category"] == "sports"),
            "open_time": P.iso(r["open_ts"]) if pd.notna(r["open_ts"]) else "",
            "outcome": int(r["outcome"]), "volume": r["volume"],
            "has_history": c is not None,
        }
        trades = P.kalshi_trade_series(c or [])
        row.update(horizon_columns(trades, r["close_ts"]))
        row.update(horizon_columns(P.kalshi_mid_series(c or []), r["close_ts"], prefix="mid_"))
        rows.append(row)
    print(f"kalshi: {len(rows)} markets, {missing_batches} candle batches missing from cache")
    return pd.DataFrame(rows)


def build_polymarket(f: Fetcher) -> pd.DataFrame:
    from collect import poly_price_window

    sample = pd.read_csv(INTERIM / "polymarket_sample.csv", dtype={"yes_token": str,
                                                                    "event_id": str})
    rows, missing = [], 0
    for _, r in sample.iterrows():
        start, end = poly_price_window(r)
        status, body = f.get(f"{CLOB}/prices-history",
                             {"market": r["yes_token"], "startTs": start, "endTs": end,
                              "fidelity": 60}, venue="polymarket", kind="prices")
        if status == -1:
            missing += 1
        hist = body.get("history", []) if status == 200 and isinstance(body, dict) else None
        row = {
            "venue": "polymarket", "market_id": r["market_id"], "event_id": r["event_id"],
            "series": r["series"], "category": r["category"],
            "category_raw": r["category_raw"], "title": r["title"],
            "close_time": P.iso(r["ref_ts"]), "close_ts": r["ref_ts"],
            "close_source": r["ref_source"],
            # closed before both the scheduled end date and the game start:
            # the close was triggered by the outcome (or its resolution)
            "scheduled_close": r["ref_source"] in ("end", "game_start"),
            "actual_close_time": P.iso(r["closed_ts"]) if pd.notna(r["closed_ts"]) else "",
            "open_time": P.iso(r["open_ts"]) if pd.notna(r["open_ts"]) else "",
            "outcome": int(r["outcome"]), "volume": r["volume"],
            "has_history": bool(hist),
        }
        row.update(horizon_columns(P.poly_series(hist or []), r["ref_ts"]))
        rows.append(row)
    print(f"polymarket: {len(rows)} markets, {missing} price histories missing from cache")
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> dict:
    out = {"generated_from": "data/markets.csv", "max_staleness_hours": P.MAX_STALENESS / 3600,
           "window": [P.iso(P.WINDOW_START), P.iso(P.WINDOW_END)],
           "min_volume": P.MIN_VOLUME, "venues": {}}
    for venue, g in df.groupby("venue"):
        steps = json.loads((INTERIM / f"{venue}_filters.json").read_text())
        v = {"filters": steps, "n_markets": int(len(g)), "n_events": int(g["event_id"].nunique()),
             "n_series": int(g["series"].nunique()),
             "markets_by_category": g["category"].value_counts().to_dict(),
             "horizons": {}}
        for h in P.HORIZONS:
            st = g[f"status_{h}"].value_counts().to_dict()
            ok = g[g[f"status_{h}"] == "ok"]
            v["horizons"][h] = {
                "status_counts": {k: int(x) for k, x in st.items()},
                "n_ok": int(len(ok)), "n_events_ok": int(ok["event_id"].nunique()),
                "staleness_hours_median": float(ok[f"staleness_h_{h}"].median()) if len(ok) else None,
                "staleness_hours_p90": float(ok[f"staleness_h_{h}"].quantile(0.9)) if len(ok) else None,
                "yes_rate": float(ok["outcome"].mean()) if len(ok) else None,
            }
        if venue == "polymarket":
            v["close_source_counts"] = g["close_source"].value_counts().to_dict()
        v["scheduled_close_share"] = float(g["scheduled_close"].mean())
        out["venues"][venue] = v
    return out


def main() -> int:
    f = Fetcher(offline=True, verbose=False)
    parts = []
    for name, fn in [("kalshi", build_kalshi), ("polymarket", build_polymarket)]:
        if (INTERIM / f"{name}_sample.csv").exists():
            parts.append(fn(f))
        else:
            print(f"{name}: no sample yet (run collect.py {name})")
    df = pd.concat(parts, ignore_index=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize(df)
    SUMMARY.write_text(json.dumps(summary, indent=1, default=int))
    print(f"wrote {OUT_CSV} ({len(df)} rows) and {SUMMARY}")
    for venue, v in summary["venues"].items():
        for h, s in v["horizons"].items():
            print(f"  {venue:<11} {h:>3}: {s['n_ok']:>6} ok  {s['status_counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
