"""Long-entry features at the close of each five-minute candle."""
from bisect import bisect_left
from dataclasses import dataclass
import numpy as np

NAMES = ["vwap_deviation_bps", "atr_expansion", "basis_bps", "relative_turnover",
         "bid_ask_ratio", "aggressive_buy_sell_ratio", "funding_4h_sum_bps",
         "funding_4h_events", "last_funding_bps", "atr_fraction"]


def rolling_atr(bars):
    """Compute 14 hourly true ranges on each five-minute phase. Benchmark against prior hours."""
    atr = np.full(len(bars)+1, np.nan)
    baseline = atr.copy()
    for phase in range(12):
        indices = list(range(13+phase, len(bars)+1, 12))
        tr = []
        for i in indices:
            group = bars[i-12:i]
            prev = bars[i-13].close
            tr.append(max(max(b.high for b in group), prev) - min(min(b.low for b in group), prev))
        if len(tr) >= 14:
            values = np.convolve(tr, np.ones(14)/14, mode="valid")
            atr[indices[13:]] = values
            if len(values) > 168:
                baseline[indices[181:]] = np.convolve(values[:-1], np.ones(168)/168, mode="valid")
    return atr, baseline


@dataclass(frozen=True)
class Reading:
    values: tuple
    volatility: str
    basis: str
    block: str | None


def classify(values):
    deviation, expansion, premium, turnover, book = values[:5]
    volatility = "expanded" if expansion > 1.5 else "ordinary"
    basis = "discount" if premium <= -10 else "premium" if premium >= 10 else "neutral"
    if volatility == "expanded":
        block = "atr_expansion"
    elif basis != "discount":
        block = basis
    elif turnover < 0.5 or book < 0.5:
        block = "thin_liquidity"
    elif deviation >= 0:
        block = "above_vwap"
    else:
        block = None
    return Reading(tuple(values), volatility, basis, block)


def live_book(record, cutoff):
    """Convert a complete flow_live.record_coin snapshot to the archived 1% band."""
    book = record["book"]
    observed = book["observed_ms"]/1000
    band = book["bands_bps"]["100"]
    if (not band["complete"] or not 0 < cutoff-observed <= 180
            or record["received_ms"] > cutoff*1000):
        return None
    return dict(observed=observed,bid_near=band["bid_usdt"],ask_near=band["ask_usdt"])


def observation(market, spot, atr, baseline, i, live_record=None):
    """i is the first unopened bar. Spot closes are keyed by their candle open timestamp."""
    if i < 294 or not np.isfinite(baseline[i]) or baseline[i] <= 0 or atr[i] <= 0:
        return None
    bars = market.bars
    b = bars[i-1]
    t = b.time + 300
    price = spot.get(b.time)
    book = market.depth.get(t) if live_record is None else live_book(live_record,t)
    if not price or not book or not 0 < t-book["observed"] <= 180:
        return None
    window = bars[i-6:i]
    quote = sum(x.quote for x in window)
    base = sum(x.volume for x in window)
    buy = sum(x.buy_quote for x in window)
    sell = quote-buy
    prior = sum(x.quote for x in bars[i-294:i-6])/48
    if min(base, quote, prior, sell, book["ask_near"]) <= 0:
        return None
    right = bisect_left(market.funding_times, t*1000)
    left = bisect_left(market.funding_times, (t-14400)*1000)
    if not right or t*1000-market.funding_times[right-1] > 9*3600_000:
        return None
    funding = market.funding[left:right]
    return classify([10000*(b.close/(quote/base)-1), atr[i]/baseline[i], 10000*(b.close/price-1),
                     quote/prior, book["bid_near"]/book["ask_near"], buy/sell,
                     10000*sum(f.rate for f in funding), len(funding),
                     10000*market.funding[right-1].rate, atr[i]/b.close])
