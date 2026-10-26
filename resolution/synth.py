"""Synthetic Polymarket-shaped markets with planted dispute drivers.

Writes the same files ``resolution.pull`` writes, so the whole pipeline (join,
labels, features, models, evaluation) runs end to end without network access:

* rules are built from a category template plus clauses. *Open* clauses leave
  a case undecided (a consensus of credible reporting, announcement language
  with a deadline, an undefined "deal"); *closing* clauses settle one (a named
  source, a time zone, a fallback, a definition).
* dispute log-odds = base + category + volume + event effect
  + ``text_effect`` x (open clauses - 0.6 x closing clauses).
  Categories differ in how many open clauses they use, so category alone
  predicts disputes too; the question is whether the words add to it.
* ``canary``: the share of disputed markets whose Gamma description gets a
  clarification appended after the fact, in one of six shapes ("Update (date):
  ...", a header paragraph with the text below it, an inline "Update 3/5/2026:",
  "Additional context:", "Clarification:", a bare date). Unstripped, it leaks
  the label into the text.
* disputed markets get ABI-encoded DisputePrice logs whose ancillary data
  hashes to the market's question id (neg-risk markets carry a different
  Gamma question id, so the join falls back to the listed text).
"""
from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import abi
from .keccak import keccak_hex

START = datetime(2024, 1, 1, tzinfo=timezone.utc)
ADAPTER = "0x157ce2d672854c848c9b79c49a8cc6cc89176a49"
NEG_RISK_ADAPTER = "0x2f5e3684cb1f318ec51b00edba38d79ac2c0aa9d"
BLOCK0, BLOCK_S = 52_000_000, 2.0
CHAINLINK_RESOLVER = "0x" + "c1" * 20  # stands in for an automated, non-UMA resolver

