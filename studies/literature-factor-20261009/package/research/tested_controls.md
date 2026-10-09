# Executed comparisons

All ten score controls below appear in each candidate's recorded overlap results. They are representative comparison formulas, implemented in `src/factorlab/features.py:controls`; they are not claims to reproduce an author's complete trading strategy. Scores share the tested calendar, eligible stocks and missing-value rules. The paired account baseline averages the eight dense ranked controls, excluding the sparse strong-close event.

| Control | Executed computation |
|---|---|
| reversal5 | Negative five-session close return |
| momentum20 | Twenty-session close return |
| weak_close | Negative close location within the day's high–low range |
| gap_diff4 | Four-session sum of open/previous-close minus close/open |
| gap_diff4_amount | gap_diff4 multiplied by cross-sectional amount rank |
| pv_anti5 | Negative five-session close/volume correlation |
| rev4_amount_highpos | Four-session reversal × amount rank × twenty-session price position |
| strong_close_event | Close location on days with return at least 9.5%; zero otherwise |
| liquidity_cv_abnormal | Negative sum of ranked twenty-session amount CV and five/twenty-session amount ratio |
| existing_equal_rank | Average centered percentile rank of eight dense controls |

The executed portfolio ablations use reversal5, momentum20, existing_equal_rank, and a fixed-seed permutation of leader identities. Executed account diagnostics use 2×/3× modeled friction, one-session extra delay, CNY 10 million capital, and the higher-liquidity half-universe. These outputs are in `results/metrics.json` and the corresponding aggregate daily ledgers.
