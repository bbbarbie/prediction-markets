# How well calibrated are Kalshi and Polymarket prices?

*Data snapshot 2026-10-24; markets closing 2026-08-25 to 2026-10-21. Every number below is
produced by `analyze.py`. All tables, with more horizons and categories, are in
[`results/tables.md`](results/tables.md). The fitted parameters are in
[`results/fit.json`](results/fit.json).*

## Findings

Using prices 24 hours before close, I found no favorite-longshot bias on either venue that is
distinguishable from zero.

- **Kalshi, 24 h** (7,769 markets in 2,389 events): alpha = 0.01 [-0.06, 0.08] and
  beta = 0.99 [0.94, 1.04]. The direct table agrees. Contracts priced under 10% averaged
  2.9% and resolved YES 3.0% of the time (+0.1 pp [-0.5, +0.7]). Contracts priced over 90%
  averaged 96.9% and resolved YES 96.1% of the time (-0.8 pp [-2.3, +0.5]).
- **Polymarket, 24 h** (4,821 markets in 1,185 events): alpha = 0.12 [0.03, 0.21] and
  beta = 1.07 [1.005, 1.15]. Taken alone, that is mild compression toward 0.5 (beta > 1).
  The result is not robust. It comes from markets that closed because the outcome happened
  ("triggered" closes; see Method). For those, "24 h before close" means 24 h before the
  event, and prices that close to an outcome-driven close look too timid in hindsight.
  Without them (3,968 markets, 997 events), the fit is alpha = -0.05 [-0.15, 0.04] and
  beta = 1.01 [0.93, 1.09].
- **1 h before close** there is a small, significant beta > 1 on both venues: Kalshi 1.06
  [1.02, 1.10] and Polymarket 1.13 [1.06, 1.22]. On Kalshi it comes from the tails.
  4,816 markets traded at the 1-cent floor; they resolved YES 0.27% of the time.
  - On Kalshi, if you keep only prices in [0.02, 0.98], beta falls to 0.97 [0.92, 1.02].
    The "longshots are overpriced" pattern (bucket under 10%: 2.0% priced, 1.3% realized,
    -0.6 pp [-0.9, -0.3]) is therefore mostly the minimum tick plus fees. It is not a broad
    bias.
  - Kalshi sports, which are in play at that point, go the other way: beta = 0.89
    [0.84, 0.95], so prices are slightly too extreme.
- **Resolution dominates the Brier score.** Reliability terms are at most 0.001 at 24 h
  and 1 h on both venues (0.007 for Polymarket at 7 d), against Brier scores of
  0.08–0.13.

**For a simulator.** The defensible "real miscalibration shape" at 24 h is close to the
identity on both venues. Use beta between 0.94 and 1.09 and alpha between -0.15 and 0.08.
In `fit.json → simulator`, `logit_bias` and `logit_slope` give the price as a function of
the true probability q: logit(price) = logit_bias + logit_slope · logit(q).

## Data

**Endpoints (all public, unauthenticated, read-only).**

Kalshi (`https://api.elections.kalshi.com/trade-api/v2`):

- `GET /series`: series → category.
- `GET /events?status=settled`: settled events, newest first.
- `GET /markets?series_ticker=&status=settled&min_close_ts=&max_close_ts=&mve_filter=exclude`.
- `GET /markets/candlesticks?market_tickers=…&period_interval=60`: batch hourly candles,
  at most 100 markets and 10,000 candles per call.

Kalshi's `/historical/cutoff` reported 2026-08-24, which is why the window starts on
2026-08-25.

Polymarket:

- Gamma `GET /events/keyset?closed=true&volume_min=1000`. The response nests full market
  objects. It is paged with `after_cursor`, and `exclude_tag_id` drops sports (tag 1) and
  5-minute "up-or-down" crypto (tag 102127).
- CLOB `GET /prices-history?market=<YES token>&startTs&endTs&fidelity=60`.

