# RSI and Bollinger Bands on Aahil Wave

Compare the original model, the model plus Wilder RSI(14), the model plus Bollinger %B and relative bandwidth (20 closes, two population standard deviations), and the model plus all three inputs. Compute indicators on closed five-minute candles ending immediately before each hourly decision. Present them to the two existing classifiers as continuous predictors. Use the existing temporal calibration, four quarterly 2025 folds, dated coin membership, expected-net-R threshold, fees, funding and six-hour order replay. Use one parameter setting per indicator. This is a retrospective feature comparison on previously examined dates.

Judge each addition by net R per submission, net return and marked drawdown. Report win rate with its fill denominator. Use paired seven-day blocks of UTC exit-day net R for descriptive uncertainty on incremental total R. Treat any promising result as a hypothesis for new data. The December prospective model is frozen.

[RSI calculation](https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/trading-with-momentum-transcript.pdf) · [Bollinger's indicator rules](https://www.bollingerbands.com/bollinger-band-rules)

## Results

| Inputs added | Submitted | Wins / fills | Win rate | Net R | Net R/submission | Net USDT | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 59 | 12 / 34 | 35.3% | −7.61 | −0.129 | −382.16 | 1.16% |
| RSI | 69 | 14 / 40 | 35.0% | −10.47 | −0.152 | −523.94 | 1.35% |
| Bollinger bands | 17 | 3 / 7 | 42.9% | −0.97 | −0.057 | −49.16 | 0.46% |
| Both | 27 | 5 / 11 | 45.5% | −0.75 | −0.028 | −38.41 | 0.70% |

Both indicators together selected fewer trades, had the highest observed win rate and still had negative expectancy. The paired change versus baseline was +6.87R over the year, with a descriptive 95% block-bootstrap interval of −8.09R to +22.77R. The interval includes a worse result. It does not adjust for testing three feature extensions. RSI alone worsened both net R and drawdown. Keep the additions in research.

Wins count profitable fills after both fees, modeled slippage and funding. Submissions include post-only rejections. Drawdown uses the combined five-minute marked equity of four 10,000 USDT sleeves. BTC, ETH and SOL qualified for the dated membership; AVAX generated no trades. A band-based fixed entry rule would be a separate experiment.

Run `python wave_indicator_study.py` after preparing the base study's archives with `wave_inputs.py` and `wave_context.py`. The script rebuilds and checks the original 65 baseline signals against their published ledger. [Study code](../../wave_indicator_study.py) · [All orders](orders.csv) · [Results and paired intervals](results.json)
