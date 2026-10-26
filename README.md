# Prediction markets

*Barbie Zhu · Columbia CS · [github.com/bbbarbie](https://github.com/bbbarbie)*

Three projects around one question: **how good is a probability, and what does
it cost to be wrong?**

| | What it is | What it shows |
|---|---|---|
| [**EventEdge**](https://github.com/bbbarbie/EventEdge) | C++ simulator of market making in binary event contracts | How calibration error and informed flow turn into adverse selection and P&L |
| [**What does calibration error cost a market maker?**](https://github.com/bbbarbie/EventEdge/blob/main/docs/calibration_cost.md) | Short research note built on EventEdge | The cost of each cent of bias, and the *calibration budget*: how wrong a market maker can be and still make money |
| [**Averon**](https://github.com/bbbarbie/Averon) | Python engine that turns evidence into auditable probabilities and compares them with Polymarket prices | Language models only extract evidence; a transparent log-odds engine does the arithmetic, and every forecast is scored later with leakage-guarded backtests |
| [**Forecast log**](forecast_log/) (this repo) | My own forecasts on live Kalshi and Polymarket contracts | My Brier score against the market's on the same events, with every forecast committed before the market closed |
| [**How calibrated are Kalshi and Polymarket?**](market_calibration/REPORT.md) (this repo) | 25,500 resolved markets, price 24 h and 1 h before close vs outcome | No favorite-longshot bias at 24 h on either venue (Kalshi β = 0.99 [0.94, 1.04]); intervals from a bootstrap that resamples whole events |
| [**Same Brier score, different P&L**](https://github.com/bbbarbie/EventEdge/blob/main/docs/beyond_brier.md) | Four EventEdge follow-ups | Error shape matters at equal Brier; a learning MM recovers the budget; a rival removes it; the real markets' measured miscalibration costs an MM at most about 0.5¢ per contract |
| [**Where do event contracts leak?**](leakage/) (this repo) | From anonymous Kalshi trades: the leak share before scheduled reveals, a test for the "mirror trade" (NO on every other outcome) and what leaked information costs in spread | Pre-registered; on synthetic events with planted insiders the skip test catches NO baskets 78% of the time with 3% false alarms. Real run next |
| [**Which market rules end up disputed?**](resolution/) (this repo) | Every UMA dispute on Polymarket since 2024 joined to its market; a model trained on markets that resolved before a date and scored on markets listed after it; a linter that names each case a market's rules leave open | Pre-registered; on synthetic markets the test has 3% false alarms, and stripping post-listing clarifications is what keeps it honest. Real run next |

## Scoreboard

The log started on 2026-10-24. Results will appear here once forecasts
resolve, whether or not they beat the market.

```
No resolved forecasts yet.
```

Update it with `python forecast_log/pmlog.py score`.

## How the pieces fit

EventEdge asks what miscalibration costs someone who quotes prices. The
calibration study measures how miscalibrated real prices actually are, and
EventEdge prices that shape. Averon asks whether structured evidence can say
something the price does not. The leakage study asks where the answer reaches the price
before it is public, and the dispute study asks which rules leave the answer
itself open. The forecast log asks the plainest version of
all of them: when I disagree with the market, who is right more often, and
would acting on it have paid after the spread?

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q tests market_calibration/tests leakage/tests resolution/tests
.venv/bin/python forecast_log/pmlog.py --help
(cd market_calibration && ../.venv/bin/python analyze.py)   # needs its data cache; see REPORT
```
