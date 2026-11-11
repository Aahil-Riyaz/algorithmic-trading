# RSI and Bollinger Bands on Aahil Wave

Compare the original model, the model plus Wilder RSI(14), the model plus Bollinger %B and relative bandwidth (20 closes, two population standard deviations), and the model plus all three inputs. Compute indicators on closed five-minute candles ending immediately before each hourly decision. Present them to the two existing classifiers as continuous predictors. Use the existing temporal calibration, four quarterly 2025 folds, dated coin membership, expected-net-R threshold, fees, funding and six-hour order replay. Use one parameter setting per indicator. This is a retrospective feature comparison on previously examined dates.

Judge each addition by net R per submission, net return and marked drawdown. Report win rate with its fill denominator. Use paired seven-day blocks of UTC exit-day net R for descriptive uncertainty on incremental total R. Treat any promising result as a hypothesis for new data. The December prospective model is frozen.

[RSI calculation](https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/trading-with-momentum-transcript.pdf) · [Bollinger's indicator rules](https://www.bollingerbands.com/bollinger-band-rules)
