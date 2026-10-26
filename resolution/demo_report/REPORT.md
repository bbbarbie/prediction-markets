# Which market rules end up disputed? Report

> **Synthetic data.** 8,184 generated markets with planted dispute drivers (open clauses raise dispute odds, closing clauses lower them; text effect 0.9) and clarifications appended after the fact, in six shapes, to 50% of disputed markets. These numbers validate the pipeline; they say nothing about Polymarket.

Generated 2026-10-26 06:07 UTC from `data/synthetic`. Train: markets resolved before 2026-04-01. Test: markets listed on or after 2026-04-01. Population and tests as in [PREREGISTRATION.md](../PREREGISTRATION.md).

## Data

| step | markets |
|---|---:|
| all markets | 8184 |
| closed (resolution time known) | 8184 |
| resolved through UMA | 7842 |
| volume >= 10,000 | 6084 |
| listed on or after 2024-01-01 | 6084 |
| resolved 21+ days before the pull | 5924 |
| has rules text | 5924 |
| label known | 5924 |

Train 4,852 markets (302 disputed, 6.2%); test 866 (55 disputed, 6.4%).

Label sources (markets with a value) and how they agree:

```
{
 "api_rows": 8184,
 "api_conditions_with_several_rows": 0,
 "chain_logs": 589,
 "chain_undecodable_logs": 0,
 "chain_coverage": [
  "2024-01-01 00:00:00+00:00",
  "2026-10-20 00:00:00+00:00"
 ],
 "chain_requester_filter": [],
 "chain_questions": 486,
 "joined_by_question_id": 177,
 "joined_by_text": 279,
 "unmatched": 30,
 "chain_requesters": {
  "UmaCtfAdapter (neg risk)": 279,
  "UmaCtfAdapter v3": 177,
  "other": 30
 },
 "label_sources": {
  "api": 8184,
  "chain": 3963,
  "gamma": 7842
 },
 "label_agreement_all_three": {
  "rows": 3703,
  "crosstab": {
   "000": 3247,
   "111": 456
  }
 },
 "crosstab api_was_disputed x chain_disputed": {
  "False/False": 3507,
  "False/True": 0,
  "True/False": 0,
  "True/True": 456
 },
 "crosstab api_was_disputed x gamma_disputed": {
  "False/False": 7386,
  "False/True": 0,
  "True/False": 0,
  "True/True": 456
 },
 "crosstab chain_disputed x gamma_disputed": {
  "False/False": 3247,
  "False/True": 0,
  "True/False": 0,
  "True/True": 456
 }
}
```

| category | train markets | train rate | test markets | test rate | gap markets | gap rate |
|---|---:|---:|---:|---:|---:|---:|
| business | 307 | 0.065 | 35 | 0.029 | 21 | 0.143 |
| crypto | 437 | 0.016 | 107 | 0.009 | 1 | 0.000 |
| culture | 374 | 0.053 | 80 | 0.050 | 14 | 0.000 |
| economy | 458 | 0.022 | 80 | 0.025 | 22 | 0.000 |
| elections | 712 | 0.029 | 89 | 0.045 | 58 | 0.034 |
| geopolitics | 555 | 0.173 | 60 | 0.217 | 51 | 0.176 |
| mentions | 269 | 0.134 | 61 | 0.197 |  |  |
| politics | 732 | 0.116 | 125 | 0.120 | 37 | 0.135 |
| sports | 1008 | 0.007 | 229 | 0.013 | 2 | 0.000 |

Post-listing text removed before modelling (clarification and update paragraphs):

| markets | count | with post-listing text removed |
|---|---:|---:|
| disputed | 376 | 178 |
| not disputed | 5548 | 21 |

Where the on-chain listing text exists (disputed markets):

|  | markets |
|---|---:|
| markets with on-chain listing text | 376 |
| Gamma rules identical to listing text | 198 |
| identical after stripping post-listing text | 376 |

## Do the words predict disputes?

| model | rate | ROC-AUC | PR-AUC | recall@5% | volume recall@5% | lift@5% |
|---|---|---:|---:|---|---|---|
| prior | 6.4% | 0.782 | 0.177 | 14.5% | 14.4% | 2.9x |
| M0 | 6.4% | 0.772 | 0.159 | 12.7% | 9.6% | 2.5x |
| M1 | 6.4% | 0.818 | 0.291 | 30.9% | 27.8% | 6.2x |
| M2 | 6.4% | 0.823 | 0.278 | 29.1% | 26.2% | 5.8x |
| M3 | 6.4% | 0.826 | 0.275 | 27.3% | 25.0% | 5.5x |
| M0v | 6.4% | 0.785 | 0.189 | 20.0% | 51.9% | 4.0x |
| M2v | 6.4% | 0.825 | 0.285 | 29.1% | 26.5% | 5.8x |

