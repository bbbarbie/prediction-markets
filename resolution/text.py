"""Rule-text features: what a market's rules say at listing, and what they leave open.

Everything here reads only the question and the rules text, so it can score a
market before it lists. Gamma serves the *current* rules, and Polymarket adds
clarifications to some markets after they list (often the disputed ones), so
``strip_post_listing`` removes update and clarification paragraphs first; the
data audit checks how much it removed and compares the result with the
on-chain listing text where that exists.
"""
from __future__ import annotations

import math
import re

_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
          r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")

# Text added after listing: "Update (Mar 3, 2026): ...", "Update 3/5/2026: ...",
# "Clarification: ...", "EDIT - ...", "Additional context: ...", or a line that opens with
# a date stamp. Clarifications are appended, so everything from the first marker on is
# dropped: a header paragraph and the paragraphs under it go together. A marker needs
# a colon or dash after the word (and an optional date), so a sentence such as
# "Updates made by the question creator ..." is not one.
_DATE = (rf"(?:\(?[^)\n]{{0,40}}\)|\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?|\d{{4}}-\d{{2}}-\d{{2}}|"
         rf"{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?)")
_HEAD = (r"(?:update[sd]?|clarification|clarified|edit(?:ed)?|additional context|"
         r"note from polymarket|polymarket note|correction|amendment)")
_POST_MARK = re.compile(
    rf"(?:^|(?<=[.!?\]\)])[ \t]+)[\*\(\[_#]*[ \t]*{_HEAD}\b[ \t]*(?:{_DATE})?[ \t]*[\*\)\]]*[ \t]*"
    r"[:\-\u2013\u2014]", re.I | re.M)
_DATE_LINE = re.compile(
    rf"^[ \t]*[\*\(\[]*[ \t]*(?:{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}|"
    r"\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})[ \t]*[\)\]\*]*[ \t]*[:\-\u2013\u2014]",
    re.I | re.M)


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def strip_post_listing(text: str | None) -> tuple[str, int]:
    """Cut the rules at the first post-listing marker; return (text, characters removed).

    Characters are counted after collapsing whitespace, so tidying blank lines
    does not count as removed text.
    """
    if not isinstance(text, str) or not text.strip():
        return "", 0
    cuts = [m.start() for rx in (_POST_MARK, _DATE_LINE) for m in [rx.search(text)] if m]
    out = text[: min(cuts)] if cuts else text
    out = re.sub(r"\n\s*\n+", "\n\n", out).strip()
    return out, max(0, len(_squash(text)) - len(_squash(out)))


def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


