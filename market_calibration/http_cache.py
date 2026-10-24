"""Polite, cached, resumable HTTP GET for public read-only market-data endpoints.

Every response (including 4xx bodies other than 429) is stored gzip-compressed
under ``data/raw/<venue>/<kind>/<sha1>.json.gz`` together with the URL and the
fetch time, so a rerun reads the cache instead of the network. Requests to one
host are spaced by a minimum interval; 429 and 5xx responses are retried with
exponential backoff (honouring ``Retry-After``) and are never cached.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
USER_AGENT = ("market-calibration-study/1.0 (read-only academic research; "
              "github.com/bbbarbie)")

# Maximum request rate per host (requests per second). The Kalshi and
# Polymarket collectors may run at the same time; the totals stay <= 5 req/s.
HOST_RATE = {
    "api.elections.kalshi.com": 2.0,
    "gamma-api.polymarket.com": 3.0,
    "clob.polymarket.com": 3.0,
}
DEFAULT_RATE = 2.0


class FetchError(RuntimeError):
    pass


def canonical_url(url: str, params: dict | None = None) -> str:
    if not params:
        return url
    items = []
    for k, v in params.items():
        if v is None:
            continue
        for one in (v if isinstance(v, (list, tuple)) else [v]):
            items.append((k, str(one)))   # lists become repeated parameters
    return f"{url}?{urlencode(sorted(items))}"


def cache_path(full_url: str, venue: str, kind: str, raw_dir: Path = RAW_DIR) -> Path:
    digest = hashlib.sha1(full_url.encode()).hexdigest()[:24]
    return raw_dir / venue / kind / f"{digest}.json.gz"


class Fetcher:
    def __init__(self, raw_dir: Path = RAW_DIR, offline: bool = False,
                 max_attempts: int = 8, verbose: bool = True):
        import requests  # imported lazily so offline users need not have it

        self.raw_dir = raw_dir
        self.offline = offline
        self.max_attempts = max_attempts
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT,
                                     "Accept": "application/json"})
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self.n_network = 0
        self.n_cached = 0
        self.n_retries = 0

    # ------------------------------------------------------------------
    def _wait_turn(self, host: str) -> None:
        interval = 1.0 / HOST_RATE.get(host, DEFAULT_RATE)
        with self._lock:
            now = time.monotonic()
            ready = self._last.get(host, 0.0) + interval
            if ready > now:
                time.sleep(ready - now)
            self._last[host] = time.monotonic()

    def get(self, url: str, params: dict | None = None, *, venue: str,
            kind: str) -> tuple[int, object]:
        """Return (http_status, parsed_json_body) using the cache when possible.

        In offline mode a cache miss returns (-1, None).
        """
        full = canonical_url(url, params)
        path = cache_path(full, venue, kind, self.raw_dir)
        if path.exists():
            self.n_cached += 1
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                rec = json.load(fh)
            return rec["status"], rec["body"]
        if self.offline:
            return -1, None

        host = urlsplit(url).netloc
        attempt = 0
        while True:
            attempt += 1
            self._wait_turn(host)
            try:
                resp = self.session.get(full, timeout=60)
            except Exception as exc:  # connection reset, timeout, ...
                if attempt >= self.max_attempts:
                    raise FetchError(f"{full}: {exc}") from exc
                self._backoff(attempt, None, f"exception {exc!r}")
                continue
            status = resp.status_code
            if status == 429 or status >= 500:
                if attempt >= self.max_attempts:
                    raise FetchError(f"{full}: HTTP {status} after {attempt} tries")
                self._backoff(attempt, resp.headers.get("Retry-After"), f"HTTP {status}")
                continue
            break

        self.n_network += 1
        try:
            body = resp.json()
        except ValueError:
            body = {"_non_json": resp.text[:2000]}
        rec = {"url": full, "status": status,
               "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "body": body}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".tmp{os.getpid()}")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(rec, fh, separators=(",", ":"))
        tmp.replace(path)
        if self.verbose and self.n_network % 100 == 0:
            print(f"  [http] {self.n_network} fetched, {self.n_cached} cached, "
                  f"{self.n_retries} retries", flush=True)
        return status, body

    def _backoff(self, attempt: int, retry_after: str | None, why: str) -> None:
        self.n_retries += 1
        delay = min(120.0, 2.0 ** attempt) + random.uniform(0, 1)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        if self.verbose:
            print(f"  [http] {why}; backing off {delay:.1f}s (attempt {attempt})",
                  flush=True)
        time.sleep(delay)
