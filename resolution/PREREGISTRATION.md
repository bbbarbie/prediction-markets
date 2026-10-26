# Pre-registration: which market rules end up disputed?

Written and committed before any real Polymarket data was pulled; the commit timestamp of this file is the record. Anything changed after the pull goes under *Deviations* at the bottom, with the reason, and the report says which results were affected.

## Question

Read at listing time, does the text of a market's rules rank which markets will be disputed through UMA's optimistic oracle better than the market's category and design already do?

Wen, Zhou and Huang ([2026](https://arxiv.org/abs/2604.15674)) found that LLMs prompted with a market's rules cannot reliably say in advance which markets will be disputed. This tests a narrower claim with a supervised model trained on every dispute in the training window, a time split, and baselines that already know the category. A null result is a result: it would mean a rules checklist is worth having but cannot be sold as a predictor.

## Data

* Gamma `/markets/keyset`: closed markets with end date on or after 2024-01-01 and volume of at least $10,000; question, rules (`description`), dates, tags, event, UMA bond and reward.
* Data API `/v2/resolutions`, per condition: `was_disputed`, `was_arbitrated`, `new_version_q`, `reporter`; per disputed question: first and second proposed price.
* Polygon `eth_getLogs` for UMA `DisputePrice` events from 2024-01-01 (topic `0x5165909c…e7f3`), if an RPC endpoint is available. A dispute joins its market when keccak256 of its ancillary data equals the market's question id, or else by the listed title and rules.

## Population

In order: resolution time known; resolved through UMA (Data API `reporter` = `UMA_OO`; where the Data API has no row, an on-chain dispute, a Gamma resolution-status history, or `resolvedBy` a known UMA adapter; being inside the chain scan's block range is not evidence); volume ≥ $10,000; listed on or after 2024-01-01; resolved at least 21 days before the pull date; rules text present; label known. A market's resolution time is the latest of Gamma's `closedTime`, the Data API's `resolved_at` and its last on-chain dispute. The report prints the count after each step.

## Labels

* **Primary, `disputed`:** any source reports a dispute: Data API `was_disputed` (true if any of the condition's rows says so); at least one on-chain `DisputePrice` for the market's question; "disputed" or "challenged" in Gamma's `umaResolutionStatuses` when it holds a history of two or more states. A market without an on-chain match counts as undisputed on chain only where a match was possible: listed and resolved inside the scan's coverage, not a neg-risk market, and no requester filter. The report cross-tabulates the sources.
* **Secondary:** `escalated` (two or more on-chain disputes, or `was_arbitrated`); `rules_updated` (`new_version_q`); `overturned` (first proposal differs from the final outcome; disputed markets only).

## Features (listing time only)

Question text; rules cut at the first post-listing marker (update, clarification, edit, additional context, correction or a note from Polymarket followed by an optional date and a colon or dash, or a line opening with a date stamp), with everything after it dropped; category from tags; market design: horizon (end minus listing), neg-risk, outcome labels, UMA bond and reward, custom liveness. (The number of markets in an event is not used: the pull keeps only markets above the volume floor, so it would carry post-listing volume.) Template history counts only markets that resolved before the market listed. Realized volume enters only M0v and M2v.

## Split

Train: markets resolved before **2026-04-01** (resolution time as defined under Population). Test: markets listed on or after 2026-04-01 (and mature). Markets listed before the split and resolved after it are in neither set.

## Models

Logistic regressions that differ only in inputs (see `model.py`): prior (category), M0 (category + design), M1 (M0 + phrase-family counts, the linter's eleven flags, text structure), M2 (M1 + TF-IDF of 1–2-grams, min_df 5, max_df 0.6), M3 (M2 + template history), M0v and M2v (with log volume). For models with text, C is chosen from {0.1, 0.3, 1, 3} by PR-AUC on the last fifth of the training period; other models use C = 1.

## Hypotheses and tests

One-sided at 5%: a hypothesis is supported when its one-sided p-value is below 0.05 (the report also prints the two-sided 95% interval, which is stricter). H1 and H2 use a paired bootstrap over events (1,000 resamples) on the test set; average precision breaks tied scores with the same fixed jitter for every model.

* **H1 (primary):** PR-AUC of M2 exceeds that of M0. Reported alongside: recall within the riskiest 5% of test markets.
* **H2:** PR-AUC of M2v exceeds that of M0v (the words add beyond realized volume, since disputes rise with volume).
* **H3:** each of four flags raises the odds of a dispute when added alone to M0 on the training set (nearly unpenalised logistic regression, C = 100; p from the event-cluster bootstrap standard error of the coefficient, 200 resamples; Holm-adjusted across the four): `consensus_undefined`, `event_vs_announcement`, `undefined_term`, `no_source`.
* **H4 (descriptive):** where the Iran peace-deal markets and the Strategy bitcoin-sale markets fall in M2's risk distribution, and which flags fire.

## What would count against the idea

* H1 fails: the words add nothing to category and design.
* The placebo (each market given another market's text from the same category and quarter) scores close to M2: the signal is in the mix of markets, not the words.
* M2's advantage exists only in the top volume quintile, or only for templates seen in training: reported as the scope of the result, not hidden.
* The unstripped model (Gamma's current text, clarifications included) scoring far above M2 is expected and is not evidence for the idea: post-listing text leaks the label. The stripped number is the one that counts.

## Robustness, reported whatever H1 shows

Markets whose rules were never updated after listing; volume ≥ $100k; each label source alone; event level (any market disputed vs. the event's highest score); new vs. seen templates; ROC-AUC within volume quintiles; calibration by decile.

## Known limits

* Gamma serves current rules; stripping is a heuristic and cannot catch a clarification with no marker. The on-chain listing text checks it for disputed markets only, and the report lists the markets where the stripped rules still differ from it.
* A dispute is a noisy measure of ambiguity: some are bad-faith or "too early" proposals. `overturned` separates part of that.
* The population depends on the volume floor. Polymarket only: Kalshi resolves disputes internally and does not publish them.

## Validation before the real run

`power.py` (fresh synthetic samples, planted drivers, the same pipeline) and `tests/`. Results in the README.

## Deviations

None yet.
