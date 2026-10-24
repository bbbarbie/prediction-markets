"""Personal forecast log: my probability vs the market's, scored by Brier.

Every forecast records, at the moment it is made, my probability for YES and
the market's quote for the same contract, fetched from the venue's public API
so the comparison price cannot be chosen after the fact. Once markets resolve,
`score` compares my Brier score with the market's on exactly the same events.

    python forecast_log/pmlog.py add --venue kalshi --market <TICKER> --prob 0.62 --note "why"
    python forecast_log/pmlog.py add --venue polymarket --market <slug> --prob 0.30
    python forecast_log/pmlog.py add --venue manual --market <id> --question "..." \
        --prob 0.40 --market-prob 0.35 --close 2026-12-01T00:00:00Z
    python forecast_log/pmlog.py resolve                 # pull outcomes from the APIs
    python forecast_log/pmlog.py resolve --id F0007 --outcome 1    # or set one by hand
    python forecast_log/pmlog.py score [--plot forecast_log/calibration.png]
    python forecast_log/pmlog.py verify

Rules the tool enforces: one forecast per market, made while the market is
open, probability in [0.01, 0.99], and a two-sided market quote no wider than
--max-spread. `verify` adds the rule the tool cannot enforce alone: each
forecast must reach a git commit before its market closes, so the git history
is the timestamp. Only public, read-only market-data endpoints are used; no
account, key or money is involved.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

LOG_PATH = Path(__file__).resolve().parent / "forecasts.csv"
COLUMNS = [
    "forecast_id", "created_utc", "venue", "market", "question",
    "my_prob", "model_prob", "market_mid", "market_bid", "market_ask",
    "market_last", "close_utc", "note", "outcome", "resolved_utc",
]
KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/markets/{market}"
POLYMARKET_URL = "https://gamma-api.polymarket.com/markets?slug={market}"
MIN_PROB, MAX_PROB = 0.01, 0.99
DEFAULT_MAX_SPREAD = 0.20
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 7


@dataclass(frozen=True)
class MarketQuote:
    """A venue's view of one YES contract at one moment."""
    question: str
    bid: float | None
    ask: float | None
    last: float | None
    close_utc: str
    is_open: bool
    outcome: str          # "" while unresolved, else "1", "0" or "void"

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2.0
        return None


# ---------------------------------------------------------------- venues ---

def _float_or_none(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def parse_kalshi(payload: dict) -> MarketQuote:
    market = payload["market"]
    bid = _float_or_none(market.get("yes_bid_dollars"))
    ask = _float_or_none(market.get("yes_ask_dollars"))
    # Kalshi reports an empty side as bid 0 / ask 1: treat it as missing.
    if bid is not None and bid <= 0.0:
        bid = None
    if ask is not None and ask >= 1.0:
        ask = None
    result = (market.get("result") or "").lower()
    outcome = {"yes": "1", "no": "0", "": ""}.get(result, "void")
    return MarketQuote(
        question=market.get("title", ""),
        bid=bid, ask=ask,
        # Kalshi's minimum tick is 1 cent, so a last price of 0 means "no trade yet".
        last=_float_or_none(market.get("last_price_dollars")) or None,
        close_utc=market.get("close_time", ""),
        is_open=market.get("status") in ("active", "open"),
        outcome=outcome,
    )


def parse_polymarket(payload: list) -> MarketQuote:
    if not payload:
        raise LookupError("no Polymarket market with that slug")
    market = payload[0]
    outcomes = json.loads(market.get("outcomes") or "[]")
    if [o.lower() for o in outcomes[:2]] != ["yes", "no"]:
        raise ValueError(f"not a YES/NO market: outcomes={outcomes}")
    outcome = ""
    if market.get("closed") and market.get("umaResolutionStatus") == "resolved":
        prices = [float(p) for p in json.loads(market["outcomePrices"])]
        outcome = {1.0: "1", 0.0: "0"}.get(prices[0], "void")
    return MarketQuote(
        question=market.get("question", ""),
        bid=_float_or_none(market.get("bestBid")),
        ask=_float_or_none(market.get("bestAsk")),
        last=_float_or_none(market.get("lastTradePrice")),
        close_utc=market.get("endDate", ""),
        is_open=bool(market.get("active")) and not market.get("closed"),
        outcome=outcome,
    )


def http_get_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "pmlog/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def fetch_quote(venue: str, market: str,
                get_json: Callable[[str], object] = http_get_json) -> MarketQuote:
    encoded = urllib.parse.quote(market, safe="")
    if venue == "kalshi":
        return parse_kalshi(get_json(KALSHI_URL.format(market=encoded)))
    if venue == "polymarket":
        return parse_polymarket(get_json(POLYMARKET_URL.format(market=encoded)))
    raise ValueError(f"no API for venue {venue!r}")


