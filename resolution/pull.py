"""Pull closed Polymarket markets, their resolution history and on-chain disputes.

    python3 -m resolution.pull all --out data/pm --since 2024-01-01
    python3 -m resolution.pull gamma --out data/pm --since 2024-01-01 --min-volume 10000
    python3 -m resolution.pull resolutions --out data/pm [--questions]
    python3 -m resolution.pull chain --out data/pm --since 2024-01-01 --rpc $POLYGON_RPC_URL

Three sources, all public and unauthenticated:

* Gamma ``/markets/keyset``: market metadata and the rules text
  (``description``), written to ``gamma_markets.jsonl``.
* Data API ``/v2/resolutions``: the resolution lifecycle per condition,
  including ``was_disputed``, ``was_arbitrated`` and ``new_version_q``
  (rules updated after the question was posed), written to
  ``resolutions.jsonl``. With ``--questions``, disputed markets are also looked
  up by question id to get the first and second proposed prices
  (``resolutions_q.jsonl``).
* Polygon ``eth_getLogs`` for UMA's ``DisputePrice`` event: every dispute,
  with the listing-time question text, written to ``dispute_logs.jsonl``.
  Optional; needs a Polygon JSON-RPC URL (a free Alchemy or Infura key is much
  faster than public endpoints).

Every step resumes where it stopped. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import abi
from .net import RPC, Client, FetchError, RPCError

GAMMA_BASE = os.environ.get("GAMMA_API_BASE", "https://gamma-api.polymarket.com")
DATA_BASE = os.environ.get("POLYMARKET_DATA_API_BASE", "https://data-api.polymarket.com")
DEFAULT_RPC = os.environ.get("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")

GAMMA_KEEP = [
    "id", "question", "conditionId", "questionID", "slug", "description",
    "resolutionSource", "category", "outcomes", "outcomePrices", "startDate",
    "createdAt", "endDate", "closedTime", "umaEndDate", "updatedAt", "volumeNum",
    "liquidityNum", "umaBond", "umaReward", "customLiveness", "resolvedBy",
    "umaResolutionStatus", "umaResolutionStatuses", "automaticallyResolved",
    "marketType", "formatType", "groupItemTitle", "negRiskOther", "sportsMarketType",
    "gameId", "closed", "archived",
]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def _iso(date: str | None) -> str | None:
    if not date:
        return None
    return date if "T" in date else f"{date}T00:00:00Z"


def slim_market(m: dict) -> dict:
    """Keep the fields the analysis uses; flatten tags, events and series."""
    out = {k: m.get(k) for k in GAMMA_KEEP}
    out["tags"] = [t.get("label") or t.get("slug") for t in (m.get("tags") or [])
                   if isinstance(t, dict)]
    events = []
    for e in m.get("events") or []:
        if not isinstance(e, dict):
            continue
        events.append({
            "id": e.get("id"), "slug": e.get("slug"), "title": e.get("title"),
            "negRisk": e.get("negRisk"), "negRiskMarketID": e.get("negRiskMarketID"),
            "series": [s.get("slug") or s.get("ticker") for s in (e.get("series") or [])
                       if isinstance(s, dict)],
            "tags": [t.get("label") or t.get("slug") for t in (e.get("tags") or [])
                     if isinstance(t, dict)],
        })
    out["events"] = events
    return out


class JsonlWriter:
    """Append-only JSON lines. A run killed mid-write can leave a partial last
    line; it is cut off on open, so the next row does not fuse with it."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size:
            with path.open("rb+") as f:
                data = f.read()
                if not data.endswith(b"\n"):
                    f.truncate(data.rfind(b"\n") + 1)
        self.f = path.open("a", encoding="utf-8")

    def write(self, row: dict) -> None:
        self.f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def flush(self) -> None:
        self.f.flush()
        os.fsync(self.f.fileno())

    def close(self) -> None:
        self.f.close()


def read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # a line cut off by an interrupted run


def _state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(path)


# --------------------------------------------------------------------------- Gamma