The Gamma `/markets` listing could not exclude tags and was dominated by up-or-down and
over/under markets, so I abandoned it. `interval=max` returns nothing for closed markets.

**Collection.**

- Rate: at most 2 requests/s to Kalshi and 3/s to Polymarket (5/s in total).
- Every response is cached gzip-compressed in `data/raw/` (git-ignored).
- 4,307 Kalshi and 5,710 Polymarket requests, with no 429s or retries. The whole run took
  about 55 minutes including probing.
- A second run with `--offline` made zero network requests and reproduced every
  intermediate file byte for byte.

**Sampling.** Only binary YES/NO markets were kept. Sampling is by event (the unit of
correlation), stratified by category with quotas proportional to √(eligible count), and
capped at 10 markets per event and 150 per series (seed 20261024).

- **Kalshi.** I listed 2,400 of 4,127 active series, chosen with the same rule over
  categories. Multivariate (KXMVE) and 15-minute series were skipped up front. 112 series
  had more than 1,000 settled markets in the window; for those I kept only the first page.
- **Polymarket.** I took all non-sports events. For sports, I took every closed sports event
  whose end date falls in ten one-day slices spaced six days apart (6,446 events). I did not
  page all ~250k sports and crypto markets.

**Filters**, with counts from `results/dataset_summary.json`.

| Kalshi step | remaining | removed |
|---|---|---|
| markets listed (in window, server-side `mve_filter=exclude`) | 286,312 | |
| not multivariate (client check) | 286,312 | 0 |
| `market_type == binary` | 286,312 | 0 |
| settled YES/NO (scalar/void results dropped) | 282,822 | 3,490 |
| volume ≥ 1,000 contracts | 135,932 | 146,890 |
| stratified sample | 20,000 (4,961 events, 1,010 series) | 115,932 |
| price at 7 d / 24 h / 1 h | 1,472 / 7,769 / 16,321 | |

| Polymarket step | remaining | removed |
|---|---|---|
| markets nested in listed events | 311,128 | |
| outcomes exactly Yes/No | 197,657 | 113,471 |
| UMA `resolved` and `outcomePrices` exactly 1/0 | 196,268 | 1,389 |
| reference close in window | 133,384 | 62,884 |
| volume ≥ $1,000 | 46,685 | 86,699 |
| stratified sample | 5,500 (1,389 events, 622 series) | 41,185 |
| price at 7 d / 24 h / 1 h | 1,724 / 4,821 / 5,160 | |

Most markets lost at a horizon simply did not exist yet. Daily sports, weather and financial
markets open less than 24 h before they close.

- **Kalshi drops at 24 h.** 10,417 had no trade at or before the horizon; 1,814 had a last
  trade more than 24 h old.
- **Kalshi drops at 1 h.** 2,031 had no trade; 1,648 were stale.

**Volume threshold.** Below about 1,000 contracts (about $1k notional on Polymarket), a
couple of trades of a few dozen contracts set the "price" for the whole market. The
threshold removes about half the Kalshi markets and about two thirds of Polymarket's YES/NO
markets. A 10× threshold is reported as a sensitivity check.

**Sample by category** (Kalshi / Polymarket):

| category | Kalshi | Polymarket |
|---|---|---|
| sports | 7,948 | 861 |
| economics and finance | 3,592 | 687 |
| weather | 2,907 | 1,640 |
| culture and mentions | 2,638 | 635 |
| science and tech | 1,230 | 361 |
| politics | 1,166 | 558 |
| crypto | 519 | 755 |

## Method

**Reference close.**

- **Kalshi:** `close_time`. Kalshi halts trading there. Sports markets close when the result
  is declared, so the 1 h price is an in-play price.
- **Polymarket:** the earliest of `endDate`, `gameStartTime` (or the sports event's
  `startTime`) and `closedTime`. Polymarket's `closedTime` comes after the UMA resolution,
  often hours after the outcome is public. Using it directly would score post-outcome
  prices: in the markets where `closedTime` came first, 88% of 1 h prices sat at ≤ 2c or
  ≥ 98c and none of those missed.