# ------------------------------------------------------------------- log ---

def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    # Venues occasionally send a bare date; read it as UTC midnight.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_log(path: Path = LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write_log(rows: list[dict], path: Path = LOG_PATH) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COLUMNS})


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def add_forecast(rows: list[dict], *, venue: str, market: str, prob: float,
                 note: str = "", model_prob: float | None = None,
                 question: str = "", market_prob: float | None = None,
                 close_utc: str = "", max_spread: float = DEFAULT_MAX_SPREAD,
                 fetch: Callable[[str, str], MarketQuote] = fetch_quote,
                 created_utc: str | None = None) -> dict:
    """Validate one forecast and append it to rows; returns the new row."""
    if not MIN_PROB <= prob <= MAX_PROB:
        raise ValueError(f"--prob must be in [{MIN_PROB}, {MAX_PROB}]")
    if model_prob is not None and not 0.0 <= model_prob <= 1.0:
        raise ValueError("--model-prob must be in [0, 1]")
    if any(r["venue"] == venue and r["market"] == market for r in rows):
        raise ValueError(f"already forecast {venue}:{market}; one forecast per market")
    created = created_utc or now_utc()

    if venue == "manual":
        if market_prob is None or not close_utc or not question:
            raise ValueError("manual forecasts need --market-prob, --close and --question")
        quote = MarketQuote(question, None, None, None, close_utc, True, "")
        mid = market_prob
    else:
        quote = fetch(venue, market)
        if not quote.is_open:
            raise ValueError("market is not open; forecasts must be made before close")
        if market_prob is not None:
            raise ValueError("--market-prob is only for manual forecasts; API venues "
                             "record the live quote")
        if quote.mid is None:
            raise ValueError("market has no two-sided quote to compare against")
        if quote.ask - quote.bid > max_spread:
            raise ValueError(f"quote {quote.bid:.3f}/{quote.ask:.3f} is wider than "
                             f"--max-spread {max_spread}")
        mid = quote.mid
    if quote.close_utc and parse_time(quote.close_utc) <= parse_time(created):
        raise ValueError("market close time has passed")

    row = {
        "forecast_id": f"F{len(rows) + 1:04d}",
        "created_utc": created,
        "venue": venue,
        "market": market,
        "question": question or quote.question,
        "my_prob": f"{prob:.4f}",
        "model_prob": fmt(model_prob),
        "market_mid": fmt(mid),
        "market_bid": fmt(quote.bid),
        "market_ask": fmt(quote.ask),
        "market_last": fmt(quote.last),
        "close_utc": quote.close_utc,
        "note": note,
        "outcome": "",
        "resolved_utc": "",
    }
    rows.append(row)
    return row


def resolve_from_venues(rows: list[dict],
                        fetch: Callable[[str, str], MarketQuote] = fetch_quote) -> list[str]:
    """Fill outcomes of unresolved API forecasts; returns the ids resolved."""
    resolved = []
    for row in rows:
        if row["outcome"] or row["venue"] == "manual":
            continue
        quote = fetch(row["venue"], row["market"])
        if quote.outcome:
            row["outcome"] = quote.outcome
            row["resolved_utc"] = now_utc()
            resolved.append(row["forecast_id"])
    return resolved


# --------------------------------------------------------------- scoring ---

def brier(forecasts: np.ndarray, outcomes: np.ndarray) -> float:
    return float(np.mean((forecasts - outcomes) ** 2))