**H1** (M2 beats M0; words add to category and market design): PR-AUC +0.118 (two-sided 95% CI +0.035 to +0.231; one-sided p = 0.003); recall@5% +0.164 (two-sided 95% CI +0.017 to +0.315; one-sided p = 0.023). **supported**.

**H2** (words add beyond realized volume, M2v vs M0v): PR-AUC +0.096 (two-sided 95% CI +0.012 to +0.195; one-sided p = 0.009). **supported**.

Template history (M3 vs M2): PR-AUC -0.002 (two-sided 95% CI -0.007 to +0.001; one-sided p = 0.921).

![gains](gains.png)

Within volume quintiles (ROC-AUC; disputes rise with volume, so this checks the words are not a proxy for size):

| volume quintile | markets | min volume | disputed | M0 AUC | M2 AUC |
|---:|---:|---:|---:|---:|---:|
| 1 | 174 | 10085.350 | 6 | 0.812 | 0.820 |
| 2 | 173 | 21949.720 | 9 | 0.712 | 0.764 |
| 3 | 173 | 38351.750 | 10 | 0.764 | 0.868 |
| 4 | 173 | 72426.030 | 16 | 0.835 | 0.880 |
| 5 | 173 | 153834.500 | 14 | 0.697 | 0.765 |

Seen vs. new templates (a template is a series, or the rules with numbers, dates and quoted names masked):

| test markets | markets | disputed | M0 PR-AUC | M2 PR-AUC | M3 PR-AUC |
|---|---:|---:|---:|---:|---:|
| template seen in training | 189 | 1 | 0.011 | 0.012 | 0.015 |
| new template | 677 | 54 | 0.165 | 0.285 | 0.281 |

## Which open questions matter (H3)

Each pre-registered flag added alone to M0 (odds ratio of dispute when the flag is on, holding category and market design fixed; nearly unpenalised logistic regression, C = 100; event-cluster bootstrap on the training set; one-sided p from the bootstrap standard error, Holm-adjusted across the four):

| flag | share flagged | odds ratio | 95% CI low | 95% CI high | p (one-sided) | Holm p |
|---|---:|---:|---:|---:|---:|---:|
| consensus_undefined | 0.138 | 2.921 | 2.141 | 3.984 | <0.001 | <0.001 |
| event_vs_announcement | 0.104 | 2.280 | 1.644 | 3.066 | <0.001 | <0.001 |
| undefined_term | 0.358 | 2.236 | 1.543 | 3.401 | <0.001 | <0.001 |
| no_source | 0.629 | 1.499 | 1.132 | 2.159 | 0.008 | 0.008 |

Dispute rate with and without each flag, test set:

| flag | share flagged | dispute rate if flagged | if not | ratio |
|---|---:|---:|---:|---:|
| consensus_undefined | 0.143 | 0.161 | 0.047 | 3.419 |
| event_vs_announcement | 0.084 | 0.137 | 0.057 | 2.414 |
| undefined_term | 0.336 | 0.124 | 0.033 | 3.744 |
| no_timezone | 0.460 | 0.078 | 0.051 | 1.519 |
| no_source | 0.614 | 0.090 | 0.021 | 4.305 |
| no_fallback | 0.000 |  | 0.064 |  |
| threshold_unmeasured | 0.081 | 0.000 | 0.069 | 0.000 |
| degree_words | 0.157 | 0.176 | 0.042 | 4.156 |
| subjective | 0.076 | 0.197 | 0.052 | 3.752 |
| mention_undefined | 0.059 | 0.235 | 0.053 | 4.460 |
| legislative_stage | 0.039 | 0.059 | 0.064 | 0.923 |

Largest M1 coefficients:

| highest | coef_hi | lowest | coef_lo |
|---|---:|---|---:|
| sentences | 1.178 | category=sports | -1.409 |
| category=geopolitics | 0.840 | log_words | -0.827 |
| category=politics | 0.729 | category=culture | -0.787 |
| category=elections | 0.446 | category=economy | -0.705 |
| flag_no_source | 0.264 | conditions_per_100w | -0.486 |
| lex_consensus_source | 0.262 | lex_fallback | -0.406 |
| category=business | 0.203 | lex_definition | -0.354 |
| lex_vague_state | 0.157 | lex_named_source | -0.336 |
| lex_say_mention | 0.116 | flag_threshold_unmeasured | -0.297 |
| lex_threshold | 0.102 | neg_risk | -0.244 |
| lex_subjective | 0.089 | log_horizon_days | -0.243 |
| flag_subjective | 0.089 | category=crypto | -0.236 |

Words and pairs with the largest M2 weights:

| highest | coef_hi | lowest | coef_lo |
|---|---:|---|---:|
| "estara" | 0.974 | "suffice note" | -0.655 |
| "jessar" | 0.869 | "december" | -0.642 |
| "outlets this" | 0.757 | "by december" | -0.624 |
| "deal during" | 0.752 | "galvany and" | -0.592 |
| "hollen" | 0.722 | "no the" | -0.557 |
| "august ana" | 0.721 | "brevia" | -0.545 |
| "and jessar" | 0.652 | "by march" | -0.541 |
| "involved note" | 0.650 | "irvana" | -0.533 |
| "hollen strike" | 0.575 | "and irvana" | -0.512 |
| "no only" | 0.553 | "deal by" | -0.512 |
| "and estara" | 0.552 | "peace" | -0.512 |
| "ceasefire" | 0.528 | "peace deal" | -0.512 |
| "ceasefire by" | 0.528 | "sign peace" | -0.512 |
| "jessar reach" | 0.499 | "marovia" | -0.510 |
| "by november" | 0.490 | "note" | -0.496 |

## Checks

| check | PR-AUC | what it should show |
|---|---:|---|
| M2 as fitted | 0.278 | the main result |
| M0 (no words) | 0.159 | the bar M2 must clear |
| placebo: each market gets another market's text (same category, quarter) | 0.170 | about M0: the words carry the signal, not the mix |
| unstripped: Gamma's current rules, clarifications included | 0.587 | above M2 if post-listing text leaks the label |

Robustness (M2 vs M0 PR-AUC):

| subset | markets | disputed | M0 PR-AUC | M2 PR-AUC | diff | p |
|---|---:|---:|---:|---:|---:|---:|
| rules never updated after listing | 836 | 31 | 0.095 | 0.188 | 0.093 | 0.003 |
| volume >= $100k | 266 | 23 | 0.197 | 0.349 | 0.152 | 0.003 |
| labels: API was_disputed only | 866 | 55 | 0.159 | 0.278 | 0.118 | 0.003 |
| labels: on-chain disputes only | 488 | 55 | 0.248 | 0.429 | 0.181 | 0.003 |
| labels: Gamma statuses only | 866 | 55 | 0.159 | 0.278 | 0.118 | 0.003 |
| event level (any market disputed; max score) | 596 | 44 | 0.164 | 0.312 | 0.148 |  |

Calibration of M2 by test-score decile:

| decile | markets | predicted | observed |
|---:|---:|---:|---:|
| 1 | 87 | 0.0019 | 0.0000 |
| 2 | 87 | 0.0036 | 0.0115 |
| 3 | 86 | 0.0062 | 0.0116 |
| 4 | 87 | 0.0095 | 0.0345 |
| 5 | 86 | 0.0145 | 0.0233 |
| 6 | 87 | 0.0226 | 0.0345 |
| 7 | 86 | 0.0356 | 0.0233 |
| 8 | 87 | 0.0613 | 0.0690 |
| 9 | 86 | 0.1211 | 0.1279 |
| 10 | 87 | 0.2987 | 0.2989 |

## Secondary outcomes

| outcome | markets | positives | rate | M0 PR-AUC | M2 PR-AUC |
|---|---:|---:|---:|---:|---:|
| escalated | 866 | 6 | 0.007 | 0.034 | 0.062 |
| rules_updated | 866 | 30 | 0.035 | 0.102 | 0.142 |
| overturned: first proposal lost (disputed markets, all years) | 376 | 193 | 0.513 |  |  |

## Case studies

No market in the population matched the case patterns (`CASES` in run.py).

## Highest-risk test markets (M2)

