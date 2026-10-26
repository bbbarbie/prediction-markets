"""Lint market rules for the open questions that turn into disputes.

    python3 -m resolution.lint --examples
    python3 -m resolution.lint --title "Will A and B sign a peace deal by March 31?" \\
        --rules-file rules.txt [--model resolution/report/model.pkl] [--json]
    pbpaste | python3 -m resolution.lint --title "..."

Each check names a case the rules leave undecided, shows the words that
triggered it and suggests the sentence that would close it. With ``--model``
(written by ``resolution.run``), it also prints the model's dispute risk and
its percentile among the markets the model was trained on, plus the words that
pushed the score up most. The checks are deliberately simple regular
expressions: they are meant to be read and argued with, and the evaluation in
``resolution.run`` measures how much each one is worth.
"""
from __future__ import annotations

import argparse
import json
import pickle
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import text as T

EXAMPLES = Path(__file__).parent / "examples"


@dataclass(frozen=True)
class Check:
    flag: str
    title: str
    why: str
    fix: str
    evidence: tuple = ()
    severity: str = "high"


CHECKS = [
    Check("flag_event_vs_announcement", "Event or announcement?",
          "The rules use announce/confirm/report language and a deadline but do not say whether "
          "the event, the news of it, or both must land before the deadline. When a sale happens "
          "inside the window and the filing that reveals it comes after, both sides have a case.",
          "Say which date governs, e.g. \"The event must occur by <deadline> ET. Confirmation "
          "published up to <N> days later counts if it shows the event occurred by the deadline.\"",
          ("announcement", "_DEADLINE")),
    Check("flag_consensus_undefined", "Whose reporting decides?",
          "\"A consensus of credible reporting\" leaves open which outlets count, how many must "
          "agree, and what happens when they disagree or report a claim rather than a fact.",
          "Name the sources and the rule, e.g. \"at least two of AP, Reuters and Bloomberg "
          "report it as fact; official statements by either government are sufficient\".",
          ("consensus_source",)),
    Check("flag_undefined_term", "Key term not defined",
          "Words like deal, agreement, ceasefire, permanent, control or similar carry the whole "
          "market and the rules never say what qualifies (signed text? announced framework? "
          "a pause in fighting? which solutions are similar enough?).",
          "Add a definition with one example on each side, e.g. \"A signed written agreement "
          "counts; a framework, memorandum or statement of intent does not.\"",
          ("vague_state",)),
    Check("flag_mention_undefined", "What counts as saying it?",
          "Mention markets turn on plurals, compound words, quoting someone else, and whether a "
          "pre-recorded or deleted remark counts.",
          "List what counts: \"Plural and possessive forms count; compound words do not; the "
          "word must be spoken by <person>, live, during <event>.\"",
          ("say_mention",)),
    Check("flag_legislative_stage", "Passed, signed or in effect?",
          "The rules turn on a bill, law or regulation but do not say which stage counts: "
          "passage by one chamber or both, signature, or taking effect, and whether an agency "
          "reinterpretation or a court ruling counts.",
          "Name the stage and where to check it, e.g. \"The bill must be signed into law by "
          "<date>, 11:59 PM ET, as shown on <official legislative site>; passage without a "
          "signature does not count.\"", ("_LEGIS",)),
    Check("flag_threshold_unmeasured", "Which number, measured how?",
          "A threshold without a measurement rule leaves open intraday vs. close, the venue or "
          "feed, rounding, and whether first prints or revisions count.",
          "Fix the measurement, e.g. \"the 1-minute candle close on <venue> at <time> ET; the "
          "first release counts and later revisions do not\".",
          ("threshold",), "medium"),
    Check("flag_no_timezone", "Deadline without a time zone",
          "A date without a time and zone moves the deadline by up to a day for events near "
          "midnight.",
          "Write the deadline as \"<date>, 11:59 PM ET\".", ("_DEADLINE",), "medium"),
    Check("flag_no_source", "No named resolution source",
          "Without a named primary source, the resolver chooses one after the fact.",
          "Name a primary source and a fallback for when it is unavailable.", (), "medium"),
    Check("flag_no_fallback", "No fallback",
          "Nothing says what happens if the event is postponed or cancelled or the source stops "
          "publishing.",
          "Add: \"If <event> is postponed past <deadline> or cancelled, this market resolves "
          "\"No\"; if <source> is unavailable, <fallback source> is used.\"", (), "low"),
    Check("flag_degree_words", "Degree words without a threshold",
          "Significant, substantial, major and effectively are judgment calls.",
          "Replace each with a measurable threshold.", ("degree",), "low"),
    Check("flag_subjective", "Left to the resolver's judgment",
          "\"Spirit of the market\", intent and discretion invite argument about the judgment.",
          "Replace with the rule the judgment would apply.", ("subjective",), "low"),
]


