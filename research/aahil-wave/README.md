# Did a pooled Wave 5 model find an edge?

The 2025 walk-forward simulation produced **12 profitable fills out of 34**. The 65 positive-EV opportunities led to 59 submitted orders. Twenty were marketable when activated and rejected, four were replaced, one expired and 34 filled. Six opportunities arrived while a position was open. The strategy lost **7.61R**, or **382.16 simulated USDT** across four 10,000 USDT sleeves, a return of −0.96%. Mean expectancy was −0.129R per submission and −0.224R per fill. The 95% interval for the latter was −0.666R to +0.167R, resampling seven-day calendar blocks jointly across coins 5,000 times. Count uncertainty and clustered execution losses make the evidence insufficient for positive expectancy. [Examined policy orders](wave-orders.csv) · [Results](results.json) · [Uncertainty](uncertainty.json)

| Cumulative feature ladder | Profitable fills / fills | Net R | Simulated USDT |
| --- | ---: | ---: | ---: |
| Price, side, asset indicators and ATR | 1 / 3 | −0.91 | −45.60 |
| Add confirmed Wave 5 features | 8 / 30 | −11.05 | −547.17 |
| Add one-hour normalized executed volume delta | 7 / 28 | −12.06 | −597.18 |
| Add last funding rate and Binance perp/spot basis | 11 / 36 | −12.72 | −633.12 |
| Add BTC return lagged by a full bar | 12 / 34 | −7.61 | −382.16 |
| Randomize the full model's entry timing | 10 / 36 | −15.08 | −744.38 |
| Cash | 0 / 0 | 0 | 0 |

The random timing control shifts each qualifying entry forward by 0–55 minutes within its original hour using one fixed seed, preserves coin, side and price-relative geometry, and uses the same six-hour entry, protective exits, costs and sequential fill policy. It tests local timing. It preserves the model's market/day selection. One seed and six observed policies cannot establish that any strategy has a positive edge.

The training labels price hypothetical standalone orders on every eligible hourly boundary. Strategies are evaluated using one open position and at most one pending entry per coin. Among 25,893 held-out standalone proposals, calibrated fill probability averaged 65.19% versus 65.20% observed, Brier score 0.2267. On 16,882 fills, mean conditional TP probability was 38.57% versus 38.28% observed, Brier 0.2351. The scores are close to those of a constant predictor using those empirical marginal rates. Aggregate calibration alone does not establish discrimination at the positive-EV threshold. [Reliability bins](calibration.csv)

## Liquidity, validation and the held period

Binance futures and same-venue spot archives cover December 2023 to December 2025. December 2023 supplies warmup and ranking inputs. Each month retained up to three contracts within the four-coin mandate using only the preceding month's turnover and sampled spread/depth. BTC, ETH and SOL qualified for all 24 evaluation months. AVAX was eligible for consideration and never ranked in the top three. The study therefore supplies zero AVAX performance evidence. Full exchange-wide or delisted-symbol inference would require a broader historical mandate. [Dated membership](membership.csv) · [Specification](../aahil-wave-protocol.md)

Four expanding quarterly 2025 folds train on earlier, resolved events. A calibration segment is reserved within each training period, with a 24h gap. Each validation quarter drops its final 30h of decisions to allow the same worst-case six-hour entry and 24-hour exit horizon regardless of outcome. The fitted research artifact uses observations through December 2025. All 2025 results are development evidence. December 2026 is reserved for a later prospective evaluation.

Combinatorial validation holds two of the four 2025 quarters at a time, refits the classifiers/calibrators, and excludes training overlaps and embargoes around both test blocks. Later training features also clear the 72h pivot window and ATR initialization. Three paths cover each quarter once per path. These diagnostics measure standalone proposals and allow later quarters in training. The two paths with submissions averaged −0.179R and +0.021R, and the third submitted nothing. [Six test combinations](cpcv.csv) · [Recombined paths](cpcv-paths.csv)

## Sparse flow ablations and plots

First-of-month Binance futures metrics and published liquidations supply observable OI and liquidation changes. The prefix of the first day's real L1 feed supplies signed best-quote order flow imbalance and size-weighted microprice. Missing observations are excluded. Each additional family is compared against a separately fitted control on precisely the same timestamps. These rows overlap heavily and describe standalone proposals. The pooled net R across selected proposals remained negative for every family, including the improvements from adding OFI (−19.48R to −16.48R) and OI change (−4.71R to −2.74R). The sparse panels cannot establish a transferable improvement at ordinary times of day. [Ablations and per-fold coverage](sparse-ablations.csv) · [Binance archive schema](https://github.com/binance/binance-public-data) · [Tardis first-day historical data](https://docs.tardis.dev/downloadable-csv-files)

[Hour × weekday, fill fraction, development threshold sensitivity and TP-model TreeSHAP](diagnostics.png) · [Top-25 depth with actual trade prints](depth-trades.png) · [TreeSHAP by feature and fold](shap.csv)

Blank cells denote no sample. Offset in basis points scales directly with current ATR by design, so some offset × volatility cells cannot occur. The hour × weekday display includes the actual fill count. The robustness grid shows hypothetical standalone reward at alternative probability and EV thresholds on development folds. The published policy threshold remains 0.05R. SHAP contributions use a systematic one-in-eight subsample of the held-out observations, measured on the pre-calibration raw model margin.

## Reproduce

Run in order from the repo root:

```sh
python -m pip install -r requirements-wave.txt
python wave_inputs.py
python wave_context.py
python wave_validation.py --rebuild
python wave_report.py
python wave_plots.py
python -m unittest test_wave_research
```

The two collectors use unauthenticated market data. The study writes the fitted model, candidate data, out-of-fold probabilities and detailed policy ledger under the ignored `data/aahil-wave` directory. All timestamps are UTC. Funding enters signed net P&L. The notebooks and exchange account credentials are unnecessary. The model's 10 bp per-leg fee is a research charge. Live incentives, fill quantity, queue position, entry latency and maker rejection still require prospective measurement. The prospective service also imposes freshness, risk and actionability gates. Its post-gate stream needs its own performance record.