CATEGORIES = {
    #  name: (share, base effect, log10-volume mean, open-clause rate, closing rate,
    #         median horizon days, neg-risk group probability, Gamma tags)
    "geopolitics": (0.09, 0.6, 5.0, 1.6, 0.8, 45, 0.25, ["Geopolitics", "World"]),
    "politics": (0.13, 0.4, 4.9, 1.3, 0.9, 40, 0.20, ["Politics"]),
    "elections": (0.07, 0.2, 5.1, 0.6, 1.4, 60, 0.80, ["Elections", "Politics"]),
    "business": (0.08, 0.3, 4.5, 1.2, 1.0, 50, 0.15, ["Business", "Tech"]),
    "mentions": (0.04, 0.5, 4.3, 1.4, 0.6, 3, 0.70, ["Mentions"]),
    "culture": (0.07, 0.0, 4.4, 0.9, 1.0, 20, 0.50, ["Pop Culture"]),
    "economy": (0.07, -0.3, 4.8, 0.5, 1.8, 25, 0.40, ["Economy"]),
    "crypto": (0.18, -0.4, 4.5, 0.4, 1.9, 5, 0.10, ["Crypto"]),
    "sports": (0.27, -0.6, 4.6, 0.3, 1.6, 2, 0.10, ["Sports"]),
}
NAMES = {  # invented names, so no generated market reads as a real one
    "country": ["Aldoria", "Brevia", "Calvera", "Dornia", "Estara", "Feldmark", "Galvany",
                "Hollen", "Irvana", "Jessar", "Kalmora", "Lusora", "Marovia", "Nerath"],
    "person": ["the President", "the Prime Minister", "the Fed Chair", "the Speaker",
               "the Secretary of State", "the CEO", "the Governor", "the Chancellor"],
    "company": ["Halcyon Labs", "Kestrel Motors", "Orbital Nine", "Pinecrest Capital",
                "Quanta Retail", "Redwood AI", "Sablewood", "Tidewater Energy", "Umbra Systems",
                "Vantage Air", "Wexford Media", "Yarrow Bio"],
    "coin": ["Aurum", "Nimbus", "Corvid", "Lumen", "Zephyr", "Quill"],
    "team": ["Harbor Hawks", "Ridge Runners", "Bay Comets", "Iron Owls", "Delta Foxes",
             "Summit Bears", "Coast Pilots", "River Kings", "Canyon Wolves", "Metro Lynx",
             "Prairie Storm", "Lake Herons"],
    "movie": ["The Long Night", "Starfall", "Paper Kings", "Blue Harbor", "Iron Valley"],
    "artist": ["Nova Ray", "The Wilders", "Kai Monroe", "Luna Park", "Atlas Bloom"],
    "office": ["governor", "mayor", "senator", "president"],
    "place": ["North Province", "Westmark", "Lakeshire", "Port Avery", "Greenvale",
              "Stonebridge", "Clearwater", "Highland"],
    "word": ["tariff", "crypto", "border", "inflation", "jobs", "deal", "weird", "historic"],
    "event_name": ["the State of the Union", "the press conference", "the rally", "the debate",
                   "the earnings call", "the interview"],
    "indicator": ["CPI", "core PCE", "unemployment", "GDP growth"],
}
TITLES = {
    "geopolitics": ["Will {country} and {country2} sign a peace deal by {date}?",
                    "{country} x {country2} ceasefire by {date}?",
                    "Will {country} strike {country2} by {date}?",
                    "Will {country} and {country2} agree to a permanent truce by {date}?"],
    "politics": ["Will {person} be out by {date}?", "Will {person} resign by {date}?",
                 "Will {person} sign the bill by {date}?", "Will {person} meet with {person2} by {date}?"],
    "elections": ["Will {option} win the {place} {office} election?"],
    "business": ["Will {company} sell its {asset} by {date}?",
                 "Will {company} announce a merger by {date}?",
                 "Will {company} launch {product} by {date}?"],
    "mentions": ["Will {person} say \"{word}\" during {event_name}?"],
    "culture": ["Will {movie} gross over ${num}M on opening weekend?",
                "Will {artist} release a new album by {date}?"],
    "economy": ["Will {indicator} be above {pct}% in {month}?",
                "Will the Fed cut rates at the {month} meeting?"],
    "crypto": ["Will {coin} reach ${num},000 by {date}?", "{coin} above ${num},000 on {date}?"],
    "sports": ["Will the {team} beat the {team2}?", "{team} vs. {team2}: who will win?"],
}
BASE_RULES = {
    "geopolitics": "This market will resolve to \"Yes\" if {country} and {country2} reach the "
                   "outcome in the title by {date}. Otherwise, this market will resolve to \"No\".",
    "politics": "This market will resolve to \"Yes\" if {person} does what the title describes "
                "by {date}. Otherwise, this market will resolve to \"No\".",
    "elections": "This market will resolve to \"Yes\" if {option} wins the {place} {office} "
                 "election. Otherwise, this market will resolve to \"No\".",
    "business": "This market will resolve to \"Yes\" if {company} does what the title describes "
                "by {date}. Otherwise, this market will resolve to \"No\".",
    "mentions": "This market will resolve to \"Yes\" if {person} says \"{word}\" during "
                "{event_name}. Otherwise, this market will resolve to \"No\".",
    "culture": "This market will resolve according to the outcome described in the title. "
               "Otherwise, this market will resolve to \"No\".",
    "economy": "This market will resolve according to the {indicator} figure for {month}. "
               "Otherwise, this market will resolve to \"No\".",
    "crypto": "This market will resolve to \"Yes\" if {coin} trades at or above the price in "
              "the title by {date}. Otherwise, this market will resolve to \"No\".",
    "sports": "This market will resolve to \"Yes\" if the {team} win the game. Otherwise, this "
              "market will resolve to \"No\".",
}
OPEN_CLAUSES = [
    "The resolution source for this market will be a consensus of credible reporting.",
    "This market will resolve based on credible reporting from major news outlets.",
    "An official announcement by either party will suffice.",
    "This market will resolve based on public announcements made by the parties involved.",
    "A deal between the parties is sufficient.",
    "Any military action against the other party will resolve this market.",
    "Only a significant change in control of the territory is relevant.",
    "Edge cases will be resolved in the spirit of this market.",
    "Reports from either government will be weighed.",
    "Statements by senior officials may be taken into account.",
]
CLOSING_CLAUSES = [
    "The deadline is {date}, 11:59 PM ET.",
    "The primary resolution source will be the official website of the organizer.",
    "Resolution will be based on data published by Reuters or the Associated Press.",
    "If the event is postponed or cancelled, this market will resolve to \"No\".",
    "If the resolution source is unavailable, the market may resolve 50-50.",
    "For the purposes of this market, a signed written agreement will count; statements of "
    "intent will not count.",
    "Prices will be taken from the 1-minute candle closing price on Binance.",
    "The event must occur on or before the deadline; announcements after the deadline count "
    "only if they show it occurred before it.",
]
NEUTRAL_NOTES = [
    "Note: this market is part of a series.",
    "Note: the title is a summary; these rules govern.",
]
CANARY = ["Following questions about how this market resolves, a signed framework will count.",
          "Due to ambiguity in the phrase used above, only official statements will be used.",
          "After review, announcements made after the deadline will not count."]