def _evidence(text: str, keys: tuple, limit: int = 2) -> list[str]:
    """One snippet per pattern family, skipping repeats of the same words."""
    out, words, starts = [], set(), []
    for key in keys:
        rx = {"_DEADLINE": T._DEADLINE, "_LEGIS": T._LEGIS}.get(key) or T.LEXICON[key]
        for m in rx.finditer(text):
            w = m.group(0).lower()
            if w in words or any(abs(m.start() - s) < 60 for s in starts):
                continue
            words.add(w)
            starts.append(m.start())
            a, b = max(0, m.start() - 35), min(len(text), m.end() + 35)
            snippet = re.sub(r"\s+", " ", text[a:b]).strip()
            out.append(("…" if a else "") + snippet + ("…" if b < len(text) else ""))
            break
    return out[:limit]


def lint(title: str, rules: str) -> list[dict]:
    rules, _ = T.strip_post_listing(rules)
    flags = T.flags(title, rules)
    if flags["flag_consensus_undefined"]:  # "whose reporting decides" already says it
        flags["flag_no_source"] = False
    full = f"{title}\n{rules}"
    return [{"check": c.flag.removeprefix("flag_"), "title": c.title, "severity": c.severity,
             "why": c.why, "fix": c.fix, "evidence": _evidence(full, c.evidence)}
            for c in CHECKS if flags[c.flag]]


READABLE = {
    "lex_consensus_source": "consensus-of-reporting phrases", "lex_announcement":
    "announce/confirm language", "lex_vague_state": "words like deal or ceasefire",
    "lex_degree": "degree words", "lex_subjective": "judgment words",
    "lex_say_mention": "say/mention words", "lex_fallback": "fallback clauses",
    "lex_definition": "definition clauses", "lex_timezone": "time zones",
    "lex_clock_time": "clock times", "lex_named_source": "named sources",
    "lex_measurement": "measurement rules", "lex_threshold": "thresholds",
    "log_words": "rules length", "log_title_words": "title length", "sentences": "sentences",
    "conditions_per_100w": "if/unless clauses", "andor_per_100w": "and/or density",
    "numbers_per_100w": "numbers", "has_url": "a URL", "has_deadline": "a deadline",
    "log_horizon_days": "time to the deadline", "neg_risk": "being one outcome of a group",
    "named_outcomes": "named outcomes",
    "log_uma_bond": "UMA bond", "log_uma_reward": "UMA reward",
    "custom_liveness": "custom liveness", "hist_rate": "the template's dispute history",
    "hist_n": "the template's track record", "log_volume": "volume",
}


COMPARATIVE = {
    "log_words": ("longer rules than usual", "shorter rules than usual"),
    "log_title_words": ("a longer title than usual", "a shorter title than usual"),
    "log_horizon_days": ("a longer time to the deadline", "a shorter time to the deadline"),
    "log_uma_bond": ("a higher UMA bond", "a lower UMA bond"),
    "log_uma_reward": ("a higher UMA reward", "a lower UMA reward"),
    "log_volume": ("higher volume", "lower volume"),
}


def describe(name: str, x: float) -> str:
    """Plain words for one positive contribution to the score."""
    if name.startswith('"'):
        return f"the words {name}"
    if name.startswith("category="):
        return f"category {name.split('=', 1)[1]}"
    if name.startswith("flag_"):
        return "check: " + next((c.title for c in CHECKS if c.flag == name), name)
    if name in COMPARATIVE:
        return COMPARATIVE[name][0 if x > 0 else 1]
    label = READABLE.get(name, name)
    if label.startswith(("a ", "being ", "the ")):
        return label if x > 0 else f"not {label}" if label.startswith("being") else f"no {label[2:]}" \
            if label.startswith("a ") else f"weak {label[4:]}"
    return f"more {label} than usual" if x > 0 else f"fewer {label} than usual"


