# Where to put the stop: candidates fixed before scoring

In the TP/SL study, 1,706 of the 5,041 trades that reached the first target had their remaining half stopped at or near entry. This study tests whether a different stop rule does better. It uses a development half and a confirmation half, so the result is not fitted to the same coins it is judged on.

## Split and fixed parts

- **Split:** the same two halves of 139 coins as the [filter check](trend-improve-plan.md), from seed 20261120.
- **Unchanged from [trend-tpsl-plan.md](trend-tpsl-plan.md):**
  - entries;
  - half taken at +1R and the +3R cap;
  - trend exit and 30-day timeout;
  - 2% risk, 2x cap, borrowing charge and costs.
- **R:** always measured from the initial stop.

## Stop candidates

| Name | Initial stop | Stop on the remaining half after the first target |
| --- | --- | --- |
| base | entry − 2 × ATR | max(entry, highest close − 2 × ATR) |
| no_breakeven | entry − 2 × ATR | max(initial stop, highest close − 2 × ATR) |
| wide_trail | entry − 2 × ATR | max(entry, highest close − 3 × ATR) |
| wide_no_breakeven | entry − 2 × ATR | max(initial stop, highest close − 4 × ATR) |
| wide_initial | entry − 3 × ATR | max(entry, highest close − 3 × ATR) |

## Selection and confirmation

- **On the development half:** choose the candidate with the highest equal-weight basket Sharpe. If base wins, nothing changes.
- **On the confirmation half:** compare the chosen candidate with base.
  - Statistic: the Sharpe difference.
  - Interval: 95% 60-day moving-block bootstrap, 5,000 resamples, seed 20261121.
  - **Adopt only if the lower bound is above zero.**
- **Also reported, for every candidate on both halves:** win rate, mean R and the share of runners closed within 0.1R of entry.
