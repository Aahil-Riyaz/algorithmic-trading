# Does a broad funding-carry basket beat cash?

**No established edge.** Holding the ten highest-funding Binance perpetuals against spot lost 2,178.86 USDT on 10,000 in the January 2021 to October 2026 historical simulation (CAGR −4.1%). The 95% bootstrap interval for annual return was −7.05% to −1.77%, so the lower bound is not positive. In the 2024-on regime it lost 575.50 USDT (CAGR −2.5%) against a 3.5% CAGR for 4% cash. The plan's pass rule needed both a positive lower bound and a win over 4% cash. Both failed. Everything here is a historical simulation. No order was placed and no real fill was measured.

Rules were fixed before any return was computed. [Plan](../cross-carry-plan.md) · [Code](../../cross_carry.py) · [Tests](../../test_cross_carry.py)

## Results

Each strategy starts with 10,000 simulated USDT and includes fees and slippage. Cash controls are zero return and 4% simple annual interest.

| Period | Strategy | Net USDT | CAGR | Sharpe | Max drawdown | Months positive |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2021-01 to 2026-10 | Top-10 carry | −2,178.86 | −4.1% | −1.54 | −21.8% | 8 of 70 |
| | Equal-weight 40 | −3,725.12 | −7.7% | −4.27 | −37.3% | 5 of 70 |
| | Cash, 0% | 0.00 | 0.0% | n/a | 0.0% | n/a |
| | Cash, 4% simple | +2,334.25 | 3.7% | n/a | 0.0% | n/a |
| 2024-01 to 2026-10 | Top-10 carry | −575.50 | −2.5% | −1.35 | −7.0% | 2 of 34 |
| | Equal-weight 40 | −1,122.86 | −5.6% | −4.81 | −15.2% | 3 of 34 |
| | Cash, 4% simple | +1,134.25 | 3.5% | n/a | 0.0% | n/a |

Top-10 carry by calendar year (net USDT): 2021 −1,444.65; 2022 −7.58; 2023 −151.14; 2024 −256.05; 2025 −131.84; 2026 (to October) −187.62. It lost in every year. [All periods and splits](results.json)

**Where the money went.** Over the full run Top-10 earned 1,551.87 USDT of funding, lost 3,336.95 on the spot-perpetual price difference, and paid 209.41 in fees and 184.38 in slippage. Equal-weight 40 earned 1,169.07 of funding against a 4,392.16 basis loss. The basis loss is almost entirely the liquidation stress. Top-10 was force-closed 58 times and Equal-weight 40 355 times, plus 29 delistings. A liquidation buys the perpetual back at the daily high plus 20 bp and sells spot at the close, so a wick on a pumping coin costs roughly the high-to-close gap on that slot. 2021, when many coins paid over 100% annualised funding while also rallying hard, supplied most of it (−1,444.65 USDT for Top-10).

**Hurdle.** At the plan's costs a coin needs about 14.1% annualised trailing funding (about 16.5% outside the top 20 by volume) to qualify. Top-10 held on average 2.5 coins per month and no coin at all in 45 of 70 months. The rest sat in cash at zero return.

## Stresses

| | Top-10 full | Top-10 2024-on | Equal-weight 40 full |
| --- | ---: | ---: | ---: |
| Positive funding halved, net USDT | −2,947.24 | −701.47 | −4,400.22 |
| Bootstrap 95% annual return, actual funding | −7.05% to −1.77% | −4.70% to −0.73% | −9.93% to −5.63% |
| Bootstrap 95% annual return, halved funding | −9.30% to −2.91% | n/a | −12.08% to −7.11% |

The bootstrap resamples 2,000 circular 30-day blocks of daily returns with a fixed seed. The intervals describe sampling noise in one history. Coins share market moves, so the effective sample is smaller than the day count.

## Sensitivity to the leverage reading (not part of the pass test)

The plan says half of slot capital buys spot and half is perpetual margin, yet also says the perpetual runs at about 2x. Those two statements conflict: half and half is 1x. The primary run takes the stricter reading, a margin ratio computed as if margin were half the perpetual notional (2x), so a short is force-closed when the daily high reaches about 143% of its entry price. Sizing still follows the half-and-half split. Re-running with margin equal to full notional (1x, liquidation near 190%) changes the picture materially:

