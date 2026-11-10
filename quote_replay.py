"""Replay one coin's timestamped limit signals against five-minute bars."""
from dataclasses import dataclass

from backtest import FEE, INITIAL
from perp_orders import Order, resolve, trade_pnl

QUOTE_TTL_BARS = 72  # six hours of five-minute bars, starting at activation

@dataclass(frozen=True)
class Proposal:
    decision: int  # index of the first bar after the feature window
    order: Order
    score: float
    ttl_bars: int | None = None  # recorded lifetime for replaying existing paper orders


def replay_quotes(market, proposals, ttl=QUOTE_TTL_BARS, replace=True, penetration_bps=0, legacy=False, allow_open=False):
    """A new quote can cancel only the unfilled entry for this coin.

    Process expiration, activation/cancel, then trading inside the bar. In legacy
    mode, reproduce the old rule blocking decisions until the order or exit ends.
    """
    if ttl < 1 or not 0 <= penetration_bps < 10000:
        raise ValueError("Invalid expiry or penetration")
    quotes = {p.decision + 1: p for p in proposals}
    if len(quotes) != len(proposals):
        raise ValueError("Duplicate decision for the same coin")
    rows = []
    if not quotes:
        return rows
    bars = market.bars
    cash, busy, pending = INITIAL, -1, None
    if any(p.ttl_bars is not None and p.ttl_bars < 1 for p in proposals):
        raise ValueError("Invalid recorded expiry")
    stop = max(active + (p.ttl_bars or ttl) for active, p in quotes.items()) + 1
    if allow_open:
        stop = min(stop, len(bars))
    for j in range(min(quotes), stop):
        if pending and j >= pending[1]:
            pending[2].update(status="expired", ended=bars[j].time)
            pending = None
        p = quotes.get(j)
        if p:
            o = p.order
            lifetime = p.ttl_bars or ttl
            row = dict(decision=bars[j-1].time, active=bars[j].time,
                       expires=bars[j].time + lifetime*300, side=o.side, score=p.score,
                       entry=o.entry, stop=o.stop, target=o.target, status="",
                       ended="", replaced_by="", fill="", exit_reason="", exit_price="",
                       qty=0., fees=0., funding=0., pnl=0.)
            rows.append(row)
            if (j-1 if legacy else j) <= busy:
                row.update(status="position_busy", ended=bars[j].time)
            elif pending and not replace:
                row.update(status="kept_first", ended=bars[j].time)
            else:
                if pending:
                    pending[2].update(status="replaced", ended=bars[j].time, replaced_by=row["decision"])
                pending = None
                if not legacy and o.side * (o.entry - bars[j].open) >= 0:
                    row.update(status="post_only_reject", ended=bars[j].time)
                else:
                    pending = (o, j + lifetime, row)
                    if legacy:
                        busy = j   # no new decision inside its one-bar entry window
        if not pending:
            continue
        o, _, row = pending
        extreme = bars[j].low if o.side == 1 else bars[j].high
        if o.side * (o.entry - extreme) <= o.entry * penetration_bps / 10000:
            continue
        x = resolve(market, o, j, entry_bars=1, allow_open=allow_open)
        qty = min(cash*0.005/o.risk, cash/(o.entry*(1+FEE)))
        if x.reason == "open":
            row.update(status="open", fill=bars[j].time, qty=qty)
            busy, pending = x.end, None
            continue
        pnl = qty * (trade_pnl(o.side, o.entry, x.price) + x.funding)
        row.update(status="filled", fill=bars[j].time, ended=bars[x.end].time+300,
                   exit_reason=x.reason, exit_price=x.price, qty=qty,
                   fees=qty*FEE*(o.entry+x.price), funding=qty*x.funding, pnl=pnl)
        busy, pending, cash = x.end, None, cash + pnl
    if pending:
        _, deadline, row = pending
        if stop >= deadline:
            row.update(status="expired", ended=row["expires"])
        else:
            row.update(status="working")
    return rows
