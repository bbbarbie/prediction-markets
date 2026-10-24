# Generated tables (analyze.py)

### Filters: Kalshi

| step | remaining | removed |
|---|---|---|
| listed | 286312 | 0 |
| not multivariate (MVE) | 286312 | 0 |
| binary market_type | 286312 | 0 |
| settled YES/NO (no scalar/void) | 282822 | 3490 |
| close in 2026-08-25..2026-10-21 | 282822 | 0 |
| volume >= 1000 | 135932 | 146890 |
| stratified sample | 20000 | 115932 |
| price available 7d before close (stale > 24 h: 70, no price: 18458) | 1472 | 18528 |
| price available 24h before close (stale > 24 h: 1814, no price: 10417) | 7769 | 12231 |
| price available 1h before close (stale > 24 h: 1648, no price: 2031) | 16321 | 3679 |

### Filters: Polymarket

| step | remaining | removed |
|---|---|---|
| listed | 311128 | 0 |
| Yes/No outcomes | 197657 | 113471 |
| UMA resolved to exactly 1/0 | 196268 | 1389 |
| has YES token id | 196268 | 0 |
| close in 2026-08-25..2026-10-21 | 133384 | 62884 |
| volume >= 1000 | 46685 | 86699 |
| stratified sample | 5500 | 41185 |
| price available 7d before close (stale > 24 h: 0, no price: 3776) | 1724 | 3776 |
| price available 24h before close (stale > 24 h: 0, no price: 679) | 4821 | 679 |
| price available 1h before close (stale > 24 h: 0, no price: 340) | 5160 | 340 |

### Scores and recalibration fit, all categories

