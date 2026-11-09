"""Construct mirrored long/short observations using data observable by the order time."""
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from math import log1p
from statistics import mean

from perp_orders import HORIZON, Exit, Order, make_order, resolve


PRICE = ["side", "atr_fraction", "move_1h", "move_6h", "move_24h", "close_location",
         "volume_ratio", "stop_in_atr"]
FLOW = ["taker_1h", "taker_6h", "taker_24h", "depth_1pct", "depth_2pct", "funding_bps"]
OPTIONS = [f"{coin}_{name}" for coin in ("BTC", "ETH")
           for name in ("call_share_centered", "call_aggressor", "put_aggressor", "log_count")]
FEATURES = {"price": PRICE, "flow": PRICE + FLOW, "options_flow": PRICE + FLOW + OPTIONS}


def imbalance(buy, sell):
    return (buy - sell) / (buy + sell) if buy + sell > 0 else 0.0


def option_features(sample, side):
    cb, cs = sample["call_buy"], sample["call_sell"]
    pb, ps = sample["put_buy"], sample["put_sell"]
    return [side * imbalance(cb + cs, pb + ps), side * imbalance(cb, cs),
            -side * imbalance(pb, ps), log1p(sample["trades"])]


@dataclass
class Proposal:
    order: Order
    features: list
    outcome: Exit


@dataclass
class Decision:
    coin: str
    time: int
    start: int
    close: float
    atr: float
    low: float
    high: float
    proposals: list


def decisions(coin, market, first, last):
    """Return ordered decisions for [first,last), including only complete label horizons."""
    result = []
    coverage = Counter()
    for i, hour in enumerate(market.hours):
        t = hour.time
        if not first <= t < last:
            continue
        start = i * 12 + 1  # quote five minutes after the hour
        if t + 300 + HORIZON * 300 > last:
            coverage["purged_end"] += 1
            continue
        if i < 25:
            coverage["warmup"] += 1
            continue
        book = market.depth.get(t)
        if book is None or not t - 180 <= book["observed"] < t:
            coverage["missing_or_stale_book"] += 1
            continue
        options = market.options.get(t - t % 21600, {})
        if any(asset not in options for asset in ("BTC", "ETH")):
            coverage["missing_options"] += 1
            continue
        fund_i = bisect_left(market.funding_times, t * 1000) - 1
        if fund_i < 0 or t * 1000 - market.funding[fund_i].ms > 9 * 3600_000:
            coverage["missing_or_stale_funding"] += 1
            continue
        h = market.hours[i - 25:i]
        close = h[-1].close
        atr = mean(max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
                   for a, b in zip(h[-15:-1], h[-14:]))
        low, high = min(b.low for b in h[-12:]), max(b.high for b in h[-12:])
        if atr <= 0 or high <= low:
            coverage["flat_history"] += 1
            continue
        taker = []
        for length in (1, 6, 24):
            q = sum(b.quote for b in h[-length:])
            buy = sum(b.buy_quote for b in h[-length:])
            taker.append(imbalance(buy, max(q - buy, 0)))
        rate = market.funding[fund_i].rate
        flow = [*taker, imbalance(book["bid_near"], book["ask_near"]),
                imbalance(book["bid_wide"], book["ask_wide"]), rate * 10000]
        avg_vol = mean(b.quote for b in h[-25:-1])
        relative_volume = h[-1].quote / avg_vol if avg_vol else 0
        proposals = []
        for side in (1, -1):
            order = make_order(side, close, atr, low, high)
            if order is None:
                break
            moves = [side * (close - h[-n-1].close) / atr for n in (1, 6, 24)]
            features = [side, atr / close, *moves, side * (2 * (close - low) / (high - low) - 1),
                        relative_volume, abs(order.entry - order.stop) / atr]
            features.extend(side * x for x in flow)
            for currency in ("BTC", "ETH"):
                features.extend(option_features(options[currency], side))
            proposals.append(Proposal(order, features, resolve(market, order, start)))
        if len(proposals) == 2:
            result.append(Decision(coin, t, start, close, atr, low, high, proposals))
            coverage["eligible"] += 1
        else:
            coverage["invalid_geometry"] += 1
    return result, dict(coverage)