# the shapes clarifications take when appended to the rules
CANARY_FORMATS = ["\n\nUpdate ({stamp}): {text}", "\n\nUpdate ({stamp}):\n\n{text}",
                  " Update {mdy}: {text}", "\nAdditional context: {text}",
                  "\n\nClarification: {text}", "\n\n{long}: {text}"]


@dataclass
class Spec:
    n_events: int = 1500
    seed: int = 0
    text_effect: float = 0.9
    vol_effect: float = 0.5
    base: float = -4.0
    canary: float = 0.0
    canary_fp: float = 0.003
    end: datetime = datetime(2026, 9, 20, tzinfo=timezone.utc)
    data_end: datetime = datetime(2026, 10, 20, tzinfo=timezone.utc)
    escalate: float = 0.25
    foreign_logs: int = 30
    note: str = field(default="")


def _seed(*parts) -> int:
    return zlib.crc32("|".join(map(str, parts)).encode())


def _fill(rng, tpl: str, slots: dict) -> str:
    return tpl.format(**slots)


def _block(t: datetime) -> int:
    return BLOCK0 + int((t - START).total_seconds() / BLOCK_S)


def generate(spec: Spec, out: Path) -> dict:
    """Write a synthetic data folder; return a summary of what was planted."""
    rng = np.random.default_rng(_seed("resolution-synth", spec.seed))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cats = list(CATEGORIES)
    shares = np.array([CATEGORIES[c][0] for c in cats])
    gamma, api, apiq, logs = [], [], [], []
    span = (spec.end - START).total_seconds()
    mid = 0
    n_disputed = n_canary = 0
    seen_q: set[str] = set()
    for e in range(spec.n_events):
        cat = cats[rng.choice(len(cats), p=shares / shares.sum())]
        _, c_eff, v_mu, open_rate, close_rate, hz, p_group, tags = CATEGORIES[cat]
        created = START + timedelta(seconds=float(rng.random() * span))
        horizon = max(0.2, float(rng.lognormal(np.log(hz), 0.6)))
        end = created + timedelta(days=horizon)
        date_s = end.strftime("%B %-d, %Y")
        slots = {k: v[rng.integers(len(v))] for k, v in NAMES.items()}
        for key in ("country", "person", "team"):  # the second party, fixed for the event
            others = [x for x in NAMES[key] if x != slots[key]]
            slots[key + "2"] = others[rng.integers(len(others))]
        slots.update(date=date_s, month=end.strftime("%B"), num=int(rng.integers(2, 200)),
                     pct=round(float(rng.uniform(1, 5)), 1), asset="bitcoin holdings",
                     product="a new model")
        group = rng.random() < p_group
        options = (list(rng.choice(["Ana Ortiz", "Ben Cole", "Chen Li", "Dara Singh", "Eli Brooks",
                                    "Fay Moreau", "Gus Ibarra"], size=int(rng.integers(2, 6)),
                                   replace=False)) if group else [None])
        title_tpl = TITLES[cat][rng.integers(len(TITLES[cat]))]
        n_open = int(rng.poisson(open_rate))
        n_close = int(rng.poisson(close_rate))
        clauses = ([OPEN_CLAUSES[i] for i in rng.choice(len(OPEN_CLAUSES), size=min(n_open, 6),
                                                        replace=False)] +
                   [CLOSING_CLAUSES[i] for i in rng.choice(len(CLOSING_CLAUSES),
                                                           size=min(n_close, 6), replace=False)])
        rng.shuffle(clauses)
        if rng.random() < 0.2:
            clauses.append(NEUTRAL_NOTES[rng.integers(len(NEUTRAL_NOTES))])
        event_effect = float(rng.normal(0, 0.6))
        series = f"{cat}-weekly-{slots['coin' if cat == 'crypto' else 'team'].lower()}" \
            if cat in ("crypto", "sports") and rng.random() < 0.4 else None
        chainlink = cat == "crypto" and rng.random() < 0.3
        log_vol_event = float(rng.normal(v_mu, 0.55))
        for opt in options:
            mid += 1
            s = dict(slots, option=opt or slots["person"])
            title = _fill(rng, title_tpl, s)
            rules = " ".join([_fill(rng, BASE_RULES[cat], s)] +
                             [c.format(date=date_s) for c in clauses])
            if opt and "{option}" not in title_tpl:
                title = f"{title} [{opt}]"
                rules += f' This market refers to the outcome "{opt}".'
            vol = 10 ** (log_vol_event + float(rng.normal(0, 0.35)) - (0.3 if opt else 0))
            text_term = spec.text_effect * (min(n_open, 6) - 0.6 * min(n_close, 6))
            logit = (spec.base + c_eff + spec.vol_effect * (np.log10(vol) - 4.5)
                     + event_effect + text_term)
            disputed = bool((not chainlink) and rng.random() < 1 / (1 + np.exp(-logit)))
            escalated = bool(disputed and rng.random() < spec.escalate)
            yes = rng.random() < 0.4
            closed = end + timedelta(days=float(rng.exponential(1.0)) +
                                     (float(rng.uniform(2, 6)) if disputed else 0) +
                                     (float(rng.uniform(3, 8)) if escalated else 0))
            description = rules
            updated = False
            if (disputed and rng.random() < spec.canary) or \
                    (not disputed and rng.random() < spec.canary_fp):
                when = closed - timedelta(days=1)
                fmt = CANARY_FORMATS[rng.integers(len(CANARY_FORMATS))]
                description += fmt.format(stamp=when.strftime("%b %-d, %Y"),
                                          mdy=when.strftime("%-m/%-d/%Y"),
                                          long=when.strftime("%B %-d, %Y"),
                                          text=CANARY[rng.integers(len(CANARY))])
                updated = True
                n_canary += disputed
            n_disputed += disputed
            adapter = NEG_RISK_ADAPTER if group else ADAPTER
            anc = abi.ancillary_for(title, rules, adapter)
            qid = keccak_hex(anc)
            if qid in seen_q:  # the adapter refuses a question it has seen; so do we
                rules += f" Market reference {mid}."
                description = description.replace(rules.rsplit(" Market reference", 1)[0],
                                                  rules, 1)
                anc = abi.ancillary_for(title, rules, adapter)
                qid = keccak_hex(anc)
            seen_q.add(qid)
            gamma_qid = keccak_hex(b"neg-risk:" + anc) if group else qid
            cond = abi.condition_id(adapter, qid)
            statuses = (["proposed", "challenged", "reproposed"] +
                        (["disputed"] if escalated else []) + ["resolved"]) if disputed \
                else ["proposed", "resolved"]
            gamma.append({
                "id": str(100000 + mid), "question": title, "conditionId": cond,
                "questionID": gamma_qid, "slug": f"m-{mid}", "description": description,
                "resolutionSource": "", "category": None,
                "outcomes": json.dumps(["Yes", "No"]),
                "outcomePrices": json.dumps(["1", "0"] if yes else ["0", "1"]),
                "startDate": created.isoformat(), "createdAt": created.isoformat(),
                "endDate": end.isoformat(), "closedTime": closed.isoformat(),
                "umaEndDate": None, "updatedAt": closed.isoformat(),
                "volumeNum": round(vol, 2), "liquidityNum": round(vol / 20, 2),
                "umaBond": "500", "umaReward": "5", "customLiveness": 0,
                "resolvedBy": CHAINLINK_RESOLVER if chainlink else adapter,
                "umaResolutionStatus": "resolved",
                "umaResolutionStatuses": json.dumps(statuses if not chainlink else []),
                "automaticallyResolved": chainlink, "marketType": "normal", "formatType": None,
                "groupItemTitle": opt, "negRiskOther": False, "sportsMarketType": None,
                "gameId": None, "closed": True, "archived": False, "tags": tags,
                "events": [{"id": str(9000 + e), "slug": f"e-{e}", "title": title,
                            "negRisk": bool(group), "negRiskMarketID": None,
                            "series": [series] if series else [], "tags": []}],
            })
            api.append({"condition_id": cond, "status": "resolved",
                        "reporter": "CHAINLINK" if chainlink else "UMA_OO",
                        "market_type": "INCREMENTAL_NEGRISK" if group else "BINARY",
                        "was_disputed": bool(disputed), "was_arbitrated": bool(escalated),
                        "new_version_q": bool(updated), "price": "1" if yes else "0",
                        "resolved_at": closed.isoformat(), "extended_review": False,
                        "log_index": "0", "transaction_hash": "",
                        "last_update_timestamp": closed.isoformat()})
            if disputed:
                overturn = rng.random() < 0.5
                first = (1 if yes else 0) if not overturn else (0 if yes else 1)
                apiq.append({"_question_id": gamma_qid, "proposed_price": str(first),
                             "reproposed_price": str(1 if yes else 0),
                             "price": "1" if yes else "0", "was_disputed": True})
                t1 = end + timedelta(hours=float(rng.uniform(2, 30)))
                for k in range(2 if escalated else 1):
                    tk = t1 + timedelta(days=k * float(rng.uniform(0.5, 2)))
                    logs.append(abi.encode_dispute_log(
                        requester=adapter, proposer="0x" + "1" * 40, disputer="0x" + "2" * 40,
                        ancillary=anc, proposed_price=(first if k == 0 else (1 if yes else 0))
                        * abi.ONE, request_timestamp=int(created.timestamp()),
                        block=_block(tk), log_index=k))
    for k in range(spec.foreign_logs):
        t = START + timedelta(seconds=float(rng.random() * span))
        logs.append(abi.encode_dispute_log(
            requester="0x" + "9" * 40, proposer="0x" + "1" * 40, disputer="0x" + "2" * 40,
            ancillary=f"q: title: Other protocol question {k}, description: n/a".encode(),
            proposed_price=abi.ONE, request_timestamp=int(t.timestamp()), block=_block(t),
            log_index=k))
    logs.sort(key=lambda x: int(x["blockNumber"], 16))

    def dump(name, rows):
        with (out / name).open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    dump("gamma_markets.jsonl", gamma)
    dump("resolutions.jsonl", api)
    dump("resolutions_q.jsonl", apiq)
    dump("dispute_logs.jsonl", [abi.decode_dispute_log(x) for x in logs])
    last = _block(spec.data_end)
    (out / "chain_state.json").write_text(json.dumps(
        {"from_block": BLOCK0, "to_block": last, "next_block": last + 1, "done": True}))
    anchors = {str(BLOCK0 + (last - BLOCK0) * k // 40):
               int((START + timedelta(seconds=(last - BLOCK0) * k // 40 * BLOCK_S)).timestamp())
               for k in range(41)}
    (out / "block_anchors.json").write_text(json.dumps(anchors))
    (out / "gamma_state.json").write_text(json.dumps(
        {"done": True, "count": len(gamma), "pulled_at": spec.data_end.isoformat()}))
    summary = {"markets": len(gamma), "events": spec.n_events, "disputed": n_disputed,
               "canary_updates_on_disputed": n_canary, "dispute_logs": len(logs),
               "spec": {k: (v.isoformat() if isinstance(v, datetime) else v)
                        for k, v in spec.__dict__.items()}}
    (out / "synth_summary.json").write_text(json.dumps(summary, indent=1))
    return summary
