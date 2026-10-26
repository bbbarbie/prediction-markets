"""Tests for the leakage toolkit. Run from the portfolio root:

    python3 -m unittest discover -s leakage/tests -t . -v
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from leakage import data, families, kalshi_pull, metrics, mirror, run, spread, synth

HOUR = 3600
T0 = 1_780_000_000          # an arbitrary reveal-time anchor (2026)


def iso(ts: int) -> str:
    return pd.Timestamp(ts, unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def tiny(markets, trades, events=None):
    """markets: (ticker, event, result, close_ts); trades: (ticker, ts, price, side, count)."""
    m = pd.DataFrame([{"ticker": t, "event_ticker": e, "result": r, "close_time": iso(c),
                       "title": "Will the named person attend?"} for t, e, r, c in markets])
    t = pd.DataFrame([{"ticker": k, "created_time": iso(ts), "yes_price": p, "taker_side": s,
                       "count": c, "trade_id": f"{k}-{i}"}
                      for i, (k, ts, p, s, c) in enumerate(trades)])
    return data.normalise(m, t, events)


class Families(unittest.TestCase):
    def test_series_rules(self):
        cases = {"KXMENTIONTRUMP": ("scheduled_reveal", "mention"),
                 "KXOSCARPIC": ("scheduled_reveal", "award"),
                 "KXNBAGAME": ("continuous_public", "sports"),
                 "KXCPI": ("scheduled_data", "release"),
                 "KXBTCD": ("continuous_public", "price_level"),
                 "KXHIGHNY": ("continuous_public", "weather"),
                 "KXSENATEPA": ("elections", "election")}
        for series, want in cases.items():
            self.assertEqual(families.classify(series), want, series)

    def test_title_fallback_and_overrides(self):
        self.assertEqual(families.classify("ODD", "Will Bezos attend the Super Bowl?"),
                         ("scheduled_reveal", "named_person"))
        self.assertEqual(families.classify("ODD", "Nothing to see"), ("other", "other"))
        self.assertEqual(families.classify("ODD", "", {"ODD": ("elections", "x")}),
                         ("elections", "x"))

    def test_script_type(self):
        self.assertEqual(families.script_type("What will Trump say during the State of the Union?"),
                         "scripted")
        self.assertEqual(families.script_type("What will Powell say at the press conference?"),
                         "unscripted")
        self.assertEqual(families.script_type("What will he say?"), "unknown")


class Loading(unittest.TestCase):
    def test_cents_and_dollars_normalise_alike(self):
        m = pd.DataFrame([{"ticker": "KXA-1-X", "event_ticker": "KXA-1", "result": "yes",
                           "close_time": iso(T0)}])
        cents = pd.DataFrame([{"ticker": "KXA-1-X", "created_time": iso(T0 - 60), "yes_price": 42,
                               "taker_side": "yes", "count": 3, "trade_id": "a"}])
        dollars = pd.DataFrame([{"ticker": "KXA-1-X", "created_time": iso(T0 - 60),
                                 "yes_price_dollars": "0.4200", "taker_side": "yes",
                                 "count_fp": "3.00", "trade_id": "a"}])
        a = data.normalise(m, cents).trades
        b = data.normalise(m, dollars).trades
        self.assertAlmostEqual(a["price"][0], 0.42)
        pd.testing.assert_frame_equal(a, b)
        self.assertEqual(a["side"][0], 1)

    def test_unsettled_dropped_and_reveal_is_first_close(self):
        ds = tiny([("KXSAY-E-A", "KXSAY-E", "yes", T0), ("KXSAY-E-B", "KXSAY-E", "no", T0 + HOUR),
                   ("KXSAY-E-C", "KXSAY-E", "", T0)], [])
        self.assertEqual(len(ds.markets), 2)
        self.assertTrue((ds.markets["reveal_ts"] == T0).all())

    def test_mutually_exclusive_inferred_only_for_awards(self):
        award = [(f"KXOSCAR-E-{i}", "KXOSCAR-E", "yes" if i == 0 else "no", T0) for i in range(3)]
        mention = [(f"KXSAY-E-{i}", "KXSAY-E", "yes" if i == 0 else "no", T0) for i in range(3)]
        ds = tiny(award + mention, [])
        me = ds.markets.groupby("event_ticker")["mutually_exclusive"].first()
        self.assertTrue(me["KXOSCAR-E"])
        self.assertFalse(me["KXSAY-E"])
        api = pd.DataFrame([{"event_ticker": "KXSAY-E", "mutually_exclusive": "True"}])
        self.assertTrue(tiny(mention, [], api).markets["mutually_exclusive"].all())


class LeakShare(unittest.TestCase):
    def test_price_before_is_strict(self):
        ts, p = np.array([10, 20, 30]), np.array([0.1, 0.2, 0.3])
        got = metrics.price_before(ts, p, [5, 10, 11, 30, 31])
        np.testing.assert_allclose(got, [np.nan, np.nan, 0.1, 0.2, 0.3])

    def test_ratio_by_cluster(self):
        R, se = metrics.ratio_by_cluster([1, 2, 3], [2, 2, 2])
        self.assertAlmostEqual(R, 1.0)
        u = np.array([1, 2, 3]) - 1.0 * np.array([2, 2, 2])
        self.assertAlmostEqual(se, np.sqrt(3 / 2 * np.sum(u ** 2)) / 6)

    def _two_markets(self, end_price):
        trades = []
        for k, (y, start) in enumerate([("yes", 0.4), ("no", 0.7)]):
            tick = f"KXATTEND-E{k}-X"
            trades += [(tick, T0 - 30 * HOUR, start, "yes", 1),
                       (tick, T0 - 3 * HOUR, end_price[k], "no", 1)]
        markets = [(f"KXATTEND-E{k}-X", f"KXATTEND-E{k}", y, T0)
                   for k, y in enumerate(["yes", "no"])]
        return tiny(markets, trades)

    def test_zero_when_prices_do_not_move_one_when_resolved(self):
        w = (metrics.PRE_REVEAL,)
        flat = metrics.leak_share_table(metrics.window_prices(self._two_markets([0.4, 0.7]), w), reps=50)
        row = flat[flat["window"] == "24h-1h"].iloc[0]
        self.assertAlmostEqual(row["leak_share"], 0.0)
        solved = metrics.leak_share_table(metrics.window_prices(self._two_markets([0.99, 0.01]), w),
                                          reps=50)
        row = solved[solved["window"] == "24h-1h"].iloc[0]
        self.assertGreater(row["leak_share"], 0.99)


    def test_stale_start_prices_are_dropped(self):
        ds = tiny([("KXATTEND-E-X", "KXATTEND-E", "yes", T0)],
                  [("KXATTEND-E-X", T0 - 60 * HOUR, 0.4, "yes", 1),    # 36h before the window opens
                   ("KXATTEND-E-X", T0 - 3 * HOUR, 0.9, "yes", 1)])
        w = (metrics.PRE_REVEAL,)
        self.assertEqual(len(metrics.window_prices(ds, w)), 1)
        self.assertAlmostEqual(metrics.window_prices(ds, w)["start_age_h"].iloc[0], 36.0)
        self.assertEqual(len(metrics.window_prices(ds, w, max_start_age_hours=12)), 0)


class Trades(unittest.TestCase):
    def test_markout_and_legs(self):
        ds = tiny([("KXATTEND-E-X", "KXATTEND-E", "yes", T0)],
                  [("KXATTEND-E-X", T0 - HOUR * 2, 0.30, "yes", 2),
                   ("KXATTEND-E-X", T0 - HOUR * 3, 0.80, "no", 1)])
        tt = metrics.trade_table(ds).sort_values("ts")
        np.testing.assert_allclose(tt["markout"], [-0.2, 0.7])
        self.assertEqual(list(tt["leg"]), ["no_longshot", "yes_longshot"])
        self.assertEqual(list(metrics.leg_of(np.array([0.5, 0.9, 0.9]), np.array([1, 1, -1]))),
                         ["yes_middle", "yes_favorite", "no_longshot"])

    def test_effective_half_spread(self):
        hs = metrics.effective_half_spread(np.array([0, 10, 20, 2000]), np.array([.52, .48, .52, .5]),
                                           np.array([1, -1, 1, -1]))
        self.assertTrue(np.isnan(hs[0]) and np.isnan(hs[1]))
        self.assertAlmostEqual(hs[2], 0.02)
        self.assertTrue(np.isnan(hs[3]))           # both prints older than 10 minutes


class Mirror(unittest.TestCase):
    def test_basket_earns_what_the_long_shot_earns(self):
        yes, basket = mirror.mirror_profits([0.5, 0.3, 0.2], winner=1)
        self.assertAlmostEqual(yes, 0.7)
        self.assertAlmostEqual(basket, 0.7)
        yes, basket = mirror.mirror_profits([0.5, 0.3, 0.25], winner=1)   # 5c overround
        self.assertAlmostEqual(basket - yes, 0.05)

    def test_logistic_recovers_a_known_curve(self):
        rng = np.random.default_rng(0)
        p = rng.uniform(0.02, 0.98, 20000)
        y = (rng.random(20000) < mirror.sigmoid(0.3 + 1.2 * mirror.logit(p))).astype(float)
        a, b = mirror.fit_logistic(p, y)
        self.assertAlmostEqual(a, 0.3, delta=0.08)
        self.assertAlmostEqual(b, 1.2, delta=0.08)

    def test_bursts_split_on_gaps(self):
        parts = mirror.bursts_of(np.array([0, 5, 30, 200, 210]), 60)
        self.assertEqual([list(p) for p in parts], [[0, 1, 2], [3, 4]])

    def _run(self, leak_rate, style, seed):
        ds, _ = synth.dataset([synth.Spec(family="scheduled_reveal", n_events=240, me_share=0.6,
                                          leak_rate=leak_rate, leak_style=style, seed=seed)])
        tt = metrics.trade_table(ds)
        cal = mirror.cross_fit_calibration(ds)
        return (mirror.skip_test(mirror.skip_bursts(ds, tt, cal), n_null=2000),
                mirror.longshot_test(tt, cal, n_null=2000))

    def test_skip_test_quiet_on_clean_data_and_on_yes_insiders(self):
        for rate, style, seed in ((0.0, "mixed", 71), (0.15, "yes", 72)):
            skip, _ = self._run(rate, style, seed)
            self.assertGreater(skip["p_value"], 0.05, (rate, style))

    def test_skip_test_finds_basket_insiders_and_long_shot_test_does_not(self):
        skip, long_shot = self._run(0.15, "basket", 73)
        self.assertLess(skip["p_value"], 0.01)
        self.assertGreater(skip["hit_ratio"], 1.1)
        self.assertGreater(long_shot["p_value"], 0.05)


class Spread(unittest.TestCase):
    def test_half_spread_is_half_the_insider_share_at_fifty_cents(self):
        for mu in (0.01, 0.05, 0.2):
            self.assertAlmostEqual(spread.gm_half_spread(0.5, mu), mu / 2)
        self.assertAlmostEqual(spread.gm_half_spread(0.3, 0.0, b=0.6), 0.0)

    def test_implied_mu_inverts(self):
        for q in (0.1, 0.5):
            h = spread.gm_half_spread(q, 0.04)
            self.assertAlmostEqual(spread.implied_mu(h, q), 0.04, places=6)
        self.assertEqual(spread.implied_mu(-0.01), 0.0)


class Pull(unittest.TestCase):
    def test_trade_rows_accept_both_price_formats(self):
        a = kalshi_pull.trade_row({"trade_id": "1", "ticker": "T", "created_time": "x",
                                   "yes_price_dollars": "0.4250", "count_fp": "10.00",
                                   "taker_side": "no"})
        b = kalshi_pull.trade_row({"trade_id": "2", "ticker": "T", "created_time": "x",
                                   "yes_price": 43, "count": 10, "taker_side": "yes"})
        self.assertEqual((a["yes_price"], a["count"]), ("0.4250", "10.00"))
        self.assertEqual((b["yes_price"], b["count"]), ("0.4300", 10))
        self.assertEqual(kalshi_pull.parse_ts("2026-01-01T00:00:00.123456789Z"), 1767225600)

    def test_pull_uses_both_tiers_and_resumes(self):
        cut = 1767225600                                    # 2026-01-01
        old = {"ticker": "KXOSCAR-25-A", "event_ticker": "KXOSCAR-25", "result": "yes",
               "open_time": "2025-01-01T00:00:00Z", "close_time": "2025-03-02T00:00:00Z",
               "volume": 500}
        new = {"ticker": "KXOSCAR-26-A", "event_ticker": "KXOSCAR-26", "result": "no",
               "open_time": "2026-01-10T00:00:00Z", "close_time": "2026-03-15T00:00:00Z",
               "volume_fp": "800.00"}
        calls = []

        def fake_get(path, params=None, **_):
            calls.append((path, (params or {}).get("ticker")))
            if path == "/historical/cutoff":
                return {"market_settled_ts": "2026-01-01T00:00:00Z",
                        "trades_created_ts": "2026-01-01T00:00:00Z"}
            if path == "/events":
                return {"events": [{"event_ticker": "KXOSCAR-25", "title": "Best Picture",
                                    "mutually_exclusive": True}]}
            if path == "/markets":
                return {"markets": [new]}
            if path == "/historical/markets":
                return {"markets": [old]}
            if path == "/markets/trades":
                return {"trades": [{"trade_id": "n1", "ticker": params["ticker"],
                                    "created_time": "2026-02-01T00:00:00Z",
                                    "yes_price_dollars": "0.30", "count_fp": "5", "taker_side": "yes"}]}
            if path == "/historical/trades":
                return {"trades": [{"trade_id": "o1", "ticker": params["ticker"],
                                    "created_time": "2025-02-01T00:00:00Z",
                                    "yes_price": 60, "count": 2, "taker_side": "no"}]}
            raise AssertionError(path)

        with tempfile.TemporaryDirectory() as d, mock.patch.object(kalshi_pull, "_get", fake_get):
            stats = kalshi_pull.pull(["KXOSCAR"], Path(d), min_volume=100)
            self.assertEqual(stats["markets"], 2)
            self.assertEqual(json.loads((Path(d) / "cutoff.json").read_text())["trades_created_ts"], cut)
            with open(Path(d) / "trades.csv") as f:
                trades = list(csv.DictReader(f))
            tiers = {t["ticker"]: t["tier"] for t in trades}
            self.assertEqual(tiers, {"KXOSCAR-25-A": "historical", "KXOSCAR-26-A": "live"})
            n_calls = len(calls)
            again = kalshi_pull.pull(["KXOSCAR"], Path(d), min_volume=100)
            self.assertEqual(again["markets"], 0)
            self.assertNotIn("/markets/trades", [c[0] for c in calls[n_calls:]])
            ds = data.load(d)
            self.assertEqual(len(ds.markets), 2)
            self.assertEqual(sorted(ds.trades["side"]), [-1, 1])


class EndToEnd(unittest.TestCase):
    def test_report_on_synthetic_data(self):
        ds, truth = synth.dataset([synth.Spec(n_events=80, leak_rate=0.2, seed=5),
                                   synth.Spec(family="continuous_public", n_events=60, seed=6)])
        with tempfile.TemporaryDirectory() as d:
            text = run.build_report(ds, Path(d), split_date="2026-02-15", reps=50, truth=truth)
            self.assertIn("## 2. Leak share before the reveal", text)
            self.assertTrue((Path(d) / "leak_share.png").stat().st_size > 10_000)
            leak = pd.read_csv(Path(d) / "leak_share.csv")
            self.assertEqual(set(leak["family"]), {"scheduled_reveal", "continuous_public"})


if __name__ == "__main__":
    unittest.main()