| market | category | listed | volume | risk | disputed | flags |
|---|---|---|---:|---:|---:|---|
| Will Irvana strike Nerath by August 30, 2026? | geopolitics | 2026-07-22 | 214,044 | 0.811 | no | event_vs_announcement, undefined_term, no_timezone, no_source, subjective |
| Will the Governor say "jobs" during the earnings call? | mentions | 2026-05-10 | 59,948 | 0.675 | yes | consensus_undefined, event_vs_announcement, undefined_term, no_source, degree_words, subjective, mention_undefined |
| Will Dornia strike Jessar by July 2, 2026? | geopolitics | 2026-05-17 | 22,766 | 0.639 | no | event_vs_announcement, undefined_term, no_timezone, no_source, degree_words, subjective |
| Galvany x Feldmark ceasefire by September 6, 2026? | geopolitics | 2026-07-16 | 55,144 | 0.501 | no | consensus_undefined, undefined_term, no_timezone, no_source |
| Will the Speaker sign the bill by May 5, 2026? | politics | 2026-04-14 | 206,293 | 0.498 | no | no_timezone, no_source, subjective, legislative_stage |
| Will Lusora and Hollen sign a peace deal by August 7, 2026? | geopolitics | 2026-06-14 | 139,870 | 0.482 | yes | consensus_undefined, event_vs_announcement, undefined_term, no_timezone, no_source, degree_words, subjective |
| Will the Fed Chair say "jobs" during the State of the Union? | mentions | 2026-09-04 | 202,662 | 0.454 | no | consensus_undefined, undefined_term, degree_words, subjective, mention_undefined |
| Will the CEO resign by July 5, 2026? | politics | 2026-06-14 | 127,168 | 0.453 | yes | undefined_term, no_timezone, degree_words, subjective |
| Will the Speaker be out by July 20, 2026? [Dara Singh] | politics | 2026-06-11 | 136,028 | 0.450 | no | consensus_undefined, event_vs_announcement, no_timezone, no_source |
| Will Jessar strike Lusora by June 19, 2026? [Ben Cole] | geopolitics | 2026-04-30 | 524,990 | 0.436 | yes | consensus_undefined, undefined_term, no_timezone, no_source, degree_words |
| Marovia x Irvana ceasefire by May 25, 2026? | geopolitics | 2026-04-28 | 58,914 | 0.409 | no | event_vs_announcement, no_timezone, no_source |
| Will the Speaker be out by July 20, 2026? [Ana Ortiz] | politics | 2026-06-11 | 24,763 | 0.404 | no | consensus_undefined, event_vs_announcement, no_timezone, no_source |
| Will the Governor be out by September 19, 2026? | politics | 2026-08-24 | 34,928 | 0.402 | yes | consensus_undefined, event_vs_announcement, no_timezone, degree_words, subjective |
| Will the Prime Minister meet with the Chancellor by June 23, 2026? | politics | 2026-05-08 | 32,104 | 0.392 | no | consensus_undefined, undefined_term, no_timezone, no_source, degree_words |
| Will the Speaker be out by July 20, 2026? [Chen Li] | politics | 2026-06-11 | 34,744 | 0.391 | no | consensus_undefined, event_vs_announcement, no_timezone, no_source |
| Will Jessar strike Lusora by June 19, 2026? [Ana Ortiz] | geopolitics | 2026-04-30 | 324,492 | 0.388 | yes | consensus_undefined, undefined_term, no_timezone, no_source, degree_words |
| Will Jessar strike Lusora by June 19, 2026? [Fay Moreau] | geopolitics | 2026-04-30 | 99,210 | 0.384 | yes | consensus_undefined, undefined_term, no_timezone, no_source, degree_words |
| Will the Speaker be out by July 20, 2026? [Gus Ibarra] | politics | 2026-06-11 | 101,907 | 0.381 | no | consensus_undefined, event_vs_announcement, no_timezone, no_source |
| Will Dornia and Lusora agree to a permanent truce by August 18, 2026? [Ben Cole] | geopolitics | 2026-07-20 | 155,635 | 0.376 | yes | consensus_undefined, event_vs_announcement, undefined_term, no_timezone, no_source |
| Will Jessar strike Lusora by June 19, 2026? [Gus Ibarra] | geopolitics | 2026-04-30 | 173,684 | 0.364 | yes | consensus_undefined, undefined_term, no_timezone, no_source, degree_words |

Full list: `top_risk.csv`. Model for the linter: `model.pkl` (`python3 -m resolution.lint --model resolution/demo_report/model.pkl --examples`).

Runtime 113.7 s.