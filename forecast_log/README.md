# Forecast log

My probability for real Kalshi and Polymarket contracts, recorded next to the
market's own quote at the same moment, then scored against the outcome.

## Rules

1. **One forecast per market**, made while the market is open. No edits after
   the fact; a forecast I regret stays in the log.
2. **The market price is fetched, not typed.** `add` reads the live bid and ask
   from the venue's public API, so the comparison price is the one that existed
   when I made the call.
3. **Commit before close.** Every forecast goes into a git commit before its
   market closes. `verify` checks this from the git history, so the timestamps
   do not depend on trusting me.
4. **Probabilities stay in [0.01, 0.99]**, and the quote must be two-sided and
   no wider than 20¢, so the market price means something.
5. **Every resolved forecast counts.** Voided markets are reported but not
   scored.

No account, API key or money is involved. The tool only reads public market data.

## Workflow

```bash
# record a forecast (Kalshi ticker or Polymarket slug from the market's URL)
python forecast_log/pmlog.py add --venue kalshi --market KXEXAMPLE-26NOV --prob 0.62 \
    --note "one line on why I disagree with 0.55"
git add forecast_log/forecasts.csv && git commit -m "Forecast F0001"

# later
python forecast_log/pmlog.py resolve      # pulls outcomes from the venues
python forecast_log/pmlog.py verify       # every forecast committed before close?
python forecast_log/pmlog.py score --plot forecast_log/calibration.png
```

`--model-prob` stores a model's forecast next to mine (for example Averon's),
so the same events can be scored three ways: me, the model and the market.
For a market with no API, `--venue manual` takes `--question`, `--market-prob`
and `--close` by hand. Those rows are marked as manual.

## What `score` reports

| Metric | Meaning |
|---|---|
| Brier score, me vs market | Mean squared error of the probability against the 0/1 outcome, on exactly the same events |
| Brier skill vs market | `1 − Brier_me / Brier_market`; positive means I beat the market |
| Paired Brier difference with 95% bootstrap CI | Whether the difference is real or noise at this sample size |
| Log loss | Punishes confident misses harder than Brier |
| Reliability / resolution | Murphy decomposition: am I calibrated, and do my forecasts separate events that happen from those that don't |
| Paper P&L | One contract traded at the quote I saw whenever my probability was outside the bid/ask, no fees. Agreement with the market is free; acting on disagreement has to clear the spread |
| Calibration table and plot | Forecast bins vs observed frequency, for me and the market |

With fewer than about 100 resolved forecasts the decomposition is noisy, so the
paired difference and its interval are the numbers to read first.

## Columns of `forecasts.csv`

`forecast_id, created_utc, venue, market, question, my_prob, model_prob,
market_mid, market_bid, market_ask, market_last, close_utc, note, outcome,
resolved_utc`. `outcome` is `1`, `0`, `void` or empty while open.
