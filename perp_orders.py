"""Two-sided passive orders on linear USDT perpetuals. All P&L here is per coin."""
from bisect import bisect_left
from dataclasses import dataclass

from backtest import FEE, SLIP


ENTRY_BARS = 24      # two hours of five-minute bars
HOLD_BARS = 288      # 24 hours from a fill
HORIZON = ENTRY_BARS + HOLD_BARS - 1


@dataclass(frozen=True)
class Order:
    side: int
    entry: float
    stop: float
    target: float
    risk: float


@dataclass(frozen=True)
class Exit:
    fill: int | None
    end: int
    price: float | None
    reason: str
    funding: float


def trade_pnl(side, entry, exit_price, fee=FEE):
    return side * (exit_price - entry) - fee * (entry + exit_price)


def make_order(side, close, atr, low, high, wide=True):
    entry = close - side * 0.5 * atr
    if wide:
        swing = low if side == 1 else high
        distance = max(2 * atr, 0.015 * entry, side * (entry - swing) + 0.25 * atr)
    else:
        distance = max(atr, 0.005 * entry)
    stop = entry - side * distance
    stop_fill = stop * (1 - side * SLIP)
    risk = -trade_pnl(side, entry, stop_fill)
    target = ((side + FEE) * entry + 1.5 * risk) / (side - FEE)
    if min(stop, target, entry) <= 0 or risk <= 0:
        return None
    return Order(side, entry, stop, target, risk)


def funding_payments(market, side, fill, end):
    first = market.bars[fill].time * 1000
    last = (market.bars[end].time + 300) * 1000
    left = bisect_left(market.funding_times, first)
    right = bisect_left(market.funding_times, last)
    for f in market.funding[left:right]:
        j = fill + (f.ms - first) // 300_000
        cash = -side * f.rate * f.mark
        # Exchange order and settlement sequencing inside a five-minute bar is unknown.
        if j in (fill, end):
            cash = min(cash, 0)
        yield j, cash


def resolve(market, o, start):
    """start is the activation bar, five minutes after the feature cutoff."""
    bars = market.bars
    if start + HORIZON > len(bars):
        raise ValueError("Incomplete execution horizon")
    long = o.side == 1
    for fill in range(start, start + ENTRY_BARS):
        b = bars[fill]
        if (long and b.low < o.entry) or (not long and b.high > o.entry):
            break
    else:
        return Exit(None, start + ENTRY_BARS - 1, None, "expired", 0.0)
    for j in range(fill, fill + HOLD_BARS):
        b = bars[j]
        gap_target = b.open > o.target if long else b.open < o.target
        target = b.high > o.target if long else b.low < o.target
        stop = b.low <= o.stop if long else b.high >= o.stop
        if j > fill and gap_target:
            price, reason = o.target, "target"
            break
        if stop:
            price = min(b.open, o.stop) if long else max(b.open, o.stop)
            price, reason = price * (1 - o.side * SLIP), "stop"
            break
        if j > fill and target:
            price, reason = o.target, "target"
            break
    else:
        price, reason = b.close * (1 - o.side * SLIP), "timeout"
    carry = sum(cash for _, cash in funding_payments(market, o.side, fill, j))
    return Exit(fill, j, price, reason, carry)


def net_r(order, outcome):
    if outcome.fill is None:
        return 0.0
    pnl = trade_pnl(order.side, order.entry, outcome.price) + outcome.funding
    return pnl / order.risk