def ordinal(n: float) -> str:
    k = int(round(n))
    suffix = "th" if 10 <= k % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
    return f"{k}{suffix}"


def load_model(path: Path) -> dict:
    with Path(path).open("rb") as f:
        return pickle.load(f)


def score(bundle: dict, title: str, rules: str, *, category: str | None = None,
          horizon_days: float = 30.0, group_size: int = 1) -> dict:
    from . import model as M
    rules, _ = T.strip_post_listing(rules)
    now = pd.Timestamp("2026-01-01", tz="UTC")
    row = pd.DataFrame([{
        "question": title, "rules": rules,
        "category_name": category or T.category_of([], None, f"{title} {rules}"),
        "created": now, "end": now + pd.Timedelta(days=horizon_days), "neg_risk": group_size > 1,
        "outcome_list": ["Yes", "No"], "volume": 0.0,
        "umaBond": bundle["meta"].get("median_bond", 0), "umaReward":
            bundle["meta"].get("median_reward", 0), "customLiveness": 0,
    }])
    row = M.prepare(row)
    for col in M.HISTORY:
        row[col] = bundle["meta"].get(f"median_{col}", 0.0)
    m = bundle["model"]
    p = float(m.predict(row)[0])
    ref = np.asarray(bundle.get("ref_scores", bundle.get("train_scores")))
    return {"risk": p, "percentile": float((ref <= p).mean() * 100),
            "reference": bundle["meta"].get("reference", "training markets"),
            "base_rate": bundle["meta"]["train_rate"], "model": bundle["meta"]["name"],
            "trained_through": bundle["meta"]["split"],
            "top_terms": [(describe(n, x), round(v, 3)) for n, v, x in
                          m.contributions(row, top=5)[0]],
            "category": row["category_name"].iloc[0]}


def render(title: str, findings: list[dict], risk: dict | None = None) -> str:
    lines = [f"Rules lint: {title!r}"]
    if risk:
        lines.append(f"Dispute risk {risk['risk']:.1%}: {ordinal(risk['percentile'])} percentile "
                     f"of {risk['reference']} ({risk['model']} trained on markets closed before "
                     f"{risk['trained_through']}; training base rate {risk['base_rate']:.1%}; "
                     f"category: {risk['category']})")
        if risk["top_terms"]:
            lines.append("  pushed up by: " + ", ".join(f"{n} (+{v:.2f})"
                                                       for n, v in risk["top_terms"]))
    if not findings:
        lines.append("No open questions found by the checks.")
    else:
        lines.append(f"{len(findings)} open question{'s' if len(findings) > 1 else ''}:")
    for i, f in enumerate(findings, 1):
        lines.append(f" {i}. [{f['severity']}] {f['title']}")
        for e in f["evidence"]:
            lines.append(f"      > {e}")
        lines.append(f"    Why: {f['why']}")
        lines.append(f"    Fix: {f['fix']}")
    return "\n".join(lines)


def read_example(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8")
    head, _, body = raw.partition("\n\n")
    return head.removeprefix("Title:").strip(), body.strip()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Lint prediction-market rules.")
    ap.add_argument("--title", default="")
    ap.add_argument("--rules", default=None, help="rules text (or use --rules-file / stdin)")
    ap.add_argument("--rules-file", type=Path)
    ap.add_argument("--model", type=Path, help="model.pkl written by resolution.run")
    ap.add_argument("--category", default=None, choices=T.CATEGORIES)
    ap.add_argument("--horizon-days", type=float, default=30.0)
    ap.add_argument("--group-size", type=int, default=1)
    ap.add_argument("--examples", action="store_true", help="lint resolution/examples/*.txt")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    bundle = load_model(args.model) if args.model else None
    if args.examples:
        items = [read_example(p) for p in sorted(EXAMPLES.glob("*.txt"))]
    else:
        rules = args.rules if args.rules is not None else (
            args.rules_file.read_text(encoding="utf-8") if args.rules_file else sys.stdin.read())
        items = [(args.title, rules)]
    results = []
    for title, rules in items:
        findings = lint(title, rules)
        risk = score(bundle, title, rules, category=args.category,
                     horizon_days=args.horizon_days, group_size=args.group_size) if bundle else None
        results.append({"title": title, "findings": findings, "risk": risk})
        if not args.json:
            print(render(title, findings, risk) + "\n")
    if args.json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=1))


if __name__ == "__main__":
    main()