**Triggered closes.** Some markets close because the outcome happened, for example "closes
early if X happens". I flag these and report every fit with and without them.

- **Polymarket:** flagged when the close came before both the end date and the game start.
- **Kalshi:** Kalshi publishes no original close time. As a heuristic, a non-sports close at
  a non-whole-minute timestamp counts as triggered. Scheduled Kalshi closes fall on whole
  minutes.

Neither choice is unbiased:

- Keeping triggered closes measures horizons from an outcome-dependent time.
- Dropping them removes by-date markets that resolved YES.

The truth plausibly lies between the two estimates.

**Price at horizon h** (7 d, 24 h, 1 h before the reference close):

- **Kalshi:** the last traded price in the latest hourly candle that ends at or before the
  horizon. Candles without a trade are skipped. Staleness is horizon minus candle end, so
  the true age of the trade is up to 1 h more. Median staleness was 1.1 h at 24 h and 0.9 h
  at 1 h.
- **Polymarket:** the last point of the hourly CLOB price history at or before the horizon.
  This is Polymarket's displayed price: the midpoint, or the last trade when the spread is
  over 10c. It carries no trade timestamps, so its staleness (always under 1 h here) is the
  age of the observation, not of a trade.
- **Staleness limit:** a market is dropped at a horizon if its last observation is older
  than 24 h.

**Scores.**

- Brier score and log loss.
- Murphy decomposition with 10 equal bins: BS = REL − RES + UNC + a within-bin term, all
  reported.
- Reliability diagrams with 12 bins.

**Recalibration.**

- Model: logit P(Y=1) = alpha + beta · logit(p), with p clipped to [0.01, 0.99]. That is
  Kalshi's tick; Polymarket prices below 1c are set to 1c, and a 0.001 clip is reported as
  a sensitivity check.
- Fitted by Newton–Raphson (IRLS) in `analyze.py`. The tests check that the score equations
  are zero at the solution and that known parameters are recovered.
- Interpretation: beta < 1 means prices are too extreme. beta > 1 means they are compressed
  toward 0.5, which is the favorite-longshot pattern. alpha < 0 means YES is overpriced
  across the board.

**Intervals: cluster bootstrap over events.**

- Each of 1,000 replicates (400 for the sensitivity checks) draws events with replacement.
- Every market inherits its event's draw count as a frequency weight, so mutually exclusive
  brackets and both sides of a game move together.
- Intervals are 95% percentile intervals.
- Category fits are reported where a category has at least 200 markets and 40 events.

## Results

### Scores and fits by venue and horizon

