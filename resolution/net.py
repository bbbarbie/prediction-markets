"""Small HTTP and JSON-RPC client: standard library only, retries, rate limit."""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "prediction-market-portfolio-resolution/0.1 (+python urllib)"


class FetchError(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class RPCError(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class Client:
    """GET/POST JSON with a client-side rate limit and backoff on 429 and 5xx."""

    def __init__(self, base: str = "", *, min_interval: float = 0.15,
                 retries: int = 5, timeout: float = 60.0, sleep=time.sleep):
        self.base = base.rstrip("/")
        self.min_interval = min_interval
        self.retries = retries
        self.timeout = timeout
        self._sleep = sleep
        self._last = 0.0
        self.calls = 0

    def _url(self, path: str, params: dict | None) -> str:
        url = path if path.startswith("http") else f"{self.base}{path}"
        query = {k: v for k, v in (params or {}).items() if v is not None}
        if query:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query, doseq=True)
        return url

    def _send(self, req: urllib.request.Request) -> Any:
        delay = 1.0
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            self.calls += 1
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                body = err.read().decode("utf-8", "replace")[:300]
                retryable = err.code == 429 or err.code >= 500
                if not retryable or attempt == self.retries:
                    raise FetchError(f"HTTP {err.code} for {req.full_url}: {body}",
                                     err.code) from err
                after = err.headers.get("Retry-After") if err.headers else None
                pause = float(after) if after and after.replace(".", "", 1).isdigit() else delay
                self._sleep(min(pause, 120.0))
            except (urllib.error.URLError, TimeoutError, ConnectionError,
                    http.client.HTTPException, json.JSONDecodeError) as err:
                if attempt == self.retries:
                    reason = getattr(err, "reason", err)
                    raise FetchError(f"cannot reach {req.full_url}: {reason}") from err
                self._sleep(delay)
            delay = min(delay * 2, 60.0)
        raise FetchError(f"unreachable: {req.full_url}")  # pragma: no cover

    def get(self, path: str, params: dict | None = None) -> Any:
        req = urllib.request.Request(self._url(path, params), headers={
            "Accept": "application/json", "User-Agent": USER_AGENT})
        return self._send(req)

    def post(self, path: str, payload: Any) -> Any:
        req = urllib.request.Request(self._url(path, None), method="POST",
                                     data=json.dumps(payload).encode("utf-8"), headers={
                                         "Accept": "application/json",
                                         "Content-Type": "application/json",
                                         "User-Agent": USER_AGENT})
        return self._send(req)


class RPC:
    """Ethereum JSON-RPC over a Client."""

    def __init__(self, url: str, **kw):
        self.client = Client(url, **kw)
        self._id = 0

    def call(self, method: str, params: list) -> Any:
        self._id += 1
        out = self.client.post("", {"jsonrpc": "2.0", "id": self._id,
                                    "method": method, "params": params})
        if isinstance(out, dict) and out.get("error"):
            err = out["error"]
            raise RPCError(str(err.get("message", err)), err.get("code"))
        return out.get("result") if isinstance(out, dict) else out

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def block_timestamp(self, number: int) -> int:
        block = self.call("eth_getBlockByNumber", [hex(number), False])
        if not block:
            raise RPCError(f"no block {number}")
        return int(block["timestamp"], 16)

    def block_at(self, ts: int, lo: int = 1, hi: int | None = None) -> int:
        """First block with timestamp >= ts (binary search, about 27 calls)."""
        hi = self.block_number() if hi is None else hi
        if self.block_timestamp(hi) < ts:
            return hi
        while lo < hi:
            mid = (lo + hi) // 2
            if self.block_timestamp(mid) < ts:
                lo = mid + 1
            else:
                hi = mid
        return lo