# Phrase families. Directions are not assumed here; the model learns weights,
# and PREREGISTRATION.md states the four directions tested.
LEXICON: dict[str, re.Pattern] = {
    # who decides: an undefined crowd of sources
    "consensus_source": _rx(r"consensus of (?:credible )?report\w*", r"credible report\w*",
                            r"widely reported", r"reputable (?:news )?(?:sources?|outlets?|media)",
                            r"major (?:news )?(?:media|outlets?|news organi[sz]ations?)",
                            r"multiple (?:credible |reputable |independent )?(?:sources|outlets|reports)"),
    # the event versus the news of the event
    "announcement": _rx(r"\bannounce\w*", r"\bconfirm\w*", r"\bdisclos\w+",
                        r"publicly (?:state|report|acknowledg|declar)\w*",
                        r"officially (?:report|state|declare|disclose|acknowledge)\w*",
                        r"\bfil(?:e|es|ed|ing) (?:an? |its )?(?:8-k|10-q|10-k|form\b)"),
    # states of the world that need a definition
    "vague_state": _rx(r"\bagreement", r"\bdeal\b", r"cease-?fire", r"\btruce", r"\bpeace\b",
                       r"\bpermanent\w*", r"\binva(?:de|des|ded|sion)\b",
                       r"military (?:action|operation|strike|offensive)s?", r"\bstrikes?\b",
                       r"\battack\w*", r"control (?:of|over)\b", r"\bcaptur\w+", r"\bseiz\w+",
                       r"\bbann?(?:ed|s)?\b", r"\bout as\b", r"\bresign\w*", r"step(?:s|ped)? down",
                       r"removed? from office", r"\bimpeach\w*", r"\bacqui(?:re|res|red|sition)\b",
                       r"\bmerg(?:e|er|es|ed)\b", r"\blaunch\w*", r"\brelease[sd]?\b",
                       r"meet(?:s|ing)? with", r"\bnegotiat\w+", r"\brecogni[sz]\w+",
                       r"\bnormali[sz]\w+", r"\bsanction\w*", r"\bsimilar\b", r"\bequivalent\b",
                       r"\bcomparable\b", r"substantially the same"),
    "degree": _rx(r"\bsignificant\w*", r"\bsubstantial\w*", r"\bmajor\b", r"\bmajority\b",
                  r"\blargely\b", r"\beffectively\b", r"\bformally\b", r"\bmaterial(?:ly)?\b",
                  r"\bmeaningful\w*", r"\bwidespread\b", r"large[- ]scale", r"full[- ]scale"),
    "subjective": _rx(r"spirit of (?:the|this) market", r"\bintent(?:ion)? of\b", r"\breasonabl\w+",
                      r"\bclearly\b", r"\bunambiguous\w*", r"\bdiscretion\b", r"\bjudge?ment\b",
                      r"\binterpret\w*"),
    "say_mention": _rx(r"\bsays?\b", r"\bsaid\b", r"\bmention\w*", r"\butter\w*", r"\btweet\w*",
                       r"\bpost(?:s|ed)? on (?:x|twitter|truth social)\b"),
    # what makes rules complete
    "fallback": _rx(r"\botherwise\b", r"50-50|50/50|fifty-fifty", r"\bin the event (?:that|of)\b",
                    r"\bif (?:no|none|neither)\b.{0,100}?\bresolve",
                    r"\bcancel+ed\b|\bpostpon\w+|\bdelay(?:ed|s)?\b",
                    r"\bnot available\b|\bunavailable\b|ceases? to (?:exist|publish|be)"),
    "definition": _rx(r"\bwill count\b", r"\b(?:will not|won't|does not|do not|shall not) count\b",
                      r"\bdefined as\b", r"for the purposes? of this market",
                      r"[\"\u201c'][^\"\u201d'\n]{1,40}[\"\u201d']\s+(?:means|refers to)\b",
                      r"\bthe term\b.{0,40}?\b(?:means|refers to)\b",
                      r"\bregardless of\b", r"\bqualif(?:y|ies|ying)\b",
                      r"\bonly .{0,40}? will be considered\b", r"\bto be considered\b"),
    "timezone": _rx(r"\b(?:ET|EST|EDT|UTC|GMT|PT|PST|PDT|CT|CST|CDT)\b",
                    r"eastern time|pacific time|central time|coordinated universal"),
    "clock_time": _rx(r"\b\d{1,2}:\d{2}\s*(?:am|pm|a\.m\.|p\.m\.)?", r"\bnoon\b", r"\bmidnight\b"),
    "named_source": _rx(r"https?://", r"\bwww\.", r"\.gov\b",
                        r"\bSEC\b|\bEDGAR\b|\bForm (?:8-K|10-Q|10-K)\b",
                        r"\b(?:AP|Associated Press|Reuters|Bloomberg|BLS|Bureau of Labor Statistics|"
                        r"Federal Reserve|FRED|CoinGecko|CoinMarketCap|Binance|Coinbase|CME|NOAA|"
                        r"ESPN|Box Office Mojo|Billboard|Spotify|YouTube|Wikipedia|Kalshi|"
                        r"official website|official (?:X|Twitter) account)\b"),
    "measurement": _rx(r"closing price|close price|\bcandle\b", r"\bintraday\b",
                       r"(?:initial|first|advance|preliminary) (?:release|estimate|print|reading)",
                       r"\brevis\w+", r"\bround(?:ed|ing)?\b", r"as (?:reported|published|listed) (?:by|on)"),
    "threshold": _rx(r"\bat least\b", r"\bor (?:more|higher|above|greater)\b", r"\bgreater than\b",
                     r"\bmore than\b", r"\babove\b", r"\bexceed\w*", r"\bless than\b",
                     r"\bfewer than\b", r"\bbelow\b", r"\bor (?:less|lower|below)\b"),
}

