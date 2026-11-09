"""Hourly pullback orders with an attached stop and take-profit."""
from dataclasses import dataclass
from statistics import mean

from backtest import FEE, SLIP


@dataclass(frozen=True)
class Setup:
    limit: float
    stop: float
    target: float
    features: tuple


def setup(bars, i):
    """Called before candle i opens, after 24 completed hours."""
    history = bars[i - 24:i]
    close = history[-1].close
    tr = [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
          for a, b in zip(history, history[1:])]
    atr = mean(tr[-14:])
    if atr <= 0:
        return None
    limit = close - 0.5 * atr
    stop = limit - max(atr, limit * 0.005)
    if stop <= 0:
        return None
    cost = limit * (1 + FEE)
    risk = cost - stop * (1 - SLIP) * (1 - FEE)
    target = (cost + 1.5 * risk) / (1 - FEE)
    return Setup(limit, stop, target, (atr / close, (close - history[-7].close) / atr))


@dataclass(frozen=True)
class Outcome:
    end: int
    fill: int | None
    price: float | None
    reason: str


def resolve(order, bars, i):
    """Two-hour entry expiry and up to 24 hourly candles in a position."""
    for fill in range(i, i + 2):
        if bars[fill].low < order.limit:
            break
    else:
        return Outcome(i + 1, None, None, "expired")
    for j in range(fill, fill + 24):
        b = bars[j]
        if j > fill and b.open > order.target:
            return Outcome(j, fill, order.target, "target")
        if b.low <= order.stop:
            price = min(b.open, order.stop) * (1 - SLIP)
            return Outcome(j, fill, price, "stop")
        # A high earlier in the entry candle could precede the buy.
        if j > fill and b.high > order.target:
            return Outcome(j, fill, order.target, "target")
    return Outcome(j, fill, b.close * (1 - SLIP), "timeout")


def unit_pnl(order, result):
    return result.price * (1 - FEE) - order.limit * (1 + FEE)