def pull_gamma(out: Path, *, since: str | None, until: str | None, min_volume: float,
               client: Client | None = None, page_size: int = 100,
               max_pages: int | None = None) -> int:
    client = client or Client(GAMMA_BASE)
    state_path = out / "gamma_state.json"
    state = _state(state_path)
    query = {"since": since, "until": until, "min_volume": min_volume}
    if state.get("query") and state["query"] != query:
        raise SystemExit(f"{state_path} was written for {state['query']}; "
                         "use another --out or delete the state file")
    if state.get("done"):
        log(f"gamma: already complete ({state.get('count', 0)} markets)")
        return state.get("count", 0)
    state["query"] = query
    writer = JsonlWriter(out / "gamma_markets.jsonl")
    params = {"closed": "true", "limit": page_size, "include_tag": "true",
              "volume_num_min": min_volume or None, "end_date_min": _iso(since),
              "end_date_max": _iso(until)}
    count, pages = state.get("count", 0), 0
    mode = state.get("mode", "keyset")
    try:
        while True:
            if mode == "keyset":
                try:
                    page = client.get("/markets/keyset",
                                      {**params, "after_cursor": state.get("cursor")})
                except FetchError as err:
                    if err.code in (400, 422) and params.get("include_tag"):
                        log(f"gamma: include_tag refused ({err.code}); continuing without tags")
                        params.pop("include_tag")
                        continue
                    if err.code in (404, 405, 422) and not state.get("cursor"):
                        log(f"gamma: keyset paging unavailable ({err.code}); using offset")
                        mode = state["mode"] = "offset"
                        continue
                    raise
                markets = page.get("markets", []) if isinstance(page, dict) else page
                cursor = page.get("next_cursor") if isinstance(page, dict) else None
            else:
                markets = client.get("/markets", {**params, "limit": 500,
                                                  "offset": state.get("offset", 0)})
                cursor = None
            for m in markets or []:
                writer.write(slim_market(m))
            count += len(markets or [])
            pages += 1
            writer.flush()
            state["count"] = count
            if mode == "keyset":
                state["cursor"] = cursor
                finished = not cursor or not markets
            else:
                state["offset"] = state.get("offset", 0) + len(markets or [])
                finished = not markets
            if finished:
                state["done"] = True
                state["pulled_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _save_state(state_path, state)
            if pages % 20 == 0:
                log(f"gamma: {count} markets")
            if finished or (max_pages and pages >= max_pages):
                break
    finally:
        writer.close()
    log(f"gamma: {count} markets in {out / 'gamma_markets.jsonl'}")
    return count


# ---------------------------------------------------------------- Data API resolutions

def pull_resolutions(out: Path, *, client: Client | None = None, batch: int = 20,
                     questions: bool = False) -> int:
    client = client or Client(DATA_BASE)
    markets = {}
    for m in read_jsonl(out / "gamma_markets.jsonl"):
        if m.get("conditionId"):
            markets[m["conditionId"].lower()] = m
    path = out / "resolutions.jsonl"
    done = {r.get("condition_id", "").lower() for r in read_jsonl(path) if not r.get("_missing")}
    todo = [c for c in markets if c not in done]
    log(f"resolutions: {len(done)} already pulled, {len(todo)} to go")

    def ask(ids: list[str]) -> list[dict]:
        try:
            page = client.get("/v2/resolutions", {"condition": ",".join(ids)})
        except FetchError as err:
            if err.code != 400:
                raise
            if len(ids) == 1:
                return []
            return [r for cid in ids for r in ask([cid])]  # one bad id spoils a batch
        return page.get("data", []) if isinstance(page, dict) else []

    writer = JsonlWriter(path)
    n = 0
    try:
        for i in range(0, len(todo), batch):
            chunk = todo[i: i + batch]
            rows = ask(chunk)
            got = {(r.get("condition_id") or "").lower() for r in rows}
            for cid in [c for c in chunk if c not in got]:  # a capped response? ask alone
                rows += ask([cid]) if len(chunk) > 1 else []
            got = set()
            for k, r in enumerate(rows):
                cid = (r.get("condition_id") or "").lower()
                if cid:
                    got.add(cid)
                    writer.write({**r, "_row": k})
            for cid in chunk:
                if cid not in got:
                    writer.write({"condition_id": cid, "_missing": True})
            writer.flush()
            n += len(chunk)
            if (i // batch) % 50 == 0:
                log(f"resolutions: {n}/{len(todo)}")
    finally:
        writer.close()
    if questions:
        pull_question_rows(out, client=client, markets=markets)
    return n


def pull_question_rows(out: Path, *, client: Client, markets: dict) -> int:
    """First and second proposed prices for disputed markets (one call each)."""
    disputed = {r.get("condition_id", "").lower() for r in read_jsonl(out / "resolutions.jsonl")
                if r.get("was_disputed")}
    path = out / "resolutions_q.jsonl"
    done = {r.get("_question_id") for r in read_jsonl(path)}
    qids = sorted({markets[c]["questionID"].lower() for c in disputed
                   if c in markets and markets[c].get("questionID")} - done)
    log(f"resolutions: {len(qids)} disputed questions to look up by question id")
    writer = JsonlWriter(path)
    try:
        for k, q in enumerate(qids):
            try:
                page = client.get("/v2/resolutions", {"question_id": q})
            except FetchError as err:
                if err.code == 400:
                    writer.write({"_question_id": q, "_missing": True})
                    continue
                raise
            rows = page.get("data", []) if isinstance(page, dict) else []
            writer.write({**(rows[0] if rows else {"_missing": True}), "_question_id": q})
            if k % 100 == 0:
                writer.flush()
    finally:
        writer.close()
    return len(qids)


# ---------------------------------------------------------------------- chain disputes

_RANGE_ERRORS = ("range", "too many results", "too large", "exceed", "limit", "10000", "10,000",
                 "response size", "query returned more", "timeout", "timed out")
_RATE_ERRORS = ("rate", "429", "too many requests", "throttl", "capacity", "busy")


def _too_big(err: Exception) -> bool:
    """Does the error read like a span or result cap (rather than a rate limit)?"""
    msg = str(err).lower()
    code = getattr(err, "code", None)
    if code == 429 or any(w in msg for w in _RATE_ERRORS):
        return False
    return code in (413, -32005, -32602, -32614) or any(w in msg for w in _RANGE_ERRORS)


def scan_logs(rpc: RPC, *, from_block: int, to_block: int, topics: list, on_logs,
              on_progress=None, chunk: int = 100_000, min_chunk: int = 500,
              max_chunk: int = 5_000_000, sleep=time.sleep) -> int:
    """eth_getLogs over [from_block, to_block] with an adaptive block range.

    Providers cap the block span or the number of results and word the error
    differently. An error that reads like a cap cuts the span to a quarter and
    lowers the ceiling to half the failed span; any other error (rate limits,
    dropped connections) is retried at the same span with backoff. Spans that
    succeed with few results double, and after 20 clean calls the ceiling is
    allowed to double again.
    """
    a, size, ceiling, n, strikes, clean = from_block, chunk, max_chunk, 0, 0, 0
    while a <= to_block:
        b = min(a + size - 1, to_block)
        try:
            logs = rpc.call("eth_getLogs", [{"fromBlock": hex(a), "toBlock": hex(b),
                                              "topics": topics}])
        except (RPCError, FetchError) as err:
            clean = 0
            if _too_big(err) and size > min_chunk:
                ceiling = max(min_chunk, size // 2)
                size = max(min_chunk, size // 4)
                continue
            strikes += 1
            if strikes > 6:
                raise
            log(f"chain: retrying blocks {a}-{b} after: {err}")
            sleep(min(60.0, 2.0 * strikes))
            continue
        strikes = 0
        clean += 1
        logs = [x for x in (logs or []) if not x.get("removed")]
        on_logs(logs)
        n += len(logs)
        if on_progress:
            on_progress(b)
        a = b + 1
        if clean % 20 == 0:
            ceiling = min(max_chunk, ceiling * 2)
        if len(logs) < 2_000:
            size = min(size * 2, ceiling)
    return n


def pull_chain(out: Path, *, rpc_url: str, since: str | None = None,
               from_block: int | None = None, to_block: int | None = None,
               requesters: list[str] | None = None, chunk: int = 100_000,
               rpc: RPC | None = None) -> int:
    rpc = rpc or RPC(rpc_url, min_interval=0.1)
    state_path = out / "chain_state.json"
    state = _state(state_path)
    latest = to_block or state.get("to_block") or rpc.block_number()
    if "next_block" in state:
        start = state["next_block"]
    elif from_block is not None:
        start = from_block
    elif since:
        ts = int(datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp())
        start = rpc.block_at(ts, hi=latest)
        log(f"chain: {since} starts at block {start}")
    else:
        start = 29_786_052  # first block of Polymarket's UMA OOv2 adapters
    if state.get("requesters") not in (None, sorted(r.lower() for r in requesters or [])):
        raise SystemExit(f"{state_path} was scanned with another --requesters filter; "
                         "use another --out or delete the chain files")
    state.update({"from_block": state.get("from_block", start), "to_block": latest,
                  "requesters": sorted(r.lower() for r in requesters or [])})
    topics = [abi.DISPUTE_PRICE_TOPIC]
    if requesters:
        topics.append(["0x" + "0" * 24 + r.lower().removeprefix("0x") for r in requesters])
    writer = JsonlWriter(out / "dispute_logs.jsonl")
    counter = {"n": 0, "last": time.monotonic()}

    def on_logs(logs):
        for x in logs:
            try:
                writer.write(abi.decode_dispute_log(x))
            except Exception as err:  # keep going; count what could not be read
                writer.write({"_undecodable": True, "error": str(err),
                              "tx": x.get("transactionHash")})
        counter["n"] += len(logs)

    def on_progress(b):
        writer.flush()
        state["next_block"] = b + 1
        _save_state(state_path, state)
        if time.monotonic() - counter["last"] > 30:
            counter["last"] = time.monotonic()
            pct = 100 * (b - state["from_block"]) / max(1, latest - state["from_block"])
            log(f"chain: block {b} ({pct:.0f}%), {counter['n']} disputes")

    try:
        if start <= latest:
            scan_logs(rpc, from_block=start, to_block=latest, topics=topics,
                      on_logs=on_logs, on_progress=on_progress, chunk=chunk)
    finally:
        writer.close()
    anchors_path = out / "block_anchors.json"
    anchors = {int(k): v for k, v in _state(anchors_path).items()}
    lo = state["from_block"]
    for k in range(41):
        blk = lo + (latest - lo) * k // 40
        if blk not in anchors:
            try:
                anchors[blk] = rpc.block_timestamp(blk)
            except (RPCError, FetchError) as err:
                log(f"chain: no timestamp for block {blk}: {err}")
    _save_state(anchors_path, {str(k): v for k, v in sorted(anchors.items())})
    state["done"] = True
    _save_state(state_path, state)
    log(f"chain: {counter['n']} dispute logs this run; blocks {lo}-{latest} done")
    return counter["n"]


# ------------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("all", "gamma", "resolutions", "chain"):
        p = sub.add_parser(name)
        p.add_argument("--out", default="data/pm", type=Path)
        if name in ("all", "gamma", "chain"):
            p.add_argument("--since", default="2024-01-01",
                           help="markets ending on or after this date (YYYY-MM-DD)")
        if name in ("all", "gamma"):
            p.add_argument("--until", default=None)
            p.add_argument("--min-volume", type=float, default=10_000)
        if name in ("all", "resolutions"):
            p.add_argument("--no-questions", action="store_true",
                           help="skip the per-question lookup of proposed prices")
        if name in ("all", "chain"):
            p.add_argument("--rpc", default=DEFAULT_RPC)
            p.add_argument("--from-block", type=int)
            p.add_argument("--to-block", type=int)
            p.add_argument("--chunk", type=int, default=100_000)
            p.add_argument("--requesters", default="",
                           help="comma-separated adapter addresses to keep (default: all)")
        if name == "all":
            p.add_argument("--skip-chain", action="store_true")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.cmd in ("all", "gamma"):
        pull_gamma(args.out, since=args.since, until=args.until, min_volume=args.min_volume)
    if args.cmd in ("all", "resolutions"):
        pull_resolutions(args.out, questions=not args.no_questions)
    if args.cmd == "chain" or (args.cmd == "all" and not args.skip_chain):
        req = [r for r in args.requesters.split(",") if r.strip()] or None
        try:
            pull_chain(args.out, rpc_url=args.rpc, since=args.since,
                       from_block=args.from_block, to_block=args.to_block,
                       requesters=req, chunk=args.chunk)
        except (RPCError, FetchError) as err:
            if args.cmd == "all":
                log(f"chain: skipped ({err}); the analysis runs without it. "
                    "Retry with: python3 -m resolution.pull chain --rpc <your Polygon URL>")
            else:
                raise


if __name__ == "__main__":
    main()
