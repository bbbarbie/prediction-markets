# Pre-registration: where do Kalshi event contracts leak?

Written before any real Kalshi trade data has been analysed with this code. Commit this file before the first real run; the commit time is the registration time. Anything not fixed here is reported as exploratory.

## Data

- Kalshi public API, live and historical tiers, pulled with `kalshi_pull.py`.
- Series found by `--discover mention,award,oscar,grammy,emmy,nobel,attend,draft,nominee,cpi,fed`, plus `KXBTCD` and `KXHIGHNY` as continuous-public comparisons.
- Settled markets closing from 2025-06-01 to the pull date, with at least 500 contracts of volume.
- Families assigned by `families.py` as committed with this file. Corrections are allowed only for a series the table plainly misreads (for example a sports series caught by an award pattern), are listed in the report, and are made before outcomes are looked at.

## Fixed choices

- Reveal time: the earliest close among an event's markets.
- Windows (hours before the reveal): 168–24, 24–6, 6–1; primary window 24–1; baseline for markouts 336–168. The final hour is excluded everywhere (news sniping, live events).
- Prices: last trade strictly before each time. A market enters a window only if its last trade before the window opens is at most 12 hours old (a stale start price would count earlier news as resolved inside the window); the primary window is also reported with no age limit.
- Intervals: event-clustered; 95% percentile bootstrap with 2,000 resamples; one-sided tests at 5%.
- Recalibration: logistic in log-odds, per family, five folds by event, fitted on the last price 24 hours before the reveal.
- Basket: NO-taker trades on at least two outcomes of one event, consecutive trades at most 60 seconds apart. Long-shot bet: a market's largest YES-taker trade at 35¢ or less in the window, if in the top 5% of trade sizes.

## Hypotheses

**H1. Where.** In the scheduled-reveal family, the leak share over the primary window is above zero. Subfamilies (mention, award, named person, announcement, corporate) are ranked by leak share; a subfamily whose lower 95% bound is above zero is called leaky. The continuous-public and scheduled-data families are reported beside it as context, not as nulls.

**H2. Displacement.** Kalshi announced pre-listing risk scores and employer checks for high-risk markets on 2026-06-09. In mutually exclusive scheduled-reveal events, the skip-test hit ratio is higher for events revealed after that date than before it, and the long-shot hit ratio is lower. Test: difference in hit ratios after minus before, event bootstrap, one-sided. A skip-test result counts only if both placebos are quiet (p > 0.05): the same test on scheduled-reveal events one to two weeks before the reveal, and on continuous-public events in the primary window. Employer checks bar insiders whichever side they trade, so H2 is about screens keyed on long-shot YES bets, not about the checks.

**H3. Cost.** In scheduled-reveal events, net-of-spread taker markout is higher in the primary window than in the baseline window (leakage tax above zero). It is reported in cents per contract and as the Glosten–Milgrom insider share it implies at 50¢.

**H4. Scripts.** Mention markets on scripted events (prepared remarks: addresses, State of the Union, earnings-call scripts) leak more in the primary window than mention markets on unscripted events (press conferences, interviews, debates). Test: leak-share difference, event bootstrap, one-sided. Events whose script type the title does not settle are left out.

**H5. Risk scores (needs Kalshi's scores).** Families that Kalshi's framework would score high leak more. Scores trigger employer checks, which should themselves cut leakage, so the check uses markets that settled before 2026-06-09, scored after the fact.

## What would count against the idea

- H1 fails if no scheduled-reveal subfamily is leaky. The map would then say that public data cannot see leakage at this scale, which is worth reporting.
- H2 fails, or reverses, if the skip test is quiet after June 2026. That reads either as no displacement or as insiders spreading baskets beyond 60 seconds; the leak share for the same events tells the two apart.
- The power analysis (`power.py`) says what each test can detect with the number of events actually pulled; a null result below that power is reported as inconclusive, not as absence.
