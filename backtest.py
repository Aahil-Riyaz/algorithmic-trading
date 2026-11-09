"""Replay one long-only breakout position at a time."""
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import mean

from prices import load


FEE = 0.001
SLIP = 0.0002
INITIAL = 10_000


@dataclass
class Position:
    time: int
    entry: float
    quantity: float
    stop: float
    target: float

    @property
    def cost(self):
        return self.quantity * self.entry * (1 + FEE)


def signal(bars, i):
    """At the open of i, only completed candles are visible."""
    if i < 21:
        return False
    return bars[i - 1].close > max(b.high for b in bars[i - 21:i - 1])


def open_position(bar, cash):
    entry = bar.open * (1 + SLIP)
    stop = entry * 0.99
    loss_per_coin = entry * (1 + FEE) - stop * (1 - SLIP) * (1 - FEE)
    quantity = min(cash * 0.005 / loss_per_coin, cash / (entry * (1 + FEE)))
    return Position(bar.time, entry, quantity, stop, entry * 1.02)


def exit_price(p, b, last):
    if b.open <= p.stop:
        return b.open, "gap stop"
    if b.open >= p.target:
        return p.target, "target"
    if b.low <= p.stop:
        return p.stop, "stop"
    if b.high >= p.target:
        return p.target, "target"
    if last:
        return b.close, "period end"
    return None, None


def simulate(bars, start, end):
    cash = peak = INITIAL
    drawdown = 0
    trades = []
    position = None
    for i in range(start, end):
        b = bars[i]
        if position is None and signal(bars, i):
            position = open_position(b, cash)
            cash -= position.cost
        equity = cash
        if position:
            price, reason = exit_price(position, b, i == end - 1)
            if price is None:
                equity += position.quantity * b.close * (1 - SLIP) * (1 - FEE)
            else:
                fill = price * (1 - SLIP)
                proceeds = position.quantity * fill * (1 - FEE)
                trades.append(dict(**asdict(position), exit_bar=b.time, exit=fill,
                                   reason=reason, pnl=proceeds - position.cost))
                cash += proceeds
                equity = cash
                position = None
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
    pnl = [t["pnl"] for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [-p for p in pnl if p < 0]
    hold = bars[end - 1].close * (1 - SLIP) * (1 - FEE) / (bars[start].open * (1 + SLIP) * (1 + FEE))
    return dict(trades=len(pnl), win_pct=100 * len(wins) / len(pnl) if pnl else None,
                avg_win_over_avg_loss=mean(wins) / mean(losses) if wins and losses else None,
                avg_pnl_usdt=mean(pnl) if pnl else None, return_pct=100 * (cash / INITIAL - 1),
                max_drawdown_pct=100 * drawdown, buy_hold_pct=100 * (hold - 1)), trades


if __name__ == "__main__":
    bars = load()
    if len(bars) < 100:
        raise SystemExit("Run python prices.py to download a full dataset.")
    cuts = [0, len(bars) * 6 // 10, len(bars) * 8 // 10, len(bars)]
    with open("trades.csv", "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["period", "time", "entry", "quantity", "stop",
                                                  "target", "exit_bar", "exit", "reason", "pnl"])
        writer.writeheader()
        for label, start, end in zip(("development", "validation", "test"), cuts, cuts[1:]):
            metrics, trades = simulate(bars, start, end)
            date = datetime.fromtimestamp(bars[start].time, timezone.utc).isoformat()
            print(label, date, json.dumps({k: round(v, 3) if isinstance(v, float) else v
                                           for k, v in metrics.items()}))
            writer.writerows(dict(period=label, **t) for t in trades)