def log_loss(forecasts: np.ndarray, outcomes: np.ndarray) -> float:
    clipped = np.clip(forecasts, 1e-6, 1 - 1e-6)
    return float(-np.mean(outcomes * np.log(clipped)
                          + (1 - outcomes) * np.log(1 - clipped)))


def murphy(forecasts: np.ndarray, outcomes: np.ndarray, bins: int = 10) -> dict:
    """Reliability / resolution / uncertainty on equal-width bins.

    Brier = reliability - resolution + uncertainty exactly when forecasts are
    constant within each bin; otherwise the gap is the within-bin term, which
    is reported so the identity is never silently approximate.
    """
    index = np.minimum((forecasts * bins).astype(int), bins - 1)
    base_rate = outcomes.mean()
    reliability = resolution = 0.0
    table = []
    for k in range(bins):
        mask = index == k
        n = int(mask.sum())
        if n == 0:
            continue
        mean_forecast = forecasts[mask].mean()
        frequency = outcomes[mask].mean()
        reliability += n * (mean_forecast - frequency) ** 2
        resolution += n * (frequency - base_rate) ** 2
        table.append((k / bins, (k + 1) / bins, n, mean_forecast, frequency))
    total = len(forecasts)
    reliability /= total
    resolution /= total
    uncertainty = base_rate * (1 - base_rate)
    return {
        "reliability": reliability,
        "resolution": resolution,
        "uncertainty": uncertainty,
        "within_bin": brier(forecasts, outcomes) - (reliability - resolution + uncertainty),
        "table": table,
    }


def paired_bootstrap(differences: np.ndarray, samples: int = BOOTSTRAP_SAMPLES,
                     seed: int = BOOTSTRAP_SEED) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(differences), size=(samples, len(differences)))
    means = differences[draws].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def paper_pnl(prob: float, bid: float | None, ask: float | None, outcome: float,
              edge: float = 0.0) -> float | None:
    """P&L of one contract traded at the quote I saw, if my forecast said to.

    Buy YES at the ask when prob > ask + edge; sell YES at the bid when
    prob < bid - edge; otherwise no trade (None). No fees, unit size.
    """
    if ask is not None and prob > ask + edge:
        return outcome - ask
    if bid is not None and prob < bid - edge:
        return bid - outcome
    return None


def score(rows: list[dict], edge: float = 0.0) -> dict:
    done = [r for r in rows if r["outcome"] in ("0", "1")]
    if not done:
        return {"n": 0}
    y = np.array([float(r["outcome"]) for r in done])
    mine = np.array([float(r["my_prob"]) for r in done])
    market = np.array([float(r["market_mid"]) for r in done])
    report = {
        "n": len(done),
        "n_void": sum(r["outcome"] == "void" for r in rows),
        "n_open": sum(r["outcome"] == "" for r in rows),
        "base_rate": float(y.mean()),
        "brier_me": brier(mine, y),
        "brier_market": brier(market, y),
        "log_loss_me": log_loss(mine, y),
        "log_loss_market": log_loss(market, y),
        "mean_abs_disagreement": float(np.mean(np.abs(mine - market))),
        "murphy_me": murphy(mine, y),
        "murphy_market": murphy(market, y),
    }
    report["brier_skill_vs_market"] = 1 - report["brier_me"] / report["brier_market"] \
        if report["brier_market"] > 0 else float("nan")
    differences = (mine - y) ** 2 - (market - y) ** 2
    report["brier_diff"] = float(differences.mean())
    report["brier_diff_ci"] = paired_bootstrap(differences) if len(done) > 1 else (math.nan, math.nan)

    model_rows = [i for i, r in enumerate(done) if r["model_prob"] != ""]
    if model_rows:
        model = np.array([float(done[i]["model_prob"]) for i in model_rows])
        report["n_model"] = len(model_rows)
        report["brier_model"] = brier(model, y[model_rows])
        report["brier_market_on_model_rows"] = brier(market[model_rows], y[model_rows])

    trades = []
    for row, outcome in zip(done, y):
        pnl = paper_pnl(float(row["my_prob"]), _float_or_none(row["market_bid"]),
                        _float_or_none(row["market_ask"]), outcome, edge)
        if pnl is not None:
            trades.append(pnl)
    report["paper_trades"] = len(trades)
    report["paper_pnl"] = float(sum(trades))
    return report


