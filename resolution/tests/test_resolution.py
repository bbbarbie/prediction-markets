"""Tests for the resolution dispute-risk package (no network: local fakes only)."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd

from resolution import abi, data as D, lint, model as M, pull, synth
from resolution import text as T
from resolution.keccak import keccak256, keccak256_py, keccak_hex
from resolution.net import RPC, Client, RPCError

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")


class Hashing(unittest.TestCase):
    def test_known_vectors(self):
        self.assertEqual(keccak256_py(b"").hex(),
                         "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")
        self.assertEqual(keccak256_py(b"abc").hex(),
                         "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45")
        self.assertEqual(keccak_hex(abi.DISPUTE_PRICE_SIG), abi.DISPUTE_PRICE_TOPIC)

    def test_pure_python_matches_backend_across_block_edges(self):
        rng = np.random.default_rng(0)
        for n in (0, 1, 135, 136, 137, 271, 272, 273, 1000):
            data = rng.integers(0, 256, n, dtype=np.uint8).tobytes()
            self.assertEqual(keccak256_py(data), keccak256(data))


class Abi(unittest.TestCase):
    def test_round_trip(self):
        anc = abi.ancillary_for("Will X happen?", "Rules, with commas, and \"quotes\".",
                                "0x" + "ab" * 20)
        log = abi.encode_dispute_log(requester="0x" + "11" * 20, proposer="0x" + "22" * 20,
                                     disputer="0x" + "33" * 20, ancillary=anc,
                                     proposed_price=abi.TOO_EARLY, request_timestamp=1_700_000_000,
                                     block=60_000_000, log_index=3)
        d = abi.decode_dispute_log(log)
        self.assertEqual(d["requester"], "0x" + "11" * 20)
        self.assertEqual(d["disputer"], "0x" + "33" * 20)
        self.assertEqual(d["identifier"], "YES_OR_NO_QUERY")
        self.assertTrue(d["too_early"])
        self.assertEqual(bytes.fromhex(d["ancillary_hex"][2:]), anc)
        self.assertEqual(d["question_id"], keccak_hex(anc))
        self.assertEqual((d["block"], d["log_index"]), (60_000_000, 3))

    def test_parse_ancillary(self):
        anc = abi.ancillary_for("Title, with comma?", "Line one.\n\nLine two.", "0x" + "Ab" * 20)
        p = abi.parse_ancillary(anc)
        self.assertEqual(p["title"], "Title, with comma?")
        self.assertEqual(p["description"], "Line one.\n\nLine two.")
        self.assertEqual(p["initializer"], "0x" + "ab" * 20)

    def test_price_mapping(self):
        self.assertEqual(abi.price_to_outcome(abi.ONE), 1.0)
        self.assertEqual(abi.price_to_outcome(abi.ONE // 2), 0.5)
        self.assertIsNone(abi.price_to_outcome(abi.TOO_EARLY))


class Text(unittest.TestCase):
    def test_strip_post_listing(self):
        base = "Resolves Yes if A happens by May 1, 2026. Otherwise No."
        appended = {
            "\n\nUpdate (May 3, 2026): a framework counts.": True,
            "\n\nUpdate (May 3, 2026):\n\nA signed framework will count as a deal.": True,
            " Update 3/5/2026: a framework counts.": True,
            "\nAdditional context: a framework counts.": True,
            "\n\nClarification: X counts.\n\nMore text.": True,
            "\n\nMarch 3, 2026: X counts.": True,
            " EDIT - B counts.": True,
            "\n\nNote: the title is a summary.": False,
            " Updates made by the question creator via the bulletin board count.": False,
        }
        for tail, removed in appended.items():
            out, n = T.strip_post_listing(base + tail)
            if removed:
                self.assertEqual(out, base, tail)
                self.assertGreater(n, 0, tail)
            else:
                self.assertEqual(T._squash(out), T._squash(base + tail), tail)
                self.assertEqual(n, 0, tail)
        self.assertEqual(T.strip_post_listing("A.\n\n\nB.")[1], 0)  # whitespace only
        self.assertEqual(T.strip_post_listing(float("nan")), ("", 0))

    def test_examples_and_flags(self):
        expect = {
            "1_peace_deal.txt": {"event_vs_announcement", "consensus_undefined",
                                 "undefined_term", "no_timezone"},
            "2_peace_deal_fixed.txt": set(),
            "3_asset_sale.txt": {"event_vs_announcement", "no_timezone", "no_source"},
            "4_btc_price.txt": set(),
            "5_mention.txt": {"mention_undefined", "no_timezone", "no_source"},
            "6_regulation.txt": {"legislative_stage", "undefined_term", "no_timezone",
                                 "no_source"},
        }
        boiler = "The resolution source for this market will be a consensus of credible reporting."
        self.assertTrue(T.flags("Q?", boiler)["flag_no_source"])  # boilerplate names no source
        self.assertTrue(T.flags("Q?", 'A deal. This market refers to the outcome "X".')
                        ["flag_undefined_term"])  # "refers to the outcome" defines nothing
        self.assertGreater(T.lexicon_counts('"Deal" means a signed agreement.')["definition"], 0)
        for name, want in expect.items():
            title, rules = lint.read_example(lint.EXAMPLES / name)
            got = {f["check"] for f in lint.lint(title, rules)}
            self.assertEqual(got, want, name)

    def test_category_and_template(self):
        self.assertEqual(T.category_of(float("nan"), float("nan"), float("nan")), "other")
        self.assertEqual(T.category_of(["NBA", float("nan")]), "sports")
        self.assertEqual(T.category_of(["Politics", "Iran"]), "geopolitics")
        self.assertEqual(T.category_of(["NBA"]), "sports")
        self.assertEqual(T.template_key("BTC above $100,000 on Oct 3, 2026?"),
                         T.template_key("BTC above $95,000 on Nov 9, 2026?"))


class FakeAPI(BaseHTTPRequestHandler):
    markets: list = []
    resolutions: dict = {}
    fail_once: set = set()
    calls: list = []
    cap = None

    def log_message(self, *a):
        pass

    def _send(self, code, body, headers=None):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        FakeAPI.calls.append((url.path, q))
        key = (url.path, json.dumps(q, sort_keys=True))
        if key in FakeAPI.fail_once:
            FakeAPI.fail_once.discard(key)
            return self._send(429, {"error": "slow down"}, {"Retry-After": "0"})
        if url.path == "/markets/keyset":
            limit = int(q["limit"][0])
            start = int(q.get("after_cursor", ["0"])[0])
            page = FakeAPI.markets[start: start + limit]
            body = {"markets": page}
            if len(page) == limit:
                body["next_cursor"] = str(start + limit)
            return self._send(200, body)
        if url.path == "/v2/resolutions":
            if "condition" in q:
                ids = q["condition"][0].split(",")
                rows = [FakeAPI.resolutions[c] for c in ids if c in FakeAPI.resolutions]
                return self._send(200, {"data": rows[: FakeAPI.cap] if FakeAPI.cap else rows})
            qid = q["question_id"][0]
            return self._send(200, {"data": [{"question_id": qid, "proposed_price": "1",
                                              "price": "0", "was_disputed": True}]})
        self._send(404, {"error": "no route"})


class Pullers(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        FakeAPI.markets = [{"id": str(i), "question": f"Q{i}?", "conditionId": f"0xC{i:03d}",
                            "questionID": f"0xQ{i:03d}", "description": "rules",
                            "tags": [{"label": "Politics"}],
                            "events": [{"id": "e1", "series": [{"slug": "s"}], "tags": []}]}
                           for i in range(7)]
        FakeAPI.resolutions = {f"0xc{i:03d}": {"condition_id": f"0xc{i:03d}",
                                               "was_disputed": i == 2, "reporter": "UMA_OO"}
                               for i in range(6)}
        FakeAPI.calls = []

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def client(self):
        return Client(self.base, min_interval=0, sleep=lambda s: None)

    def test_gamma_keyset_resume_and_retry(self):
        params = {"closed": ["true"], "limit": ["3"], "include_tag": ["true"],
                  "volume_num_min": ["10"], "end_date_min": ["2024-01-01T00:00:00Z"],
                  "after_cursor": ["3"]}
        FakeAPI.fail_once = {("/markets/keyset", json.dumps(params, sort_keys=True))}
        n1 = pull.pull_gamma(self.out, since="2024-01-01", until=None, min_volume=10,
                             client=self.client(), page_size=3, max_pages=1)
        self.assertEqual(n1, 3)
        n2 = pull.pull_gamma(self.out, since="2024-01-01", until=None, min_volume=10,
                             client=self.client(), page_size=3)
        self.assertEqual(n2, 7)
        rows = list(pull.read_jsonl(self.out / "gamma_markets.jsonl"))
        self.assertEqual(sorted(r["id"] for r in rows), [str(i) for i in range(7)])
        self.assertEqual(rows[0]["tags"], ["Politics"])
        self.assertEqual(rows[0]["events"][0]["series"], ["s"])
        self.assertTrue(json.loads((self.out / "gamma_state.json").read_text())["done"])
        with self.assertRaises(SystemExit):  # same folder, different query
            pull.pull_gamma(self.out, since="2025-01-01", until=None, min_volume=10,
                            client=self.client())

    def test_resolutions_capped_response_and_retry_of_missing(self):
        pull.pull_gamma(self.out, since="2024-01-01", until=None, min_volume=10,
                        client=self.client(), page_size=3)
        FakeAPI.cap = 2  # the fake returns at most two rows per call
        try:
            pull.pull_resolutions(self.out, client=self.client(), batch=5)
        finally:
            FakeAPI.cap = None
        rows = list(pull.read_jsonl(self.out / "resolutions.jsonl"))
        got = {r["condition_id"] for r in rows if not r.get("_missing")}
        self.assertEqual(got, {f"0xc{i:03d}" for i in range(6)})  # all six known ones
        FakeAPI.resolutions["0xc006"] = {"condition_id": "0xc006", "was_disputed": False}
        before = len(FakeAPI.calls)
        pull.pull_resolutions(self.out, client=self.client(), batch=5)  # retries the missing
        self.assertEqual(len(FakeAPI.calls), before + 1)
        api = D.load_api(self.out)
        self.assertTrue(api.loc["0xc006", "api_found"])

    def test_resolutions_batches_missing_and_questions(self):
        pull.pull_gamma(self.out, since="2024-01-01", until=None, min_volume=10,
                        client=self.client(), page_size=3)
        pull.pull_resolutions(self.out, client=self.client(), batch=4, questions=True)
        rows = list(pull.read_jsonl(self.out / "resolutions.jsonl"))
        self.assertEqual(len(rows), 7)
        self.assertEqual(sum(bool(r.get("_missing")) for r in rows), 1)
        FakeAPI.resolutions.pop("0xc005")  # still missing on the next run: asked again, once
        qrows = list(pull.read_jsonl(self.out / "resolutions_q.jsonl"))
        self.assertEqual([r["_question_id"] for r in qrows], ["0xq002"])
        before = len(FakeAPI.calls)
        pull.pull_resolutions(self.out, client=self.client(), batch=4)
        self.assertEqual(len(FakeAPI.calls), before + 1)  # only the one missing condition


class FakeRPC:
    """eth_getLogs over a list of logs, refusing spans wider than ``limit`` blocks."""

    def __init__(self, logs, limit, latest):
        self.logs, self.limit, self.latest, self.calls = logs, limit, latest, 0

    def call(self, method, params):
        self.calls += 1
        if method == "eth_blockNumber":
            return hex(self.latest)
        if method == "eth_getBlockByNumber":
            return {"timestamp": hex(1_700_000_000 + 2 * int(params[0], 16))}
        f = params[0]
        a, b = int(f["fromBlock"], 16), int(f["toBlock"], 16)
        if b - a + 1 > self.limit:
            raise RPCError("block range is too wide", -32005)
        return [x for x in self.logs if a <= int(x["blockNumber"], 16) <= b]

    def block_number(self):
        return self.latest

    def block_timestamp(self, n):
        return 1_700_000_000 + 2 * n

    def block_at(self, ts, lo=1, hi=None):
        return max(1, (ts - 1_700_000_000) // 2)


class FlakyRPC(FakeRPC):
    """Like FakeRPC, but every fifth eth_getLogs call fails with a rate limit."""

    def call(self, method, params):
        if method == "eth_getLogs":
            self.n_logs = getattr(self, "n_logs", 0) + 1
            if self.n_logs % 5 == 0:
                raise RPCError("rate limit exceeded, retry later", -32005)
        return super().call(method, params)


class Chain(unittest.TestCase):
    def test_rate_limits_do_not_shrink_the_scan(self):
        rpc = FlakyRPC([], limit=10_000_000, latest=30_000_000)
        n = pull.scan_logs(rpc, from_block=1, to_block=30_000_000, topics=[], chunk=100_000,
                           on_logs=lambda logs: None, sleep=lambda s: None)
        self.assertEqual(n, 0)
        self.assertLess(rpc.calls, 60)

    def test_writer_cuts_a_partial_last_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.jsonl"
            path.write_text('{"a": 1}\n{"a": 2}\n{"a": ')
            w = pull.JsonlWriter(path)
            w.write({"a": 3})
            w.close()
            self.assertEqual([r["a"] for r in pull.read_jsonl(path)], [1, 2, 3])

    def test_adaptive_scan_collects_each_log_once_and_resumes(self):
        rng = np.random.default_rng(1)
        blocks = sorted(rng.integers(1_000, 900_000, 60).tolist())
        logs = [abi.encode_dispute_log(requester="0x" + "11" * 20, proposer="0x" + "22" * 20,
                                       disputer="0x" + "33" * 20, ancillary=f"q {i}".encode(),
                                       proposed_price=abi.ONE, request_timestamp=1, block=b,
                                       log_index=i) for i, b in enumerate(blocks)]
        rpc = FakeRPC(logs, limit=37_000, latest=1_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            pull.pull_chain(out, rpc_url="", from_block=1, to_block=500_000, rpc=rpc)
            first = list(pull.read_jsonl(out / "dispute_logs.jsonl"))
            self.assertEqual(len(first), sum(b <= 500_000 for b in blocks))
            state = json.loads((out / "chain_state.json").read_text())
            state.pop("done")
            state["to_block"] = 1_000_000
            (out / "chain_state.json").write_text(json.dumps(state))
            pull.pull_chain(out, rpc_url="", rpc=rpc)
            got = [r["log_index"] for r in pull.read_jsonl(out / "dispute_logs.jsonl")]
            self.assertEqual(sorted(got), list(range(60)))
            anchors = json.loads((out / "block_anchors.json").read_text())
            self.assertGreaterEqual(len(anchors), 41)


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dirs = {}
        for name, kw in {"words": dict(text_effect=1.0, canary=0.0),
                         "leak": dict(text_effect=0.0, canary=0.8)}.items():
            d = Path(cls.tmp.name) / name
            synth.generate(synth.Spec(n_events=2500, seed=7, **kw), d)
            cls.dirs[name] = d

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _pop(self, name):
        df, audit = D.assemble(self.dirs[name])
        mask, _ = D.population(df, min_volume=10_000, since="2024-01-01")
        return df, audit, D.add_template_history(df[mask])

    def test_join_and_labels_agree(self):
        df, audit, _ = self._pop("words")
        self.assertEqual(audit["unmatched"], synth.Spec().foreign_logs)
        both = df[["api_was_disputed", "chain_disputed", "gamma_disputed"]].dropna()
        self.assertTrue((both.nunique(axis=1) == 1).all())
        self.assertGreater(audit["joined_by_text"], 0)  # neg-risk markets need the text join

    def test_text_join_needs_matching_rules_and_time(self):
        markets = pd.DataFrame({
            "question": ["Will X say 'crypto' this week?", "Will X say 'crypto' this week?"],
            "description": ["Rules for week 40.", "Rules for week 52."],
            "questionID": ["0xa", "0xb"],
            "created": pd.to_datetime(["2026-01-01", "2026-03-01"], utc=True)})
        per_q = pd.DataFrame([{"question_id": "0xq", "chain_n": 1,
                               "listing_title": "Will X say 'crypto' this week?",
                               "listing_description": "Rules for week 52.",
                               "chain_request_ts": pd.Timestamp("2024-03-01", tz="UTC")}])
        out, stats = D.join_chain(markets, per_q)  # right rules, 2 years off: no match
        self.assertEqual(stats["joined_by_text"], 0)
        per_q.loc[0, "chain_request_ts"] = pd.Timestamp("2026-03-02", tz="UTC")
        out, stats = D.join_chain(markets, per_q)
        self.assertEqual(list(out.index), [1])
        per_q.loc[0, "listing_description"] = "Different rules."
        self.assertEqual(D.join_chain(markets, per_q)[1]["joined_by_text"], 0)

    def test_scan_range_is_not_evidence_of_uma(self):
        df, _, _ = self._pop("words")
        df = df.copy()
        cl = df["api_reporter"].eq("CHAINLINK")
        self.assertGreater(cl.sum(), 0)
        for col in ("api_reporter", "api_was_disputed"):
            df.loc[cl, col] = pd.NA if col == "api_was_disputed" else None
        mask, _ = D.population(df, min_volume=10_000, since="2024-01-01")
        self.assertEqual(int((mask & cl).sum()), 0)

    def test_api_rows_for_one_condition_are_combined(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resolutions.jsonl"
            rows = [{"condition_id": "0xAA", "status": "resolved", "was_disputed": False,
                     "reporter": "UMA_OO"},
                    {"condition_id": "0xaa", "status": "resolved", "was_disputed": True},
                    {"condition_id": "0xbb", "_missing": True}]
            path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            api = D.load_api(Path(tmp))
            self.assertTrue(api.loc["0xaa", "api_was_disputed"])
            self.assertEqual(api.loc["0xaa", "api_rows"], 2)
            self.assertFalse(api.loc["0xbb", "api_found"])
            self.assertTrue(pd.isna(api.loc["0xbb", "api_was_disputed"]))

    def test_time_split_has_no_overlap(self):
        _, _, pop = self._pop("words")
        tr, te = M.time_split(pop, "2026-04-01")
        self.assertFalse((tr & te).any())
        t = pd.Timestamp("2026-04-01", tz="UTC")
        self.assertTrue((pop[tr]["closed_time"] < t).all())
        self.assertTrue((pop[te]["created"] >= t).all())

    def test_template_history_uses_only_earlier_resolutions(self):
        t = pd.Timestamp("2025-01-01", tz="UTC")
        df = pd.DataFrame({
            "series": ["s"] * 4, "rules": ["r"] * 4,
            "created": [t, t + pd.Timedelta(days=1), t + pd.Timedelta(days=10),
                        t + pd.Timedelta(days=30)],
            "closed_time": [t + pd.Timedelta(days=5), t + pd.Timedelta(days=40),
                            t + pd.Timedelta(days=20), t + pd.Timedelta(days=31)],
            "disputed": pd.array([True, True, False, False], dtype="boolean")})
        h = D.add_template_history(df, strength=0.0001)
        # market 3 listed on day 30: only markets 0 (day 5) and 2 (day 20) had resolved
        self.assertAlmostEqual(h["hist_rate"].iloc[3], 0.5, places=3)
        self.assertAlmostEqual(h["hist_n"].iloc[3], np.log1p(2))
        self.assertEqual(h["hist_n"].iloc[0], 0.0)

    def _fit(self, pop, rules_col="rules"):
        p = M.prepare(pop, rules_col=rules_col)
        tr, te = M.time_split(p, "2026-04-01")
        y_tr = p[tr]["disputed"].astype(int).to_numpy()
        y_te = p[te]["disputed"].astype(int).to_numpy()
        out = {n: M.RiskModel(M.SPECS[n], C=0.3, min_df=3).fit(p[tr], y_tr).predict(p[te])
               for n in ("M0", "M2")}
        return y_te, out

    def test_planted_words_are_found(self):
        _, _, pop = self._pop("words")
        y, s = self._fit(pop)
        self.assertGreater(M.ap(y, s["M2"]), M.ap(y, s["M0"]) + 0.1)

    def test_stripping_stops_the_clarification_leak(self):
        _, _, pop = self._pop("leak")
        y, s = self._fit(pop)
        y_raw, s_raw = self._fit(pop, rules_col="description")
        self.assertLess(M.ap(y, s["M2"]) - M.ap(y, s["M0"]), 0.08)
        self.assertGreater(M.ap(y_raw, s_raw["M2"]), M.ap(y, s["M2"]) + 0.15)

    def test_metrics(self):
        y = np.array([1, 0, 0, 1, 0, 0, 0, 0, 0, 0] * 10)
        s = np.linspace(1, 0, 100)
        self.assertAlmostEqual(M.recall_at(y, s, frac=0.1), 2 / 20)
        self.assertAlmostEqual(M.recall_at(y, y.astype(float), frac=0.2), 1.0)
        h = M.paired_bootstrap(y, y + 0.0, s, np.arange(100), lambda a, b, w: M.ap(a, b, w),
                               n_boot=200)
        self.assertGreater(h["lo"], 0)

    def test_report_runs_and_model_feeds_the_linter(self):
        from resolution import run
        with tempfile.TemporaryDirectory() as tmp:
            res = run.run(self.dirs["words"], Path(tmp), split="2026-04-01", min_volume=10_000,
                          since="2024-01-01", n_boot=60, min_df=3, seed=0,
                          synthetic_note="test", log=lambda *a: None)
            self.assertIn("H1", res)
            self.assertTrue((Path(tmp) / "REPORT.md").exists())
            bundle = lint.load_model(Path(tmp) / "model.pkl")
            title, rules = lint.read_example(lint.EXAMPLES / "1_peace_deal.txt")
            r = lint.score(bundle, title, rules, category="geopolitics")
            self.assertTrue(0 < r["risk"] < 1)
            self.assertTrue(0 <= r["percentile"] <= 100)


if __name__ == "__main__":
    unittest.main()
