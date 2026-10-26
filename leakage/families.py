"""Contract families, grouped by how the answer becomes public.

The leakage map compares families, not single markets, so the one judgment
call in the whole analysis lives here, in a table you can read and override
(`--families-csv`). Assign families before looking at outcomes.

scheduled_reveal   The answer is fixed, or known to a few people, before a
                   scheduled public reveal: award winners, what a speech will
                   say, whether a named person shows up, a pre-recorded video,
                   a draft pick. With no leak, prices should barely move toward
                   the answer in the quiet hours before the reveal.
scheduled_data     Embargoed statistics and committee decisions (CPI, payrolls,
                   FOMC, box office). Few insiders, but public nowcasts also
                   move prices before release, legitimately.
continuous_public  The answer forms in public during the window: games in
                   progress, index and crypto levels, weather. Prices moving
                   toward the answer before close is information, not leakage.
elections          Public counts plus private internal polling.
other              Unmatched; reported but left out of the main contrast.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

FAMILIES = ("scheduled_reveal", "scheduled_data", "continuous_public",
            "elections", "other")

# (pattern on the series ticker with any leading "KX" removed, family, subfamily)
# Order matters: the first match wins, so specific patterns come first.
SERIES_RULES: list[tuple[str, str, str]] = [
    (r"MENTION|SAY", "scheduled_reveal", "mention"),
    (r"OSCAR|GRAMMY|EMMY|GOLDENGLOBE|TONY|NOBEL|BALLONDOR|HEISMAN|POY|"
     r"PERSONOFTHEYEAR|MVP|ROTY|CYYOUNG|AWARD", "scheduled_reveal", "award"),
    (r"DRAFT|NOMIN|APPOINT|CABINET|ANNOUNCE|VPPICK|SPOTIFY|BILLBOARD|"
     r"TOPSONG|YEARINSEARCH|GOOGLE|APPLE|NETFLIX|MRBEAST|YOUTUBE|VIDEO|SNL",
     "scheduled_reveal", "announcement"),
    (r"ATTEND|APPEAR|VISIT", "scheduled_reveal", "named_person"),
    (r"CEO|IPO|EARNINGS|LAYOFF|MERGER|ACQUI", "scheduled_reveal", "corporate"),
    (r"CPI|PCE|PPI|GDP|PAYROLL|NFP|JOBS|UNEMP|JOBLESS|CLAIMS|FED|FOMC|"
     r"RETAIL|ISM|BOXOFFICE|DELIVER", "scheduled_data", "release"),
    (r"PRES|SENATE|HOUSE|GOV|MAYOR|ELECT|PRIMARY|VOTE", "elections", "election"),
    (r"GAME|MATCH|SPREAD|TOTAL|FIGHT|RACE|SERIES|NFL|NBA|MLB|NHL|NCAA|UFC|ATP|"
     r"WTA|PGA|EPL|UCL|F1|NASCAR|WNBA|MLS", "continuous_public", "sports"),
    (r"^(BTC|ETH|SOL|XRP|DOGE|INX|NASDAQ|NDX|SPX|DOW|USD|EUR|JPY|TNOTE|GOLD|"
     r"OIL|WTI)|CRYPTO", "continuous_public", "price_level"),
    (r"^(HIGH|LOW|RAIN|SNOW|TEMP)|HURRICANE|WEATHER", "continuous_public", "weather"),
]

# Fallback on the event or market title when the series ticker says nothing.
TITLE_RULES: list[tuple[str, str, str]] = [
    (r"\bsay\b|\bmention|\bsaid\b", "scheduled_reveal", "mention"),
    (r"\bwin (the|best)\b|\baward\b|\bprize\b|person of the year", "scheduled_reveal", "award"),
    (r"\battend|\bappear|\bvisit", "scheduled_reveal", "named_person"),
    (r"\bannounce|\bnominee|\bnominate|\bpick\b|\bdraft", "scheduled_reveal", "announcement"),
    (r"\bcpi\b|inflation|payrolls|unemployment|\bgdp\b|\bfed\b|rate (cut|hike)", "scheduled_data", "release"),
    (r"\belection|\bprimary|\bvote", "elections", "election"),
    (r"\bvs\.?\b|\bgame\b|\bmatch\b|\bspread\b|\bfight\b", "continuous_public", "sports"),
    (r"bitcoin|ethereum|s&p|nasdaq|price of|close (above|below)", "continuous_public", "price_level"),
    (r"temperature|\brain\b|\bsnow\b|\bhigh\b in", "continuous_public", "weather"),
]

# Mention markets: is the text written in advance (and so known to staff)?
SCRIPTED = r"state of the union|address|inaugural|earnings call|prepared remarks|" \
           r"commencement|eulogy|\bspeech\b|monologue|saturday night live|\bsnl\b"
UNSCRIPTED = r"press conference|interview|podcast|debate|\brally\b|briefing|" \
             r"town hall|post-?game|q&a|\blive\b"


def strip_kx(series: str) -> str:
    s = series.upper() if isinstance(series, str) else ""
    return s[2:] if s.startswith("KX") else s


def series_of(ticker: str) -> str:
    """Kalshi tickers are SERIES-EVENT-MARKET; the series is the first field."""
    return (ticker or "").split("-")[0]


def classify(series: str, title: str = "", overrides: dict | None = None) -> tuple[str, str]:
    """(family, subfamily) for a series ticker, falling back to the title."""
    if overrides and series in overrides:
        return overrides[series]
    core = strip_kx(series)
    for pattern, family, sub in SERIES_RULES:
        if re.search(pattern, core):
            return family, sub
    text = title.lower() if isinstance(title, str) else ""
    for pattern, family, sub in TITLE_RULES:
        if re.search(pattern, text):
            return family, sub
    return "other", "other"


def script_type(title: str) -> str:
    """'scripted', 'unscripted' or 'unknown' for a mention-market event title."""
    text = title.lower() if isinstance(title, str) else ""
    s = re.search(SCRIPTED, text) is not None
    u = re.search(UNSCRIPTED, text) is not None
    if s and not u:
        return "scripted"
    if u and not s:
        return "unscripted"
    return "unknown"


def load_overrides(path: str | Path | None) -> dict:
    """CSV with columns series,family[,subfamily] -> {series: (family, sub)}."""
    if not path:
        return {}
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            fam = row["family"].strip()
            if fam not in FAMILIES:
                raise ValueError(f"unknown family {fam!r} for {row['series']}")
            out[row["series"].strip()] = (fam, (row.get("subfamily") or fam).strip())
    return out