def print_report(report: dict, verified: int | None) -> None:
    if report["n"] == 0:
        print("No resolved forecasts yet.")
        return
    print(f"Resolved forecasts: {report['n']} (open {report['n_open']}, "
          f"void {report['n_void']}); base rate {report['base_rate']:.2f}")
    if verified is not None:
        print(f"Committed to git before close: {verified} of {report['n']} "
              "(run `verify` for details)")
    print(f"\n{'':28}{'me':>10}{'market':>10}")
    print(f"{'Brier score':28}{report['brier_me']:>10.4f}{report['brier_market']:>10.4f}")
    print(f"{'Log loss':28}{report['log_loss_me']:>10.4f}{report['log_loss_market']:>10.4f}")
    for key, label in (("reliability", "Reliability (lower=better)"),
                       ("resolution", "Resolution (higher=better)")):
        print(f"{label:28}{report['murphy_me'][key]:>10.4f}"
              f"{report['murphy_market'][key]:>10.4f}")
    lo, hi = report["brier_diff_ci"]
    print(f"\nBrier skill vs market: {report['brier_skill_vs_market']:+.3f} "
          "(positive = I beat the market)")
    if hi < 0:
        verdict = "I beat the market on these events"
    elif lo > 0:
        verdict = "the market beat me on these events"
    else:
        verdict = "no demonstrated difference yet"
    print(f"Mean Brier difference me - market: {report['brier_diff']:+.4f} "
          f"(95% paired bootstrap CI {lo:+.4f} to {hi:+.4f}: {verdict})")
    if report["n"] < 100:
        print("Fewer than 100 resolved forecasts: reliability and resolution are "
              "noisy at this size; read the Brier difference and its interval first.")
    print(f"Mean |me - market|: {report['mean_abs_disagreement']:.3f}")
    if "brier_model" in report:
        print(f"Model forecasts: {report['n_model']}, Brier {report['brier_model']:.4f} "
              f"vs market {report['brier_market_on_model_rows']:.4f} on the same rows")
    print(f"\nPaper trading at the quotes I saw (1 contract, no fees): "
          f"{report['paper_trades']} trades, P&L {report['paper_pnl']:+.2f}")
    print("\nCalibration (my forecasts):")
    print(f"  {'bin':>11}{'n':>5}{'forecast':>10}{'observed':>10}")
    for lo_edge, hi_edge, n, mean_forecast, frequency in report["murphy_me"]["table"]:
        print(f"  {lo_edge:.1f}-{hi_edge:.1f}{n:>8}{mean_forecast:>10.2f}{frequency:>10.2f}")


