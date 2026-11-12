# Sudden-move reversal study

## Result

**No fee-adjusted edge found.** A pooled XGBoost filter selected 77 of 412 eligible out-of-sample event setups from January 2025 through September 2026. Seventy-four strict-trade-through candle fills produced 29 net-profitable fills (39.19%), but lost **9.04R / 56.71 USDT** at the fixed risk size after maker-entry, taker-stop/timeout fees, stop slippage and funding. The mean was **−0.122R per fill**. Its seven-day joint-market block-bootstrap 95% interval was **−0.386R to +0.182R per fill** and **−190.18 to +69.24 USDT**. The sample is too small and the interval includes losses and gains.

The same selected fills lost 40.30 USDT under the unrealistic best-case maker/maker fee scenario and 84.35 USDT when both sides paid the repository's 10 bp taker assumption. The model's 39.19% net win rate includes positive time exits; only 19 of its 74 fills reached target, while 42 stopped and 13 timed out. Three of 77 submitted orders expired unfilled.

| Out-of-sample policy | Submitted | OHLC fills | Net wins | Net win rate | Net R / fill | Net USDT on 10,000 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pooled model, +0.05R estimated-EV cutoff | 77 | 74 | 29 | 39.19% | −0.122 | −56.71 |
| Fade every confirmed event | 412 | 381 | 162 | 42.52% | −0.013 | −34.21 |
| Continue every confirmed event | 412 | 377 | 154 | 40.85% | −0.026 | −60.52 |

The model did not beat the simple fade-every-event control on net expectancy. A post-hoc random-time/random-side diagnostic, added after the first results were inspected, matched the model's submitted order counts by coin and quarter. Across 2,000 assignments, its maker-entry/taker-stop mean was **+0.011R per fill / +4.70 USDT**, with a 2.5th–97.5th randomization range of **−0.218R to +0.262R** and **−97.03 to +116.45 USDT**. This is a diagnostic distribution, not a confidence interval or new holdout. The model's result is not evidence of an edge over random timing and direction.

The historical risk replay split 10,000 USDT into four 2,500 USDT coin sleeves, risked 0.25% of each sleeve per trade (6.25 USDT each at the start), capped each sleeve at 1x notional, and halted at a 1% daily realized loss or 5% account drawdown. The pooled model ended at 9,943.29 USDT with a 0.85% closed-equity max drawdown. No daily-loss, drawdown or notional cap activated. This is a simulation and does not model unrealized-loss halts.

## Signal and order rules

The candidate is a three-bar (15-minute) log-price move at least three standard deviations from the preceding seven days of non-overlapping 15-minute returns. After three more completed five-minute bars, it must bounce at least 0.25 event-time ATR in the opposite direction. A partial-hour ATR(14) above 1.5 times its prior seven-day average blocks the setup. The model sees only data at the signal close: shock magnitude, 1h and 24h pre-shock trend, bounce size, volatility ratio, 15-minute turnover expansion, taker-buy imbalance, BTC's lagged one-hour return, and the latest already-settled funding. Coin indicators are included.

It posts a half-five-minute-ATR limit, sets a swing/ATR stop at least two ATR and 1.5% of price away, and targets 1.5 planned net R. The entry expires after six hours. A filled trade stops, targets or times out after 24 hours. The replay requires a strict trade-through, charges 2 bp maker entry, 10 bp taker stop/timeout, 2 bp stop slippage and historical funding. The best-case sensitivity assumes maker fees on both legs; taker/taker uses 10 bp each leg.

The filter is directional mean reversion, **not arbitrage**. It has no historical order book, queue position, latency or partial-fill model. Even a strict OHLC trade-through can overstate maker fills; the 74/77 fill rate is not a live fill estimate. The study has no open-interest or liquidation feed, options data or depth data. Taker-buy volume and price action describe observed pressure but cannot establish why a cascade happened. Research on seven large BTC cascades also finds that early-warning patterns vary across events, which is why this project does not label a price shock as a liquidation without liquidation evidence ([study](https://arxiv.org/abs/2607.27070)).

## Walk-forward and training

The rules were written in [the protocol](../shock-plan.md) before scoring. The pooled model refit for each quarter with expanding prior-only training, a later chronological calibration slice, a 30-hour full-label purge and 24-hour embargo. The test windows are 2025 Q1–Q4 and 2026 Q1–Q3. No test P&L was used to tune the 3σ event level, confirmation, volatility gate, geometry, cost assumptions or +0.05R trading hurdle. The post-hoc random control is disclosed separately in [its addendum](../shock-random-check.md).

The final paper model trained on 515 prior eligible rows and calibrated on 130 later rows through September 2026. Its parameters and SHA-256 are in [freeze.json](freeze.json). The quarterly folds used 179–458 training rows and 45–116 calibration rows. A recent research paper found substantial overfitting in boosted crypto microstructure models under purged walk-forward evaluation and no strategy surviving its fee model; that supports using a small, regularized model and demanding further live paper evidence, not assuming profitability ([original study](https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2026.1811716/full)).

## Reproduce

The candle and funding archives are public Binance USDT-perpetual data. Local market data and fitted models stay under ignored `data/` paths. Download any missing candle/funding archives with `shock_research.py --prepare`, then reproduce:

```powershell
.venv/Scripts/python.exe -m unittest discover -q
.venv/Scripts/python.exe shock_research.py --prepare
.venv/Scripts/python.exe shock_research.py
.venv/Scripts/python.exe shock_signal.py --equity 10000
```

The script saves [all detected events and rejection reasons](events.csv), the OOS [setup and outcome ledger](signals.csv), [results and bootstrap summaries](results.json), and a frozen model in the ignored `data/shock/model.joblib`. `shock_signal.py` reads public Binance data only and never places an order. A setup stays `WAIT` unless both the historical sample clears a positive lower confidence bound with at least 220 out-of-sample fills and a separate eight-week prospective paper period is completed. No such evidence exists yet.

## Read-only sample

At 2026-11-12 13:47 UTC, the current public-data scan returned **WAIT for BTC, ETH, SOL and AVAX** because none had a fresh qualifying shock at the latest confirmed bar. [Timestamped scan](live-check-2026-11-12.json).

At 2026-11-12 13:33 UTC, the scanner found an ETH long-shaped watch setup after a 3.21σ downward 15-minute move and a 1.06 ATR bounce. Its model estimate was 89.4% probability of the OHLC fill proxy, 29.8% TP-before-stop conditional on that proxy, and +0.058R expected net return. Rounded geometry was entry 2,004.91, stop 1,974.83 and target 2,054.99. On a hypothetical 10,000 USDT account, the 0.19 ETH quantity risked 6.24 USDT. **Decision: WAIT**, because historical net expectancy was negative, its interval crossed zero, and the paper period has not started. The observed perpetual/spot basis was −5.77 bp and was context only, not a trained feature.