| 1x-margin reading | Liquidations | Full net USDT | Full bootstrap 95% | 2024-on net USDT |
| --- | ---: | ---: | ---: | ---: |
| Top-10 carry | 20 | +757.33 | −0.88% to +3.68% | −90.24 |
| Equal-weight 40 | 159 | −1,905.55 | −5.17% to −1.78% | −761.38 |

Even under the kinder reading Top-10 has a lower bound below zero and lost money in the recent regime, so the verdict does not change. This is a disclosure, not a revision of the plan. The result is sensitive to the stress assumptions as much as to funding itself.

## Data and method

- 465 ASCII USDT symbols exist in the Binance public archive on both the perpetual and spot legs, excluding multiplied contracts (1000PEPE and similar). 464 had usable files. 95 coins were ever held by Top-10. The listing keeps delisted contracts. 50,301 files were fetched. [Binance public data](https://github.com/binance/binance-public-data)
- 70 monthly decisions. All 70 had at least 40 eligible coins, so the 40-coin universe was always full.
- Funding uses each print's rate times that day's perpetual close, not the mark price, which the archive lacks. Spot timestamps switch from milliseconds to microseconds from 2025, and the loader normalises by digit count.
- Every ledger day reconciles: equity change equals funding plus basis minus fees minus slippage, checked to 1e-6, or the run raises.
- Three coin-months were checked by hand against raw archive files (HOTUSDT 2021-12, VETUSDT 2021-06, CYBERUSDT 2023-12). Position size implied independently by funding, by basis and by entry fees agreed to four significant figures, and the recomputed trailing funding score matched the ledger.

## Choices where the plan was ambiguous

- **Fill timing.** "Next daily open after the decision" is the open of the second day of the month, because the first day's open coincides with the decision instant. The last month closes at its final daily close, with exit costs.
- **Funding at the boundary.** A settlement stamped exactly at the entry open is not earned, and one stamped exactly at an exit open is not earned. Continuing positions earn every print.
- **Liquidation day.** Positive funding on the liquidation day is dropped. Negative funding is kept. Fees apply on the buyback and the spot sale, and spot slippage applies. The 20 bp is the perpetual's slippage.
- **Margin ratio.** Funding earned and the unused margin buffer do not count toward margin. Only daily highs are checked.
- **Hurdle.** Projected 30-day funding is the trailing score times 30/365 on the perpetual notional. It must exceed round-trip fees and slippage plus 4% annualised on the slot capital, which is twice the leg notional. The same hurdle gates continuing positions. Coins ranked beyond the top 20 in the 40-coin universe pay doubled slippage.
- **Resizing.** Continuing coins keep their quantity. Only entering coins are sized at 10% (2.5% in the control) of equity at the decision instant. If cash is short, the slot shrinks.
- **Eligibility.** "30 settled funding prints" is read literally as 30 prints, not 30 days. Volume is the smaller of the 30-day spot and perpetual quote volume.
- **Gaps and delistings.** The first day missing a bar on either leg closes the pair at the previous close with normal costs.
- **Pass test.** Full-period bootstrap lower bound above zero and 2024-on CAGR above 4%.
- **Stablecoin and other pairs.** None were excluded beyond the plan's rules.

## Look-ahead and survivorship checks

Decisions read only bars dated before the decision day and funding prints stamped before 00:00 UTC of the decision day. A unit test overwrites all later data with extreme values and confirms the decision is unchanged. Delisted symbols stay in the universe through the archive listing. A coin that vanishes mid-hold is closed at its last close rather than dropped. Sizing uses the equity at the decision instant, not at the fill. Entry prices use the day-two open, which is after the decision.

## Files

- [results.json](results.json) · [months.csv](months.csv), per coin-month ledger for both strategies
- [monthly-returns.png](monthly-returns.png) · [funding-heatmap.png](funding-heatmap.png) · [equity-curves.png](equity-curves.png)

```
python cross_carry.py            # download (cached under data/cross-carry/, about 50,000 files) and run
python cross_carry.py --skip-download
python -m unittest test_cross_carry -v
```