def plot_reliability(report: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    ax.plot([0, 1], [0, 1], color="#52514e", linewidth=1, linestyle=":")
    for key, label, color in (("murphy_me", "Me", "#2a78d6"),
                              ("murphy_market", "Market", "#eb6834")):
        table = report[key]["table"]
        x = [row[3] for row in table]
        y = [row[4] for row in table]
        sizes = [20 + 8 * row[2] for row in table]
        ax.plot(x, y, color=color, linewidth=2, label=label)
        ax.scatter(x, y, s=sizes, color=color, edgecolor="#fcfcfb", linewidth=2, zorder=3)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Forecast probability (bin mean)", color="#0b0b0b")
    ax.set_ylabel("Observed frequency", color="#0b0b0b")
    ax.set_title(f"Reliability: me vs market (n = {report['n']})", color="#0b0b0b")
    ax.grid(color="#e4e3df", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# --------------------------------------------------------------- verify ---

def first_commit_time(forecast_id: str, path: Path = LOG_PATH) -> datetime | None:
    """Commit time of the first commit that added forecast_id to the log."""
    try:
        output = subprocess.run(
            ["git", "log", "--reverse", "--format=%cI", "-S", forecast_id, "--",
             path.name],
            cwd=path.parent, check=True, capture_output=True, text=True,
        ).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return datetime.fromisoformat(output[0]) if output else None


def verify(rows: list[dict],
           commit_time: Callable[[str], datetime | None] = first_commit_time) -> list[str]:
    """Return one problem string per forecast that breaks a rule."""
    problems = []
    for row in rows:
        fid = row["forecast_id"]
        close = parse_time(row["close_utc"]) if row["close_utc"] else None
        if close and parse_time(row["created_utc"]) >= close:
            problems.append(f"{fid}: created after the market closed")
        committed = commit_time(fid)
        if committed is None:
            problems.append(f"{fid}: not in any git commit yet")
        elif close and committed >= close:
            problems.append(f"{fid}: first committed {committed.isoformat()}, "
                            f"after close {row['close_utc']}")
    return problems


# ------------------------------------------------------------------ CLI ---

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="record a forecast and the live market quote")
    add.add_argument("--venue", choices=["kalshi", "polymarket", "manual"], required=True)
    add.add_argument("--market", required=True, help="Kalshi ticker or Polymarket slug")
    add.add_argument("--prob", type=float, required=True, help="my probability of YES")
    add.add_argument("--note", default="", help="one line on why")
    add.add_argument("--model-prob", type=float, help="optional model forecast (e.g. Averon)")
    add.add_argument("--question", default="", help="manual venue only")
    add.add_argument("--market-prob", type=float, help="manual venue only")
    add.add_argument("--close", default="", help="manual venue only, ISO 8601 UTC")
    add.add_argument("--max-spread", type=float, default=DEFAULT_MAX_SPREAD)

    res = sub.add_parser("resolve", help="fill in outcomes")
    res.add_argument("--id", help="forecast id to resolve by hand")
    res.add_argument("--outcome", choices=["1", "0", "void"])

    sc = sub.add_parser("score", help="Brier score me vs market")
    sc.add_argument("--plot", type=Path, help="write a reliability diagram here")
    sc.add_argument("--edge", type=float, default=0.0,
                    help="extra edge beyond the quote required to paper-trade")
    sub.add_parser("verify", help="check every forecast was committed before close")

    args = parser.parse_args(argv)
    rows = read_log()

    if args.command == "add":
        try:
            row = add_forecast(rows, venue=args.venue, market=args.market, prob=args.prob,
                               note=args.note, model_prob=args.model_prob,
                               question=args.question, market_prob=args.market_prob,
                               close_utc=args.close, max_spread=args.max_spread)
        except (ValueError, LookupError) as err:
            print(f"Not recorded: {err}")
            return 1
        write_log(rows)
        print(f"{row['forecast_id']}: me {row['my_prob']} vs market {row['market_mid']} "
              f"({row['market_bid'] or '-'}/{row['market_ask'] or '-'}) on "
              f"{row['question']!r}, closes {row['close_utc']}")
        print("Commit it now: git add forecast_log/forecasts.csv && "
              f"git commit -m 'Forecast {row['forecast_id']}'")
        return 0

    if args.command == "resolve":
        if args.id:
            matches = [r for r in rows if r["forecast_id"] == args.id]
            if not matches or not args.outcome:
                print("resolve --id needs an existing id and --outcome")
                return 1
            matches[0]["outcome"] = args.outcome
            matches[0]["resolved_utc"] = now_utc()
            resolved = [args.id]
        else:
            resolved = resolve_from_venues(rows)
        write_log(rows)
        print(f"Resolved: {', '.join(resolved) if resolved else 'nothing new'}")
        return 0

    if args.command == "score":
        report = score(rows, edge=args.edge)
        verified = None
        if report["n"]:
            ids = {r["forecast_id"] for r in rows if r["outcome"] in ("0", "1")}
            bad = {p.split(":")[0] for p in verify(rows)}
            verified = len(ids - bad)
        print_report(report, verified)
        if args.plot and report["n"]:
            plot_reliability(report, args.plot)
            print(f"\nSaved {args.plot}")
        return 0

    problems = verify(rows)
    for problem in problems:
        print(problem)
    print(f"{len(rows) - len({p.split(':')[0] for p in problems})} of {len(rows)} "
          "forecasts pass every rule.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