_DEADLINE = _rx(rf"\b(?:by|before|on or before|prior to|no later than)\s+(?:the end of\s+)?{_MONTH}\b",
                r"\b(?:by|before|on or before|prior to|no later than)\s+\d{1,2}/\d{1,2}",
                r"\bdeadline\b", r"\b11:59\b",
                r"\bby (?:the )?end of (?:the )?(?:day|week|month|year|quarter)\b",
                rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b")
_TIMING_EXPLICIT = _rx(r"regardless of when", r"must (?:occur|take place|happen|be completed)",
                       r"(?:occur|occurs|occurred|takes? place|took place|happen\w*)\s+(?:on or )?(?:before|by|prior)",
                       r"(?:announce|report|confirm|disclos)\w*\s+(?:after|following)\s+(?:the|this)",
                       r"date of the (?:event|announcement|sale|transaction)",
                       r"\b(?:the )?announcement (?:alone|itself)\b",
                       r"(?:announce|report|confirm)\w* (?:on or )?(?:before|by) the (?:deadline|end)")
_LEGIS = _rx(r"\bbills?\b", r"\blaws?\b", r"\blegislat\w+", r"\bregulations?\b",
             r"\bstatutes?\b", r"\bordinances?\b", r"\bexecutive orders?\b", r"\bwage orders?\b",
             r"\bballot (?:measure|initiative|proposition)s?\b")
_LEGIS_ACTION = _rx(r"\bpass(?:es|ed)?\b", r"\benact\w*", r"\badopt\w*", r"\brepeal\w*",
                    r"\brestor\w+", r"\bamend\w*", r"\bfix(?:es|ed)?\b", r"\bapprov\w+",
                    r"\boverturn\w*", r"\bstr(?:ike|uck) down\b", r"\bsigns?\b", r"\bsigned\b")
_LEGIS_STAGE = _rx(r"signed into law", r"\btake[sn]? effect\b", r"\bin effect\b",
                   r"\beffective (?:date|on|as of)\b", r"\benacted\b", r"\bchaptered\b",
                   r"\bbecomes? law\b", r"\bfinal passage\b", r"\bboth (?:chambers|houses)\b",
                   r"\b(?:governor|president) signs?\b", r"signature of the (?:governor|president)")
_NAMED_OUTLET = _rx(r"\b(?:AP|Associated Press|Reuters|Bloomberg|New York Times|NYT|"
                    r"Wall Street Journal|WSJ|Washington Post|BBC|CNN|Financial Times|FT)\b")
_CONDITION = _rx(r"\bif\b", r"\bunless\b", r"\bprovided that\b", r"\bonly if\b", r"\bin case\b")
_ANDOR = _rx(r"\band\b", r"\bor\b")
_NUMBER = re.compile(r"(?<![\w.])[$€£]?\d[\d,]*(?:\.\d+)?%?")
_URL = re.compile(r"https?://\S+|www\.\S+")


def lexicon_counts(text: str) -> dict[str, int]:
    return {k: len(rx.findall(text)) for k, rx in LEXICON.items()}


def flags(title: str, rules: str) -> dict[str, bool]:
    """Yes/no checks behind the linter; each names a way rules leave a case open."""
    t = f"{title}\n{rules}"
    c = lexicon_counts(t)
    deadline = bool(_DEADLINE.search(t))
    numbers = len(_NUMBER.findall(_URL.sub(" ", t)))
    return {
        "flag_consensus_undefined": c["consensus_source"] > 0 and not _NAMED_OUTLET.search(t),
        "flag_event_vs_announcement": (c["announcement"] > 0 and deadline
                                       and not _TIMING_EXPLICIT.search(t)),
        "flag_undefined_term": c["vague_state"] > 0 and c["definition"] == 0,
        "flag_no_timezone": deadline and c["timezone"] == 0,
        "flag_no_source": c["named_source"] == 0,
        "flag_no_fallback": c["fallback"] == 0,
        "flag_threshold_unmeasured": (c["threshold"] > 0 and numbers > 0
                                      and c["measurement"] == 0 and c["named_source"] == 0),
        "flag_degree_words": c["degree"] > 0,
        "flag_subjective": c["subjective"] > 0,
        "flag_mention_undefined": c["say_mention"] > 0 and c["definition"] == 0,
        "flag_legislative_stage": (bool(_LEGIS.search(t)) and bool(_LEGIS_ACTION.search(t))
                                   and not _LEGIS_STAGE.search(t)),
    }


def structure(title: str, rules: str) -> dict[str, float]:
    words = re.findall(r"\w+", rules)
    n = max(1, len(words))
    return {
        "log_words": math.log1p(len(words)),
        "log_title_words": math.log1p(len(re.findall(r"\w+", title or ""))),
        "sentences": float(len(re.findall(r"[.!?](?:\s|$)", rules)) or 1),
        "conditions_per_100w": 100 * len(_CONDITION.findall(rules)) / n,
        "andor_per_100w": 100 * len(_ANDOR.findall(rules)) / n,
        "numbers_per_100w": 100 * len(_NUMBER.findall(_URL.sub(" ", rules))) / n,
        "has_url": float(bool(_URL.search(rules))),
        "has_deadline": float(bool(_DEADLINE.search(f"{title}\n{rules}"))),
    }


def features(title: str, rules: str) -> dict[str, float]:
    """Dense listing-time features for one market (rules already stripped)."""
    t = f"{title}\n{rules}"
    out = {f"lex_{k}": float(min(v, 5)) for k, v in lexicon_counts(t).items()}
    out.update({k: float(v) for k, v in flags(title, rules).items()})
    out.update(structure(title, rules))
    return out


_NUM_TOKEN = re.compile(r"\d+(?:[.,:/]\d+)*")


def doc(title: str, rules: str) -> str:
    """Text for the bag-of-words model: numbers collapsed so templates generalise."""
    return _NUM_TOKEN.sub(" 0 ", f"{title}\n{rules}".lower())


def template_key(rules: str) -> str:
    """Rules with numbers, dates and quoted names masked: one key per recurring template."""
    s = re.sub(rf"\b{_MONTH}\b", " M ", (rules or "").lower())
    s = _NUM_TOKEN.sub(" 0 ", s)
    s = re.sub(r"\"[^\"]{0,80}\"|'[^']{0,80}'", " Q ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:400]


CATEGORY_RULES = [
    ("mentions", r"mention"),
    ("elections", r"election|primar(?:y|ies)|midterm|electoral|\bvote|\bpolls?\b|nominee|nomination"),
    ("geopolitics", r"geopolitic|ukraine|russia|israel|iran|gaza|china|taiwan|\bwar\b|military|nato|"
                    r"middle east|foreign policy|world"),
    ("politics", r"politic|trump|congress|senate|white house|supreme court|government|executive order|"
                 r"cabinet|\bus\b|biden|doge"),
    ("crypto", r"crypto|bitcoin|ethereum|solana|\bbtc\b|\beth\b|\bxrp\b|doge|memecoin|airdrop|token|"
               r"stablecoin|defi"),
    ("sports", r"sport|\bnba\b|\bnfl\b|\bmlb\b|\bnhl\b|soccer|football|tennis|golf|\bufc\b|\bmma\b|"
               r"\bf1\b|formula 1|cricket|esports|premier league|champions league|olympic|boxing|ncaa|"
               r"world cup|baseball|basketball|hockey|games?\b"),
    ("economy", r"econom|\bfed\b|fomc|inflation|\bcpi\b|\bgdp\b|jobs report|unemployment|"
                r"interest rate|recession|tariff"),
    ("business", r"business|\btech\b|\bai\b|stocks?|earnings|\bipo\b|compan|finance|openai|tesla|"
                 r"apple|nvidia|microsoft|spacex|\bceo\b"),
    ("culture", r"culture|pop|entertainment|movie|film|box office|music|grammy|oscar|award|celebrit|"
                r"\btv\b|tweets?|youtube|tiktok|netflix|spotify|album|song"),
    ("science", r"science|space|weather|climate|hurricane|temperature|pandemic|health|covid|disease|nasa"),
]
_CATEGORY_RX = [(name, re.compile(rx, re.I)) for name, rx in CATEGORY_RULES]
CATEGORIES = [name for name, _ in CATEGORY_RULES] + ["other"]


def category_of(tags: list[str] | None, fallback: str | None = None, title: str = "") -> str:
    """One coarse category from Gamma tags (then Gamma's category, then the title)."""
    tags = [t for t in (tags if isinstance(tags, list) else []) if isinstance(t, str)]
    for source in (" | ".join(tags), fallback, title):
        if not isinstance(source, str) or not source:
            continue
        for name, rx in _CATEGORY_RX:
            if rx.search(source):
                return name
    return "other"