| venue | h | sample | markets | events | Brier | log loss | REL | RES | alpha [95% CI] | beta [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|
| Kalshi | 24h | all | 7,769 | 2,389 | 0.1223 | 0.374 | 0.0001 | 0.101 | 0.01 [-0.06, 0.08] | 0.99 [0.94, 1.04] |
| Kalshi | 24h | scheduled close | 6,539 | 2,104 | 0.1259 | 0.384 | 0.0001 | 0.088 | -0.01 [-0.08, 0.05] | 0.98 [0.93, 1.04] |
| Kalshi | 1h | all | 16,321 | 4,362 | 0.0801 | 0.252 | 0.0002 | 0.156 | -0.04 [-0.10, 0.02] | 1.06 [1.02, 1.10] |
| Kalshi | 7d | all | 1,472 | 489 | 0.1057 | 0.339 | 0.0013 | 0.139 | 0.03 [-0.15, 0.21] | 0.95 [0.86, 1.07] |
| Polymarket | 24h | all | 4,821 | 1,185 | 0.0988 | 0.311 | 0.0008 | 0.092 | 0.12 [0.03, 0.21] | 1.07 [1.00, 1.15] |
| Polymarket | 24h | scheduled close | 3,968 | 997 | 0.1038 | 0.326 | 0.0007 | 0.065 | -0.05 [-0.15, 0.04] | 1.01 [0.93, 1.09] |
| Polymarket | 1h | all | 5,160 | 1,322 | 0.0776 | 0.245 | 0.0009 | 0.117 | 0.20 [0.11, 0.29] | 1.13 [1.06, 1.22] |
| Polymarket | 7d | all | 1,724 | 508 | 0.1252 | 0.377 | 0.0066 | 0.078 | -0.20 [-0.35, -0.05] | 0.97 [0.87, 1.10] |

The samples differ by horizon. More markets exist 1 h before close than 24 h before, so
horizons are not like-for-like. On the 7,059 Kalshi markets priced at both horizons, beta is
0.97 [0.92, 1.02] at 24 h and 1.17 [1.10, 1.24] at 1 h.

The 7 d samples are small and dominated by long-dated markets. Polymarket's 7 d
scheduled-close fit has alpha = -0.52 [-0.67, -0.36]. That is the opposite selection
artifact: it keeps the by-date markets that ran to term, which are mostly NO.

### Favorite-longshot table, 24 h before close (realized minus average price, percentage points)

| bucket | Kalshi all | Kalshi scheduled | Polymarket all | Polymarket scheduled |
|---|---|---|---|---|
| < 10% | +0.1 [-0.5, +0.7] | +0.1 [-0.5, +0.8] | +0.4 [-0.2, +1.0] | +0.2 [-0.4, +0.9] |
| 10–30% | +0.6 [-1.2, +2.5] | +0.6 [-1.4, +2.7] | -0.4 [-2.6, +2.1] | -1.6 [-3.7, +0.7] |
| 30–70% | +0.5 [-1.4, +2.3] | -0.4 [-2.2, +1.3] | +1.6 [-1.1, +4.6] | -0.9 [-3.8, +1.8] |
| 70–90% | -0.2 [-4.0, +3.8] | -0.2 [-4.5, +4.1] | +5.3 [-0.6, +10.8] | -2.1 [-11.5, +6.4] |
| > 90% | -0.8 [-2.3, +0.5] | -0.8 [-3.0, +1.0] | +1.6 [+0.2, +2.7] | -0.3 [-3.0, +1.9] |

Bucket sizes are in `results/tables.md`. The thinnest are Polymarket 70–90% (163 markets)
and > 90% (353 markets).

At 1 h, Kalshi shows:

- < 10% bucket: -0.6 pp [-0.9, -0.3].
- 70–90% bucket: -3.5 pp [-6.0, -0.7]. Favorites are overpriced here, which is not the
  favorite-longshot direction.

### By category, 24 h before close

Most category fits are consistent with beta = 1.

Exceptions with intervals that exclude the identity:

- **Science and tech**, on both venues: Kalshi beta 1.32 [1.08, 1.77]; Polymarket beta 1.85
  [1.51, 3.06]. These are mostly near-certain "will X be released by …" markets, which are
  rich in triggered closes, so treat them with caution.
- **Kalshi weather:** alpha +0.13 [0.04, 0.24].
- **Kalshi sports:** alpha -0.10 [-0.19, -0.01].

33 category × horizon fits are reported, so one or two would exclude the identity by chance
alone.

### Sensitivity, 24 h (alpha / beta)

| variant | Kalshi | Polymarket |
|---|---|---|
| main | 0.01 / 0.99 [0.93, 1.04] | 0.12 / 1.07 [1.01, 1.15] |
| volume ≥ 10× threshold | 0.02 / 0.94 [0.86, 1.01] | 0.33 / 0.91 [0.81, 1.02] |
| staleness ≤ 2 h | -0.02 / 0.95 [0.88, 1.01] | identical to main |
| one random market per event | 0.07 / 0.93 [0.86, 1.01] | 0.15 / 1.10 [0.98, 1.27] |
| prices in [0.02, 0.98] | 0.01 / 0.96 [0.91, 1.02] | 0.09 / 1.02 [0.94, 1.12] |
| Kalshi bid/ask mid instead of last trade | 0.03 / 0.99 [0.95, 1.04] | n/a |
| scheduled close only | -0.01 / 0.98 [0.94, 1.04] | -0.05 / 1.01 [0.93, 1.08] |

Charts in `results/`:

- `reliability_<venue>_<h>.png`: per-bin 95% intervals and counts.
- `reliability_<venue>_horizons.png`.
- `recalibration_<venue>.png`.
- `recalibration_venues_24h.png`.
- `recalibration_deviation_{24h,1h}.png`: fitted minus price.
- `favorite_longshot_24h.png`.

## Caveats

- **Selection.**
  - The sample is stratified, not population-weighted. Pooled numbers describe this mix.
  - The volume filter keeps active markets, which are plausibly better calibrated than
    thin ones.
  - Polymarket sports cover ten sampled days, and only YES/NO markets: team-vs-team and
    over/under markets are excluded.
  - Kalshi lists only settled events and Polymarket only closed events. Events with some
    markets still open on 2026-10-24 (for example ladders of later dates) are missing, and
    so are markets that were still resolving.
  - 1,389 Polymarket markets were excluded because their resolution was not exactly 1/0.
- **Timing.**
  - Results depend on the reference close, as the "scheduled close" rows show.
  - The Kalshi triggered-close flag is a heuristic.
  - Polymarket's game-start reference makes its sports prices pre-game, while Kalshi's are
    in play.
  - Hourly resolution means a "1 h" price can be up to about 2 h old.
- **Correlation.** Markets within an event are handled by the bootstrap. Correlation
  across events is not: same-day weather in several cities, one macro release driving
  several series, or one news day. The intervals are therefore somewhat too narrow.
- **Short window.** Two months, one sports season segment, one macro calendar.
  Low-frequency categories (politics, economics releases) have tens to a few hundred
  events.
- **Fees, ticks and spreads.**
  - Kalshi charges taker fees of about 0.07·p·(1−p) per contract, rounded up per order.
  - Polymarket charges fees on some markets, for example sports.
  - Prices sit on 1c (Kalshi) and 0.1c (Polymarket) ticks.
  - Deviations of a cent or less, such as the 1c-floor effect, are within these frictions.
    Nothing here tests whether they could be traded profitably.
- **Reproducing from scratch.** The live Kalshi API keeps only recent markets. When the
  historical cutoff moves past 2026-08-25, these markets move to `/historical/` endpoints,
  and a fresh collection will no longer match. The response cache is the snapshot.

## Reproduce

Run from `market_calibration/` with the study's Python
(`/Users/barbiezhu/.cache/eventedge-venv/bin/python`; it needs numpy, pandas, matplotlib,
requests and pytest).

    python collect.py kalshi        # ~25 min on a cold cache; resumable, cached in data/raw/
    python collect.py polymarket    # ~35 min on a cold cache; can run alongside the above
    python build_dataset.py         # offline: data/markets.csv + results/dataset_summary.json
    python analyze.py               # offline: results/fit.json, tables.md, *.csv, *.png (~15 s)
    python -m pytest -q tests       # offline unit tests

With the cache present, `python collect.py kalshi --offline` and
`python collect.py polymarket --offline` rebuild every intermediate file without touching
the network.

`data/` is git-ignored. It holds:

- `data/raw/`: the response cache, about 320 MB. `data/raw/probe/` holds the first
  hand-made endpoint probes; the test fixtures were trimmed from these and from the cache.
- `data/interim/`: universes, samples and filter counts.
- `data/markets.csv`: one row per sampled market. Columns: venue, ids, category, close time
  and its source, `scheduled_close`, outcome, volume, and for each horizon
  `price_*`, `staleness_h_*` and `status_*` (plus `mid_*` for Kalshi).
