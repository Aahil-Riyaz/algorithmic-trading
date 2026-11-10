# Can exchange prices reproduce the alerts?

**Verdict for the pasted sample.** Positive fee-adjusted expectancy did not reproduce under any of the three specified execution-cost scenarios. The friend's long-run return is unknown. The evidence is a hand-copied selection, public contract prices and retrospective rule hypotheses. It contains no exchange order acknowledgments, fill records, individual fee tier, complete signal population or source code.

## One contradictory trade

One of the six reported take-profits fails even the closest reconstruction. For the November 5 AVAX long at 21:34 UTC, the alert specified entry 8.2120, stop 8.1925 and target 8.2412. At 23:01 the Binance minute **opened at 8.223, traded as low as 8.190 and as high as 8.225**. Both entry and stop lay on that downward path, while the target was above the entire candle. At 23:02 the high reached 8.248. The TP post came at 23:04. A different venue, mark-price stop or delayed protective order could change that sequence. No such detail was supplied. [Binance USD-M trade candle endpoint](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data)

## Independent rules versus retrospective rules

The price-only replay uses the published entry, stop, target, side and UTC alert minute. Orders start at the next full minute and expire eight hours **from the alert**. A limit must trade through, with full execution at the posted entry assumed. A stop wins if both exits trade in one candle. A target seen on the fill candle is deferred unless entry was already crossed at its open. A stop gapping through fills at the worse open. A still-open position is censored after 24 hours from fill or at the exchange cutoff. The copied alerts give no holding timeout. Exchange candles cannot establish FIFO position, exact latency, available size, partial fills, missed updates or mark-versus-contract stop triggers.

The parser identified 54 unique setups. Against public contract prices through **November 10, 20:10 UTC**, 20 filled (37.0% of all alerts), 30 expired, four were still pending, and none of the 20 positions remained open. Eight reached target and 12 stopped. The price-only rule disagreed with 39/50 comparable reported outcomes. In 28 cases it returned an expiry where a cancellation was reported. Six more would have filled if left live after their reported invalidation (two TP, four SL). Two reported invalidations were still pending without a cancellation at the cutoff. Both reported expiries expired in the replay.

A second replay imports the Wave 1 level **from the later invalidation post**. It can audit whether the cited level was crossed before a fill, but cannot implement a point-in-time predictor. For longs it tests a touch from below and for shorts a touch from above. A minute crossing both entry and Wave 1 is marked ambiguous. All 36 cited levels were reached 1–2 minutes before their updates, before price traded through entry. None of these 36 levels was already breached by the posted Price. The other 18 setups lack the level, so independent false-negative cancellation checks are impossible.

| Stop rule on one-minute bars | Mismatches among 14 reported closes and 2 expiries |
| --- | ---: |
| Keep the posted stop | 5 / 16 |
| Move to entry after a 0.5R favorable excursion | 1 / 16 |
| Move to entry after a 1R favorable excursion | 3 / 16 |
| After 30 min in position, move to entry on the first profitable bar close | 5 / 16 |

Stop moves take effect on the next bar. Combining the retrospective Wave 1 check with the best-fitting 0.5R trigger reproduced **51/52** resolved categories, including all four reported break-evens. Two unresolved posts are outside this denominator. This selects a trigger on the very posts used to assess it. The close match is evidence for a hypothesis about the rules, and does not verify the live bot or show its trigger uniquely.

| Sample and rule | Filled | Gross total R | Maker/maker net R per fill | Maker/taker-stop | Taker/taker |
| --- | ---: | ---: | ---: | ---: | ---: |
| Price-only, leave live until fill/expiry; fixed stop | 20 | −0.007 | −0.170 | −0.271 | −0.509 |
| Cited Wave 1 levels and fitted 0.5R move | 14 | +2.185 | −0.007 | −0.115 | −0.332 |

The posts claim +5.00R for those 14 closes. The reconstructed middle-cost total on the same 14 is −1.61R. Gross R can deviate from a posted −1/0/+1.5 because gaps and displayed precision affect realized prices. Under the fixed-stop price-only rule, middle-cost net total is −5.42R, or −0.108R per 50 resolved submissions. Pending and unmatched records carry missing realized payoff. Observed funding settlements contributed zero to this primary run.

Fee/slip inputs in basis points are 2 maker, 5 taker and 1 adverse slippage per taker leg. Maker/taker-stop assumes passive entries and TPs, taker SL and BE exits. Maker/maker is an optimistic cost sensitivity on the same paths, including stops. Taker/taker charges even the entry and TP at taker costs on the same levels. Funding is computed from actual rate and mark records where applicable, charging a possible boundary debit conservatively. Unknown account-specific fees, private executions and funding cashflows cannot be verified. [Official futures fee page](https://www.binance.com/en/fee/futureFee)

## Timing, rounding and controls

- With Dubai timestamps converted to UTC, 37/54 posted prices lie inside their one-minute range. The median absolute distance to that minute's close is 6.84 bp. Shifting four hours earlier gives 1/54 inside and 170.45 bp median error. Four hours later gives 3/51 and 82.52 bp. Three later control minutes were beyond cutoff. At October 29 16:17 UTC AVAX posted 8.9990 against 8.9930 close. At 16:23 ETH posted 2358.3200 against 2357.51 close. At October 30 00:07 BTC posted 78075.20 against 78175.00 close. A minute stamp supports a timezone check, not exact quote synchrony.
- **All 54** posted prices were already beyond the target in the proposed side's direction. Median distance to entry was 136.78 bp. These were resting pullbacks requiring price to return to entry first. The distance measures how far away execution was; it cannot reveal the age of an unposted pivot.
- The five-minute view aggregates the same Binance minute trades on UTC five-minute boundaries, including partial first/expiry bars. Four terminal labels changed relative to one minute. Against the 16 closed/expired labels it disagreed eight times versus five at one minute. Using touch rather than trade-through or including the entire announcement minute changed zero terminal categories in this sample. Including that minute is an optimistic latency sensitivity.
- Perturbing entry, stop and target by half their posted least displayed unit at all eight box corners changed zero price-only terminal categories. Substituting rounded, sometimes scientific-notation entry and exit levels copied from the outcome message also changed zero. That is a sensitivity test. The bot's internal prices and venue tick rounding remain unknown.
- In 100 seeded random-time replays each opportunity keeps its coin, UTC day, side, relative price-to-entry distance, stop/target geometry, eight-hour expiry, costs and amount of follow-up. The entire bracket is scaled to the new reference price. The middle-cost median was **−0.185R per resolved signal** versus the rule's −0.108R, within the central randomization range **−0.395R to +0.048R**. Random runs had 50–53 resolved signals and median fill rate 46.3%. This distribution answers a matched timing question. It is not a confidence interval on sustainable profitability.

## Reproduce and inspect

After parsing the original paste, run:

```sh
python discord_replay.py --signals data/discord-audit/signals.csv --through 2026-11-10T20:10:00+00:00
python -m unittest test_discord_replay
```

The local row-level output is `data/discord-audit/rebuilt.csv`. It includes original timestamps and levels, linkage to source lines, reported and simulated payoffs, strict/touch and 5m/1m outcomes, stop-move hypotheses, posted-price discrepancies and level-rounding sensitivity. Blank payoff and mismatch fields mean the value could not be determined. The manifest `data/discord-audit/replay-summary.json` records exchange cutoff, comparison denominators, per-symbol source hashes, costs and random seed. Public candles and funding are cached under `data/discord-audit/market`. The per-signal file stays local to the supplied export.