| venue | h | sample | markets | events | YES rate | Brier | log loss | REL | RES | UNC | alpha [95% CI] | beta [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Kalshi | 7d | all | 1472 | 489 | 0.423 | 0.1057 | 0.3386 | 0.0013 | 0.1386 | 0.2440 | 0.03 [-0.15, 0.21] | 0.95 [0.86, 1.07] |
| Kalshi | 7d | scheduled close | 694 | 260 | 0.408 | 0.0980 | 0.3166 | 0.0031 | 0.1459 | 0.2415 | -0.16 [-0.43, 0.09] | 1.06 [0.90, 1.26] |
| Kalshi | 24h | all | 7769 | 2389 | 0.338 | 0.1223 | 0.3740 | 0.0001 | 0.1010 | 0.2238 | 0.01 [-0.06, 0.08] | 0.99 [0.94, 1.04] |
| Kalshi | 24h | scheduled close | 6539 | 2104 | 0.311 | 0.1259 | 0.3837 | 0.0001 | 0.0879 | 0.2142 | -0.01 [-0.08, 0.05] | 0.98 [0.93, 1.04] |
| Kalshi | 1h | all | 16321 | 4362 | 0.384 | 0.0801 | 0.2520 | 0.0002 | 0.1559 | 0.2364 | -0.04 [-0.10, 0.02] | 1.06 [1.02, 1.10] |
| Kalshi | 1h | scheduled close | 14505 | 4003 | 0.370 | 0.0835 | 0.2618 | 0.0002 | 0.1492 | 0.2332 | -0.05 [-0.12, 0.01] | 1.04 [1.00, 1.08] |
| Polymarket | 7d | all | 1724 | 508 | 0.268 | 0.1252 | 0.3770 | 0.0066 | 0.0777 | 0.1962 | -0.20 [-0.35, -0.05] | 0.97 [0.87, 1.10] |
| Polymarket | 7d | scheduled close | 1233 | 408 | 0.221 | 0.1380 | 0.4116 | 0.0115 | 0.0467 | 0.1724 | -0.52 [-0.67, -0.36] | 0.88 [0.76, 1.02] |
| Polymarket | 24h | all | 4821 | 1185 | 0.255 | 0.0988 | 0.3108 | 0.0008 | 0.0915 | 0.1899 | 0.12 [0.03, 0.21] | 1.07 [1.00, 1.15] |
| Polymarket | 24h | scheduled close | 3968 | 997 | 0.214 | 0.1038 | 0.3260 | 0.0007 | 0.0649 | 0.1685 | -0.05 [-0.15, 0.04] | 1.01 [0.93, 1.09] |
| Polymarket | 1h | all | 5160 | 1322 | 0.264 | 0.0776 | 0.2454 | 0.0009 | 0.1167 | 0.1944 | 0.20 [0.11, 0.29] | 1.13 [1.06, 1.22] |
| Polymarket | 1h | scheduled close | 4253 | 1124 | 0.222 | 0.0908 | 0.2856 | 0.0009 | 0.0818 | 0.1727 | 0.12 [0.03, 0.22] | 1.09 [1.00, 1.18] |

### By category, 24h before close (categories with >= 200 markets and >= 40 events)

| venue | category | markets | events | Brier | alpha [95% CI] | beta [95% CI] |
|---|---|---|---|---|---|---|
| Kalshi | culture | 1529 | 271 | 0.0740 | 0.01 [-0.24, 0.26] | 1.06 [0.97, 1.18] |
| Kalshi | economics | 512 | 132 | 0.0974 | -0.05 [-0.47, 0.36] | 0.88 [0.73, 1.12] |
| Kalshi | politics | 529 | 161 | 0.0711 | 0.16 [-0.19, 0.57] | 1.08 [0.91, 1.36] |
| Kalshi | science_tech | 561 | 140 | 0.0610 | -0.50 [-0.92, -0.06] | 1.32 [1.08, 1.77] |
| Kalshi | sports | 1908 | 985 | 0.1830 | -0.10 [-0.19, -0.01] | 0.91 [0.81, 1.04] |
| Kalshi | weather | 2570 | 656 | 0.1367 | 0.13 [0.04, 0.24] | 1.00 [0.90, 1.10] |
| Polymarket | crypto | 557 | 82 | 0.0590 | 0.13 [-0.16, 0.46] | 1.01 [0.88, 1.25] |
| Polymarket | culture | 478 | 115 | 0.0766 | 0.02 [-0.27, 0.37] | 1.13 [0.94, 1.42] |
| Polymarket | economics | 558 | 162 | 0.1324 | -0.00 [-0.26, 0.27] | 0.94 [0.80, 1.13] |
| Polymarket | politics | 507 | 142 | 0.0746 | 0.33 [0.03, 0.75] | 1.19 [0.96, 1.60] |
| Polymarket | science_tech | 355 | 69 | 0.0298 | 1.54 [0.89, 2.85] | 1.85 [1.51, 3.06] |
| Polymarket | sports | 752 | 346 | 0.1709 | 0.07 [-0.11, 0.25] | 0.88 [0.73, 1.07] |
| Polymarket | weather | 1612 | 267 | 0.0964 | 0.03 [-0.15, 0.21] | 1.09 [0.94, 1.25] |

### By category, 1h before close (categories with >= 200 markets and >= 40 events)

| venue | category | markets | events | Brier | alpha [95% CI] | beta [95% CI] |
|---|---|---|---|---|---|---|
| Kalshi | crypto | 277 | 68 | 0.0476 | -0.03 [-0.46, 0.45] | 1.02 [0.80, 1.49] |
| Kalshi | culture | 1806 | 319 | 0.0481 | -0.02 [-0.29, 0.23] | 1.18 [1.06, 1.37] |
| Kalshi | economics | 3153 | 474 | 0.0267 | -0.24 [-0.58, 0.05] | 1.23 [1.10, 1.43] |
| Kalshi | politics | 718 | 198 | 0.0245 | 0.23 [-0.26, 0.75] | 1.43 [1.17, 1.92] |
| Kalshi | science_tech | 996 | 166 | 0.0029 | 0.20 [-2.34, 2.83] | 2.17 [1.74, 5.22] |
| Kalshi | sports | 6745 | 2470 | 0.1580 | -0.07 [-0.13, 0.00] | 0.89 [0.84, 0.95] |
| Kalshi | weather | 2626 | 667 | 0.0137 | -0.03 [-0.28, 0.29] | 1.26 [1.13, 1.48] |
| Polymarket | crypto | 732 | 112 | 0.0387 | 0.76 [0.31, 1.41] | 1.16 [1.00, 1.44] |
| Polymarket | culture | 503 | 120 | 0.0384 | -0.15 [-0.53, 0.24] | 1.35 [1.08, 2.00] |
| Polymarket | economics | 559 | 163 | 0.0910 | -0.29 [-0.55, -0.05] | 1.06 [0.89, 1.30] |
| Polymarket | politics | 511 | 146 | 0.0285 | -0.03 [-0.31, 0.51] | 1.28 [0.94, 2.85] |
| Polymarket | science_tech | 360 | 69 | 0.0016 | n/a | n/a |
| Polymarket | sports | 853 | 433 | 0.1686 | 0.49 [0.32, 0.69] | 1.06 [0.89, 1.25] |
| Polymarket | weather | 1639 | 276 | 0.0868 | 0.03 [-0.11, 0.18] | 1.08 [0.94, 1.25] |

### By category, 7d before close (categories with >= 200 markets and >= 40 events)

| venue | category | markets | events | Brier | alpha [95% CI] | beta [95% CI] |
|---|---|---|---|---|---|---|
| Kalshi | culture | 505 | 143 | 0.1268 | 0.04 [-0.29, 0.37] | 0.87 [0.73, 1.07] |
| Kalshi | politics | 382 | 124 | 0.0684 | 0.00 [-0.36, 0.47] | 1.04 [0.84, 1.38] |
| Polymarket | economics | 285 | 72 | 0.0947 | 0.51 [0.02, 1.09] | 1.19 [0.91, 1.69] |
| Polymarket | politics | 448 | 122 | 0.0978 | 0.10 [-0.24, 0.51] | 1.00 [0.81, 1.30] |
| Polymarket | science_tech | 267 | 45 | 0.0437 | 0.40 [-0.30, 1.29] | 1.39 [1.09, 2.22] |
| Polymarket | sports | 554 | 227 | 0.2036 | -0.63 [-0.86, -0.39] | 0.65 [0.40, 0.94] |

### Favorite-longshot table, 24h before close

| venue | sample | bucket | markets | events | avg price | realized | realized - price, pp [95% CI] |
|---|---|---|---|---|---|---|---|
| Kalshi | all | <10% | 2752 | 1092 | 0.029 | 0.030 | +0.1 [-0.5, +0.7] |
| Kalshi | all | 10-30% | 1466 | 975 | 0.191 | 0.196 | +0.6 [-1.2, +2.5] |
| Kalshi | all | 30-70% | 2208 | 1467 | 0.473 | 0.479 | +0.5 [-1.4, +2.3] |
| Kalshi | all | 70-90% | 532 | 412 | 0.793 | 0.791 | -0.2 [-4.0, +3.8] |
| Kalshi | all | >90% | 811 | 468 | 0.969 | 0.961 | -0.8 [-2.3, +0.5] |
| Kalshi | scheduled close | <10% | 2376 | 941 | 0.029 | 0.030 | +0.1 [-0.5, +0.8] |
| Kalshi | scheduled close | 10-30% | 1310 | 895 | 0.191 | 0.197 | +0.6 [-1.4, +2.7] |
| Kalshi | scheduled close | 30-70% | 1979 | 1368 | 0.470 | 0.467 | -0.4 [-2.2, +1.3] |
| Kalshi | scheduled close | 70-90% | 361 | 314 | 0.791 | 0.789 | -0.2 [-4.5, +4.1] |
| Kalshi | scheduled close | >90% | 513 | 309 | 0.969 | 0.961 | -0.8 [-3.0, +1.0] |
| Polymarket | all | <10% | 2322 | 678 | 0.024 | 0.028 | +0.4 [-0.2, +1.0] |
| Polymarket | all | 10-30% | 937 | 551 | 0.195 | 0.191 | -0.4 [-2.6, +2.1] |
| Polymarket | all | 30-70% | 1046 | 712 | 0.460 | 0.476 | +1.6 [-1.1, +4.6] |
| Polymarket | all | 70-90% | 163 | 127 | 0.806 | 0.859 | +5.3 [-0.6, +10.8] |
| Polymarket | all | >90% | 353 | 230 | 0.970 | 0.986 | +1.6 [+0.2, +2.7] |
| Polymarket | scheduled close | <10% | 1931 | 572 | 0.025 | 0.028 | +0.2 [-0.4, +0.9] |
| Polymarket | scheduled close | 10-30% | 863 | 509 | 0.195 | 0.178 | -1.6 [-3.7, +0.7] |
| Polymarket | scheduled close | 30-70% | 915 | 640 | 0.455 | 0.446 | -0.9 [-3.8, +1.8] |
| Polymarket | scheduled close | 70-90% | 82 | 72 | 0.789 | 0.768 | -2.1 [-11.5, +6.4] |
| Polymarket | scheduled close | >90% | 177 | 99 | 0.974 | 0.972 | -0.3 [-3.0, +1.9] |

### Favorite-longshot table, 1h before close

| venue | sample | bucket | markets | events | avg price | realized | realized - price, pp [95% CI] |
|---|---|---|---|---|---|---|---|
| Kalshi | all | <10% | 6634 | 2281 | 0.020 | 0.013 | -0.6 [-0.9, -0.3] |
| Kalshi | all | 10-30% | 2120 | 1530 | 0.187 | 0.176 | -1.1 [-2.9, +0.7] |
| Kalshi | all | 30-70% | 2816 | 1788 | 0.479 | 0.486 | +0.7 [-1.2, +2.4] |
| Kalshi | all | 70-90% | 1063 | 944 | 0.798 | 0.763 | -3.5 [-6.0, -0.7] |
| Kalshi | all | >90% | 3688 | 1926 | 0.980 | 0.981 | +0.1 [-0.4, +0.5] |
| Kalshi | scheduled close | <10% | 5984 | 2062 | 0.020 | 0.014 | -0.6 [-0.9, -0.2] |
| Kalshi | scheduled close | 10-30% | 1921 | 1436 | 0.187 | 0.179 | -0.8 [-2.7, +0.9] |
| Kalshi | scheduled close | 30-70% | 2631 | 1711 | 0.478 | 0.484 | +0.6 [-1.3, +2.3] |
| Kalshi | scheduled close | 70-90% | 938 | 865 | 0.797 | 0.748 | -4.8 [-7.7, -2.0] |
| Kalshi | scheduled close | >90% | 3031 | 1673 | 0.979 | 0.979 | -0.1 [-0.6, +0.4] |
| Polymarket | all | <10% | 2794 | 759 | 0.017 | 0.018 | +0.1 [-0.3, +0.6] |
| Polymarket | all | 10-30% | 737 | 465 | 0.198 | 0.201 | +0.3 [-2.3, +2.9] |
| Polymarket | all | 30-70% | 898 | 671 | 0.472 | 0.522 | +5.0 [+2.3, +7.9] |
| Polymarket | all | 70-90% | 129 | 118 | 0.791 | 0.767 | -2.3 [-9.3, +5.2] |
| Polymarket | all | >90% | 602 | 353 | 0.989 | 0.992 | +0.3 [-0.5, +0.9] |
| Polymarket | scheduled close | <10% | 2311 | 636 | 0.020 | 0.020 | +0.1 [-0.5, +0.6] |
| Polymarket | scheduled close | 10-30% | 721 | 453 | 0.198 | 0.193 | -0.5 [-3.0, +2.1] |
| Polymarket | scheduled close | 30-70% | 880 | 656 | 0.471 | 0.514 | +4.2 [+1.4, +6.9] |
| Polymarket | scheduled close | 70-90% | 112 | 103 | 0.789 | 0.732 | -5.7 [-14.5, +1.9] |
| Polymarket | scheduled close | >90% | 229 | 143 | 0.981 | 0.978 | -0.2 [-2.4, +1.5] |

### Favorite-longshot table, 7d before close

| venue | sample | bucket | markets | events | avg price | realized | realized - price, pp [95% CI] |
|---|---|---|---|---|---|---|---|
| Kalshi | all | <10% | 482 | 230 | 0.030 | 0.039 | +1.0 [-1.0, +3.2] |
| Kalshi | all | 10-30% | 239 | 165 | 0.173 | 0.163 | -1.0 [-5.7, +4.3] |
| Kalshi | all | 30-70% | 290 | 179 | 0.488 | 0.507 | +1.9 [-4.2, +8.5] |
| Kalshi | all | 70-90% | 161 | 123 | 0.798 | 0.795 | -0.3 [-6.8, +5.8] |
| Kalshi | all | >90% | 300 | 172 | 0.968 | 0.963 | -0.5 [-2.6, +1.4] |
| Kalshi | scheduled close | <10% | 211 | 122 | 0.037 | 0.038 | +0.1 [-2.6, +3.3] |
| Kalshi | scheduled close | 10-30% | 134 | 97 | 0.176 | 0.134 | -4.1 [-9.2, +1.9] |
| Kalshi | scheduled close | 30-70% | 127 | 97 | 0.484 | 0.402 | -8.2 [-16.8, -0.2] |
| Kalshi | scheduled close | 70-90% | 73 | 60 | 0.801 | 0.836 | +3.5 [-4.8, +11.2] |
| Kalshi | scheduled close | >90% | 149 | 83 | 0.966 | 0.973 | +0.7 [-2.2, +3.0] |
| Polymarket | all | <10% | 684 | 210 | 0.022 | 0.026 | +0.4 [-0.7, +1.7] |
| Polymarket | all | 10-30% | 312 | 187 | 0.203 | 0.215 | +1.2 [-2.9, +5.2] |
| Polymarket | all | 30-70% | 546 | 332 | 0.478 | 0.396 | -8.3 [-12.6, -3.4] |
| Polymarket | all | 70-90% | 88 | 71 | 0.801 | 0.784 | -1.7 [-13.0, +8.0] |
| Polymarket | all | >90% | 94 | 83 | 0.958 | 0.979 | +2.1 [-1.3, +4.4] |
| Polymarket | scheduled close | <10% | 438 | 154 | 0.025 | 0.023 | -0.3 [-1.5, +1.2] |
| Polymarket | scheduled close | 10-30% | 256 | 157 | 0.204 | 0.191 | -1.2 [-5.2, +2.8] |
| Polymarket | scheduled close | 30-70% | 461 | 279 | 0.474 | 0.328 | -14.6 [-18.7, -9.5] |
| Polymarket | scheduled close | 70-90% | 39 | 36 | 0.785 | 0.641 | -14.4 [-32.1, +1.3] |
| Polymarket | scheduled close | >90% | 39 | 39 | 0.955 | 0.974 | +1.9 [-3.5, +5.1] |

### Extreme buckets by category, 24h

| venue | category | h | bucket | markets | realized - price, pp [95% CI] |
|---|---|---|---|---|---|
| Kalshi | culture | 24h | <10% | 758 | -0.4 [-1.1, +0.5] |
| Kalshi | culture | 24h | >90% | 288 | +0.8 [-0.9, +2.1] |
| Kalshi | economics | 24h | <10% | 164 | +1.6 [-1.5, +5.4] |
| Kalshi | economics | 24h | >90% | 141 | -3.1 [-8.6, +0.7] |
| Kalshi | politics | 24h | <10% | 261 | -0.4 [-2.1, +1.3] |
| Kalshi | politics | 24h | >90% | 97 | -0.9 [-4.8, +2.4] |
| Kalshi | science_tech | 24h | <10% | 209 | -1.4 [-2.5, +0.2] |
| Kalshi | science_tech | 24h | >90% | 160 | -0.6 [-4.3, +2.2] |
| Kalshi | sports | 24h | <10% | 246 | +1.2 [-1.5, +4.2] |
| Kalshi | sports | 24h | >90% | 86 | -2.6 [-8.5, +2.9] |
| Kalshi | weather | 24h | <10% | 1026 | +0.3 [-0.8, +1.4] |
| Kalshi | weather | 24h | >90% | 30 | +0.2 [-7.4, +4.5] |
| Polymarket | crypto | 24h | <10% | 321 | +0.7 [-0.7, +2.5] |
| Polymarket | crypto | 24h | >90% | 117 | +2.1 [+1.7, +2.6] |
| Polymarket | culture | 24h | <10% | 240 | +0.5 [-1.2, +2.6] |
| Polymarket | culture | 24h | >90% | 60 | +1.2 [-3.1, +3.5] |
| Polymarket | economics | 24h | <10% | 185 | +1.5 [-1.0, +4.5] |
| Polymarket | economics | 24h | >90% | 47 | +1.4 [-3.8, +4.3] |
| Polymarket | politics | 24h | <10% | 248 | +0.8 [-0.8, +2.7] |
| Polymarket | politics | 24h | >90% | 68 | +0.6 [-4.5, +3.7] |
| Polymarket | science_tech | 24h | <10% | 239 | -0.4 [-1.3, +0.9] |
| Polymarket | science_tech | 24h | >90% | 54 | +3.8 [+3.1, +4.6] |
| Polymarket | sports | 24h | <10% | 217 | +3.0 [-0.0, +6.3] |
| Polymarket | sports | 24h | >90% | 3 | -29.6 [-93.0, +2.1] |
| Polymarket | weather | 24h | <10% | 872 | -0.6 [-1.5, +0.4] |
| Polymarket | weather | 24h | >90% | 3 | +3.6 [+0.4, +8.4] |

### Sensitivity, 24h before close (400 bootstrap replicates)

| venue | variant | markets | events | alpha [95% CI] | beta [95% CI] |
|---|---|---|---|---|---|
| Kalshi | main | 7769 | 2389 | 0.01 [-0.06, 0.08] | 0.99 [0.93, 1.04] |
| Kalshi | volume >= 10x threshold | 3083 | 1289 | 0.02 [-0.06, 0.10] | 0.94 [0.86, 1.01] |
| Kalshi | staleness <= 2 h | 4622 | 1650 | -0.02 [-0.10, 0.05] | 0.95 [0.88, 1.01] |
| Kalshi | one random market per event | 2389 | 2389 | 0.07 [-0.06, 0.18] | 0.93 [0.86, 1.01] |
| Kalshi | price in [0.02, 0.98] | 6056 | 2228 | 0.01 [-0.05, 0.07] | 0.96 [0.91, 1.02] |
| Kalshi | clip at 0.001 instead of 0.01 | 7769 | 2389 | 0.01 [-0.06, 0.08] | 0.99 [0.93, 1.04] |
| Kalshi | Kalshi: bid/ask mid instead of last trade | 11970 | 3438 | 0.03 [-0.03, 0.08] | 0.99 [0.95, 1.04] |
| Kalshi | scheduled close only (drop occurrence-triggered closes) | 6539 | 2104 | -0.01 [-0.07, 0.05] | 0.98 [0.94, 1.04] |
| Kalshi | same markets priced at both 24h and 1h | 7059 | 2307 | 0.01 [-0.05, 0.07] | 0.97 [0.92, 1.02] |
| Kalshi | excluding sports | 5861 | 1404 | 0.08 [-0.01, 0.17] | 1.02 [0.96, 1.08] |
| Kalshi | excluding weather | 5199 | 1733 | -0.05 [-0.13, 0.03] | 1.00 [0.94, 1.08] |
| Polymarket | main | 4821 | 1185 | 0.12 [0.03, 0.22] | 1.07 [1.01, 1.15] |
| Polymarket | volume >= 10x threshold | 1361 | 502 | 0.33 [0.21, 0.46] | 0.91 [0.81, 1.02] |
| Polymarket | staleness <= 2 h | 4821 | 1185 | 0.12 [0.03, 0.22] | 1.07 [1.01, 1.15] |
| Polymarket | one random market per event | 1185 | 1185 | 0.15 [-0.03, 0.33] | 1.10 [0.98, 1.27] |
| Polymarket | price in [0.02, 0.98] | 3236 | 1073 | 0.09 [0.01, 0.19] | 1.02 [0.94, 1.12] |
| Polymarket | clip at 0.001 instead of 0.01 | 4821 | 1185 | 0.10 [0.02, 0.20] | 1.04 [0.97, 1.12] |
| Polymarket | scheduled close only (drop occurrence-triggered closes) | 3968 | 997 | -0.05 [-0.15, 0.04] | 1.01 [0.93, 1.08] |
| Polymarket | same markets priced at both 24h and 1h | 4821 | 1185 | 0.12 [0.03, 0.22] | 1.07 [1.01, 1.15] |
| Polymarket | excluding sports | 4069 | 839 | 0.11 [0.02, 0.23] | 1.11 [1.03, 1.19] |
| Polymarket | excluding weather | 3209 | 918 | 0.16 [0.06, 0.27] | 1.05 [0.97, 1.14] |

### Sensitivity, 1h before close (400 bootstrap replicates)

| venue | variant | markets | events | alpha [95% CI] | beta [95% CI] |
|---|---|---|---|---|---|
| Kalshi | main | 16321 | 4362 | -0.04 [-0.09, 0.02] | 1.06 [1.02, 1.10] |
| Kalshi | volume >= 10x threshold | 5279 | 2154 | 0.02 [-0.06, 0.10] | 0.96 [0.90, 1.02] |
| Kalshi | staleness <= 2 h | 11028 | 3787 | -0.05 [-0.11, 0.02] | 1.00 [0.95, 1.05] |
| Kalshi | one random market per event | 4362 | 4362 | -0.03 [-0.12, 0.07] | 0.95 [0.90, 1.02] |
| Kalshi | price in [0.02, 0.98] | 8783 | 3426 | -0.06 [-0.11, 0.01] | 0.97 [0.92, 1.02] |
| Kalshi | clip at 0.001 instead of 0.01 | 16321 | 4362 | -0.04 [-0.09, 0.02] | 1.06 [1.02, 1.10] |
| Kalshi | Kalshi: bid/ask mid instead of last trade | 16334 | 4552 | 0.07 [0.02, 0.13] | 1.19 [1.14, 1.23] |
| Kalshi | scheduled close only (drop occurrence-triggered closes) | 14505 | 4003 | -0.05 [-0.12, 0.01] | 1.04 [1.00, 1.09] |
| Kalshi | same markets priced at both 24h and 1h | 7059 | 2307 | -0.06 [-0.15, 0.02] | 1.17 [1.10, 1.24] |
| Kalshi | excluding sports | 9576 | 1892 | -0.08 [-0.24, 0.07] | 1.25 [1.17, 1.33] |
| Kalshi | excluding weather | 13695 | 3695 | -0.04 [-0.10, 0.01] | 1.03 [0.99, 1.08] |
| Polymarket | main | 5160 | 1322 | 0.20 [0.11, 0.29] | 1.13 [1.06, 1.22] |
| Polymarket | volume >= 10x threshold | 1441 | 527 | 0.29 [0.16, 0.43] | 1.00 [0.90, 1.12] |
| Polymarket | staleness <= 2 h | 5153 | 1320 | 0.20 [0.11, 0.29] | 1.13 [1.06, 1.22] |
| Polymarket | one random market per event | 1322 | 1322 | 0.49 [0.30, 0.71] | 1.21 [1.07, 1.40] |
| Polymarket | price in [0.02, 0.98] | 2614 | 1042 | 0.16 [0.08, 0.27] | 1.07 [0.97, 1.18] |
| Polymarket | clip at 0.001 instead of 0.01 | 5160 | 1322 | 0.16 [0.06, 0.25] | 1.05 [0.97, 1.14] |
| Polymarket | scheduled close only (drop occurrence-triggered closes) | 4253 | 1124 | 0.12 [0.03, 0.22] | 1.09 [1.01, 1.18] |
| Polymarket | same markets priced at both 24h and 1h | 4821 | 1185 | 0.05 [-0.02, 0.15] | 1.09 [1.02, 1.18] |
| Polymarket | excluding sports | 4307 | 889 | 0.02 [-0.08, 0.13] | 1.13 [1.06, 1.22] |
| Polymarket | excluding weather | 3521 | 1046 | 0.27 [0.15, 0.39] | 1.13 [1.05, 1.25] |

### Near-certain prices by reference-close source (look-ahead diagnostic)

| venue | reference close | h | markets | share at <=2c or >=98c | of those, resolved against the price |
|---|---|---|---|---|---|
| Kalshi | close_time (scheduled) | 7d | 694 | 0.242 | 0.0119 |
| Kalshi | close_time (scheduled) | 24h | 6539 | 0.263 | 0.0070 |
| Kalshi | close_time (scheduled) | 1h | 14505 | 0.497 | 0.0042 |
| Kalshi | close_time (triggered) | 7d | 778 | 0.368 | 0.0210 |
| Kalshi | close_time (triggered) | 24h | 1230 | 0.360 | 0.0045 |
| Kalshi | close_time (triggered) | 1h | 1816 | 0.600 | 0.0018 |
| Polymarket | closed (triggered) | 7d | 491 | 0.411 | 0.0000 |
| Polymarket | closed (triggered) | 24h | 853 | 0.449 | 0.0000 |
| Polymarket | closed (triggered) | 1h | 907 | 0.884 | 0.0000 |
| Polymarket | end (scheduled) | 7d | 1220 | 0.213 | 0.0000 |
| Polymarket | end (scheduled) | 24h | 2069 | 0.368 | 0.0039 |
| Polymarket | end (scheduled) | 1h | 2251 | 0.494 | 0.0018 |
| Polymarket | game_start (scheduled) | 24h | 1899 | 0.260 | 0.0081 |
| Polymarket | game_start (scheduled) | 1h | 2002 | 0.331 | 0.0136 |

### Reliability bins, 24h before close

| venue | bin | markets | events | avg price | realized [95% CI] |
|---|---|---|---|---|---|
| Kalshi | [0.00,0.05) | 2121 | 880 | 0.017 | 0.013 [0.009, 0.017] |
| Kalshi | [0.05,0.10) | 631 | 504 | 0.069 | 0.087 [0.067, 0.109] |
| Kalshi | [0.10,0.20) | 778 | 600 | 0.144 | 0.143 [0.118, 0.169] |
| Kalshi | [0.20,0.30) | 688 | 569 | 0.244 | 0.257 [0.227, 0.288] |
| Kalshi | [0.30,0.40) | 623 | 546 | 0.343 | 0.364 [0.328, 0.400] |
| Kalshi | [0.40,0.50) | 655 | 592 | 0.447 | 0.460 [0.422, 0.493] |
| Kalshi | [0.50,0.60) | 588 | 532 | 0.543 | 0.526 [0.485, 0.564] |
| Kalshi | [0.60,0.70) | 342 | 327 | 0.640 | 0.643 [0.587, 0.693] |
| Kalshi | [0.70,0.80) | 279 | 244 | 0.747 | 0.753 [0.699, 0.806] |
| Kalshi | [0.80,0.90) | 253 | 220 | 0.844 | 0.834 [0.784, 0.882] |
| Kalshi | [0.90,0.95) | 169 | 147 | 0.921 | 0.864 [0.811, 0.918] |
| Kalshi | [0.95,1.00) | 642 | 356 | 0.981 | 0.986 [0.974, 0.995] |
| Polymarket | [0.00,0.05) | 1889 | 601 | 0.013 | 0.015 [0.010, 0.021] |
| Polymarket | [0.05,0.10) | 433 | 317 | 0.071 | 0.081 [0.057, 0.106] |
| Polymarket | [0.10,0.20) | 478 | 347 | 0.144 | 0.140 [0.112, 0.171] |
| Polymarket | [0.20,0.30) | 459 | 350 | 0.248 | 0.244 [0.207, 0.285] |
| Polymarket | [0.30,0.40) | 350 | 273 | 0.345 | 0.391 [0.349, 0.439] |
| Polymarket | [0.40,0.50) | 315 | 275 | 0.452 | 0.413 [0.357, 0.465] |
| Polymarket | [0.50,0.60) | 247 | 213 | 0.535 | 0.530 [0.467, 0.595] |
| Polymarket | [0.60,0.70) | 134 | 126 | 0.644 | 0.746 [0.676, 0.825] |
| Polymarket | [0.70,0.80) | 72 | 66 | 0.745 | 0.833 [0.740, 0.910] |
| Polymarket | [0.80,0.90) | 91 | 74 | 0.854 | 0.879 [0.800, 0.944] |
| Polymarket | [0.90,0.95) | 82 | 69 | 0.925 | 0.951 [0.896, 0.990] |
| Polymarket | [0.95,1.00) | 271 | 180 | 0.984 | 0.996 [0.988, 1.000] |

### Reliability bins, 1h before close

| venue | bin | markets | events | avg price | realized [95% CI] |
|---|---|---|---|---|---|
| Kalshi | [0.00,0.05) | 5832 | 1931 | 0.013 | 0.006 [0.004, 0.008] |
| Kalshi | [0.05,0.10) | 802 | 674 | 0.068 | 0.069 [0.051, 0.089] |
| Kalshi | [0.10,0.20) | 1160 | 938 | 0.142 | 0.143 [0.123, 0.165] |
| Kalshi | [0.20,0.30) | 960 | 832 | 0.242 | 0.217 [0.192, 0.242] |
| Kalshi | [0.30,0.40) | 790 | 689 | 0.347 | 0.325 [0.293, 0.357] |
| Kalshi | [0.40,0.50) | 791 | 734 | 0.445 | 0.468 [0.430, 0.502] |
| Kalshi | [0.50,0.60) | 693 | 615 | 0.541 | 0.545 [0.508, 0.580] |
| Kalshi | [0.60,0.70) | 542 | 516 | 0.645 | 0.672 [0.629, 0.710] |
| Kalshi | [0.70,0.80) | 503 | 484 | 0.746 | 0.704 [0.665, 0.744] |
| Kalshi | [0.80,0.90) | 560 | 517 | 0.844 | 0.816 [0.783, 0.850] |
| Kalshi | [0.90,0.95) | 359 | 342 | 0.922 | 0.889 [0.853, 0.920] |
| Kalshi | [0.95,1.00) | 3329 | 1691 | 0.986 | 0.991 [0.987, 0.994] |
| Polymarket | [0.00,0.05) | 2438 | 692 | 0.009 | 0.009 [0.006, 0.013] |
| Polymarket | [0.05,0.10) | 356 | 269 | 0.072 | 0.079 [0.051, 0.106] |
| Polymarket | [0.10,0.20) | 356 | 280 | 0.146 | 0.140 [0.106, 0.181] |
| Polymarket | [0.20,0.30) | 381 | 289 | 0.246 | 0.257 [0.216, 0.299] |
| Polymarket | [0.30,0.40) | 254 | 210 | 0.346 | 0.331 [0.277, 0.382] |
| Polymarket | [0.40,0.50) | 232 | 213 | 0.449 | 0.474 [0.411, 0.534] |
| Polymarket | [0.50,0.60) | 309 | 284 | 0.535 | 0.660 [0.602, 0.717] |
| Polymarket | [0.60,0.70) | 103 | 100 | 0.642 | 0.689 [0.602, 0.779] |
| Polymarket | [0.70,0.80) | 73 | 70 | 0.746 | 0.767 [0.667, 0.864] |
| Polymarket | [0.80,0.90) | 56 | 52 | 0.850 | 0.768 [0.653, 0.879] |
| Polymarket | [0.90,0.95) | 46 | 45 | 0.929 | 0.957 [0.889, 1.000] |
| Polymarket | [0.95,1.00) | 556 | 323 | 0.993 | 0.995 [0.987, 1.000] |
