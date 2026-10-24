"""Pure parsing and price-at-horizon logic (no network, unit tested).

Field names were checked against live responses on 2026-10-24; small copies
of those responses are in tests/fixtures/.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

HOUR = 3600
DAY = 86400

# Horizons before the reference close time, in seconds.
HORIZONS = {"7d": 7 * DAY, "24h": DAY, "1h": HOUR}
# Main staleness rule: drop a market at a horizon if its last observation at or
# before the horizon is older than this.
MAX_STALENESS = DAY


# ----------------------------------------------------------------------------
# time helpers
# ----------------------------------------------------------------------------
def to_ts(value) -> float | None:
    """Parse ISO-8601 strings in the shapes both venues use to unix seconds.

    Kalshi:     '2026-10-24T06:57:54Z', '2026-10-24T06:54:20.20361Z'
    Polymarket: '2026-10-24 07:00:58.114458+00', '2026-09-16T00:00:00Z'
    """
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if s.endswith("+00"):
        s = s + ":00"
    # Python < 3.11 cannot parse fractional seconds that are not 3 or 6 digits
    if "." in s:
        head, rest = s.split(".", 1)
        frac = "".join(ch for ch in rest if ch.isdigit())
        tz = rest[len(frac):]
        s = f"{head}.{(frac + '000000')[:6]}{tz}"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def iso(ts: float | None) -> str:
    if ts is None or (isinstance(ts, float) and math.isnan(ts)):
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(x) -> float | None:
    if x in (None, ""):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ----------------------------------------------------------------------------
# categories
# ----------------------------------------------------------------------------
KALSHI_CATEGORY = {
    "Sports": "sports",
    "Elections": "politics", "Politics": "politics", "World": "politics",
    "Economics": "economics", "Financials": "economics",
    "Commodities": "economics", "Companies": "economics", "Business": "economics",
    "Crypto": "crypto",
    "Climate and Weather": "weather",
    "Entertainment": "culture", "Mentions": "culture", "Social": "culture",
    "Culture": "culture",
    "Science and Technology": "science_tech", "Health": "science_tech",
    "Transportation": "science_tech", "Education": "other", "Exotics": "other",
}

# Polymarket has no single category field on new markets; map tag slugs, first
# matching group wins (order matters: a Fed market tagged politics+economy is
# economics; a Trump-tweets market tagged politics+tweets is culture).
POLY_TAG_GROUPS = [
    ("crypto", {"crypto", "crypto-prices", "bitcoin", "ethereum", "solana", "xrp",
                "fdv", "token-launch", "pre-market", "airdrops", "memecoins",
                "stablecoins", "doge", "crypto-policy"}),
    ("weather", {"weather", "climate", "temperature", "global-temp", "hurricanes",
                 "climate-science", "daily-temperature", "natural-disasters"}),
    ("sports", {"sports", "games", "soccer", "tennis", "baseball", "basketball",
                "football", "nfl", "nba", "mlb", "nhl", "ufc", "esports", "golf",
                "cricket", "f1", "boxing", "hockey", "cfb", "college-football",
                "ncaa", "mma", "olympics", "chess", "cycling", "rugby"}),
    ("economics", {"economy", "finance", "fed", "fed-rates", "business", "equities",
                   "earnings", "stocks", "oil", "commodities", "big-tech",
                   "hit-price", "ipos", "privates", "kpis", "inflation", "economic-policy",
                   "gdp", "jobs", "interest-rates", "tariffs", "trade-war", "gold",
                   "forex", "treasuries", "housing"}),
    ("science_tech", {"tech", "ai", "science", "space", "ai-releases", "openai",
                      "spacex", "health", "pandemics"}),
    ("culture", {"pop-culture", "culture", "entertainment", "awards", "celebrities",
                 "music", "movies", "tweets-markets", "mentions", "elon-tweets",
                 "youtube", "tv", "box-office", "streaming", "spotify", "gaming",
                 "oscars", "grammys", "religion", "mrbeast"}),
    ("politics", {"politics", "elections", "global-elections", "geopolitics", "world",
                  "trump", "us-presidential-election", "main-election", "primaries",
                  "primary-elections", "us-politics", "world-elections", "iran",
                  "ukraine", "israel", "middle-east", "china", "congress", "courts",
                  "scotus", "trump-cabinet", "democratic-primary", "us-election",
                  "foreign-policy", "immigration"}),
]


def kalshi_category(raw: str | None) -> str:
    return KALSHI_CATEGORY.get(raw or "", "other")


def poly_category(tag_slugs) -> str:
    slugs = set(tag_slugs or [])
    for name, group in POLY_TAG_GROUPS:
        if slugs & group:
            return name
    return "other"


# ----------------------------------------------------------------------------
# market records
# ----------------------------------------------------------------------------
def is_kalshi_mve(m: dict) -> bool:
    """Multivariate combo markets (parlays) are excluded."""
    return (str(m.get("event_ticker", "")).startswith("KXMVE")
            or str(m.get("ticker", "")).startswith("KXMVE")
            or bool(m.get("mve_collection_ticker"))
            or bool(m.get("mve_selected_legs")))


def parse_kalshi_market(m: dict, series_category: dict | None = None) -> dict:
    """Flatten one Kalshi /markets item."""
    event = m.get("event_ticker", "")
    series = m.get("_series_ticker") or event.split("-")[0]
    raw_cat = (series_category or {}).get(series)
    result = m.get("result")
    outcome = 1 if result == "yes" else 0 if result == "no" else None
    return {
        "venue": "kalshi",
        "market_id": m.get("ticker"),
        "event_id": event,
        "series": series,
        "category_raw": raw_cat,
        "category": kalshi_category(raw_cat),
        "title": m.get("title"),
        "market_type": m.get("market_type"),
        "status": m.get("status"),
        "result": result,
        "outcome": outcome,
        "is_mve": is_kalshi_mve(m),
        "open_ts": to_ts(m.get("open_time")),
        "close_ts": to_ts(m.get("close_time")),
        "scheduled_ts": to_ts(m.get("expected_expiration_time")),
        "can_close_early": bool(m.get("can_close_early")),
        "volume": _num(m.get("volume_fp")) if m.get("volume_fp") is not None
        else _num(m.get("volume")),
    }


def _json_list(x):
    if x is None:
        return None
    if isinstance(x, list):
        return x
    try:
        v = json.loads(x)
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, list) else None


def parse_poly_market(m: dict, event: dict | None = None) -> dict:
    """Flatten one Gamma market object (as nested in an /events item).

    ``outcomes``, ``outcomePrices`` and ``clobTokenIds`` are JSON-encoded
    strings. A market counts as resolved YES/NO only if outcomes are exactly
    ["Yes","No"], umaResolutionStatus is 'resolved' and outcomePrices is
    exactly ["1","0"] (YES) or ["0","1"] (NO).

    Reference close time ``ref_ts`` = earliest of the actual close
    (closedTime), the scheduled end (endDate) and, when present, the game start
    (gameStartTime; sports events also expose event.startTime). Polymarket's
    closedTime is an administrative time after the UMA resolution, often hours
    after the outcome is public, so prices just before it are post-outcome.
    """
    outcomes = _json_list(m.get("outcomes"))
    prices = _json_list(m.get("outcomePrices"))
    tokens = _json_list(m.get("clobTokenIds"))
    is_yes_no = outcomes is not None and [str(o).lower() for o in outcomes] == ["yes", "no"]
    outcome = None
    if prices is not None and len(prices) == 2:
        p = [_num(v) for v in prices]
        if p == [1.0, 0.0]:
            outcome = 1
        elif p == [0.0, 1.0]:
            outcome = 0
    resolved = m.get("umaResolutionStatus") == "resolved" and outcome is not None
    if event is None:
        events = m.get("events") or []
        event = events[0] if events else {}
    series = event.get("seriesSlug")
    if not series and isinstance(event.get("series"), list) and event["series"]:
        series = event["series"][0].get("slug")
    tag_src = m.get("tags") or event.get("tags") or []
    tags = [t.get("slug") for t in tag_src if isinstance(t, dict) and t.get("slug")]
    category = poly_category(tags)
    closed_ts = to_ts(m.get("closedTime"))
    end_ts = to_ts(m.get("endDate"))
    game_ts = to_ts(m.get("gameStartTime"))
    if game_ts is None and category == "sports":
        game_ts = to_ts(m.get("eventStartTime")) or to_ts(event.get("startTime"))
    cands = {"closed": closed_ts, "end": end_ts, "game_start": game_ts}
    cands = {k: v for k, v in cands.items() if v is not None}
    ref_source = min(cands, key=cands.get) if cands else None
    return {
        "venue": "polymarket",
        "market_id": m.get("conditionId") or str(m.get("id")),
        "gamma_id": str(m.get("id")),
        "event_id": str(event.get("id") or m.get("id")),
        "event_slug": event.get("slug"),
        "series": series or event.get("slug") or m.get("slug"),
        "category_raw": "|".join(tags),
        "category": category,
        "title": m.get("question"),
        "is_yes_no": is_yes_no,
        "resolved": resolved,
        "outcome": outcome if is_yes_no else None,
        "yes_token": (str(tokens[0]) if tokens and is_yes_no and len(tokens) == 2 else None),
        "neg_risk": bool(m.get("negRisk")),
        "open_ts": to_ts(m.get("startDate")),
        "closed_ts": closed_ts,
        "end_ts": end_ts,
        "game_start_ts": game_ts,
        "ref_ts": cands[ref_source] if ref_source else None,
        "ref_source": ref_source,
        "volume": _num(m.get("volumeNum")) if m.get("volumeNum") is not None
        else _num(m.get("volume")),
    }


# ----------------------------------------------------------------------------
# price series
# ----------------------------------------------------------------------------
def kalshi_trade_series(candles: list[dict]) -> list[tuple[float, float]]:
    """(candle end ts, last trade price) for hourly candles that had a trade.

    A Kalshi candle ending at ``end_period_ts`` covers the preceding period;
    ``price.close_dollars`` is the last trade in it and is absent when the
    period had no trade. Using the candle *end* time guarantees the trade
    happened at or before that time.
    """
    out = []
    for c in candles or []:
        price = c.get("price") or {}
        close = _num(price.get("close_dollars"))
        if close is None and price.get("close") is not None:  # cents (old shape)
            close = _num(price.get("close")) / 100.0
        vol = _num(c.get("volume_fp")) if c.get("volume_fp") is not None else _num(c.get("volume"))
        if close is None or not vol:
            continue
        out.append((float(c["end_period_ts"]), close))
    out.sort()
    return out


def kalshi_mid_series(candles: list[dict]) -> list[tuple[float, float]]:
    """(candle end ts, bid/ask midpoint at candle close) when both sides quoted."""
    out = []
    for c in candles or []:
        bid = _num((c.get("yes_bid") or {}).get("close_dollars"))
        ask = _num((c.get("yes_ask") or {}).get("close_dollars"))
        if bid is None or ask is None or ask <= bid or bid <= 0 or ask >= 1:
            continue
        out.append((float(c["end_period_ts"]), 0.5 * (bid + ask)))
    out.sort()
    return out


def poly_series(history: list[dict]) -> list[tuple[float, float]]:
    """(t, p) points of a CLOB /prices-history response."""
    out = []
    for h in history or []:
        t, p = _num(h.get("t")), _num(h.get("p"))
        if t is None or p is None:
            continue
        out.append((t, p))
    out.sort()
    return out


def price_at(series: list[tuple[float, float]], horizon_ts: float,
             max_staleness: float = MAX_STALENESS) -> tuple[float, float, str]:
    """Last observation at or before ``horizon_ts``.

    Returns (price, staleness_seconds, status) where status is
    'ok', 'stale' (last observation older than max_staleness; price is NaN but
    staleness is reported) or 'none' (no observation at or before horizon).
    """
    best = None
    for t, p in series:
        if t <= horizon_ts:
            best = (t, p)
        else:
            break
    if best is None:
        return math.nan, math.nan, "none"
    staleness = horizon_ts - best[0]
    if staleness > max_staleness:
        return math.nan, staleness, "stale"
    return best[1], staleness, "ok"


# ----------------------------------------------------------------------------
# study design: window, filters, sampling
# ----------------------------------------------------------------------------
WINDOW_START = to_ts("2026-08-25T00:00:00Z")   # Kalshi live API holds markets
WINDOW_END = to_ts("2026-10-22T00:00:00Z")     # settled after 2026-08-24
MIN_VOLUME = {"kalshi": 1000.0,       # contracts traded over the market's life
              "polymarket": 1000.0}   # USD notional traded (volumeNum)


def filter_cascade(df, venue: str):
    """Apply the venue's eligibility filters in order.

    Returns (eligible_df, steps) where steps is a list of
    {"step", "remaining", "removed"} dicts, starting from all listed markets.
    """
    steps = [{"step": "listed", "remaining": int(len(df)), "removed": 0}]

    def apply(d, mask, name):
        out = d[mask]
        steps.append({"step": name, "remaining": int(len(out)),
                      "removed": int(len(d) - len(out))})
        return out

    d = df
    if venue == "kalshi":
        d = apply(d, ~d["is_mve"].astype(bool), "not multivariate (MVE)")
        d = apply(d, d["market_type"] == "binary", "binary market_type")
        d = apply(d, d["status"].isin(["finalized", "settled"]) & d["outcome"].notna(),
                  "settled YES/NO (no scalar/void)")
        close = d["close_ts"]
    else:
        d = apply(d, d["is_yes_no"].astype(bool), "Yes/No outcomes")
        d = apply(d, d["resolved"].astype(bool), "UMA resolved to exactly 1/0")
        d = apply(d, d["yes_token"].notna(), "has YES token id")
        close = d["ref_ts"]
    d = apply(d, (close >= WINDOW_START) & (close < WINDOW_END),
              "close in 2026-08-25..2026-10-21")
    d = apply(d, d["volume"].fillna(0) >= MIN_VOLUME[venue],
              f"volume >= {MIN_VOLUME[venue]:g}")
    return d, steps


def stratified_sample(df, budget: int, per_event_cap: int, per_series_cap: int,
                      seed: int):
    """Sample markets by event (cluster) with caps, balancing categories.

    * at most ``per_event_cap`` markets per event (random subset),
    * at most ``per_series_cap`` markets per series,
    * the total budget is split across categories in proportion to the square
      root of each category's eligible count (unused quota is passed on),
    * within a category, events are taken in a seeded random order.
    Returns the sampled rows (a subset of df).
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    df = df.sort_values(["category", "series", "event_id", "market_id"]).reset_index(drop=True)
    counts = df.groupby("category").size()
    order = sorted(counts.index, key=lambda c: counts[c])   # small categories first
    weights = {c: math.sqrt(counts[c]) for c in order}
    remaining_budget, remaining_w = budget, sum(weights.values())
    chosen = []
    for cat in order:
        quota = int(round(remaining_budget * weights[cat] / remaining_w)) if remaining_w else 0
        sub = df[df["category"] == cat]
        events = np.array(sorted(sub["event_id"].unique()), dtype=object)
        rng.shuffle(events)
        by_event = {e: g for e, g in sub.groupby("event_id")}
        series_n: dict = {}
        taken = 0
        for e in events:
            if taken >= quota:
                break
            g = by_event[e]
            if len(g) > per_event_cap:
                g = g.iloc[np.sort(rng.choice(len(g), per_event_cap, replace=False))]
            s = g["series"].iloc[0]
            room = min(per_series_cap - series_n.get(s, 0), quota - taken)
            if room <= 0:
                continue
            g = g.iloc[:room]
            series_n[s] = series_n.get(s, 0) + len(g)
            taken += len(g)
            chosen.append(g)
        remaining_budget -= taken
        remaining_w -= weights[cat]
    return df.iloc[0:0] if not chosen else (
        __import__("pandas").concat(chosen).reset_index(drop=True))
