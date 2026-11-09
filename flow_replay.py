"""Replay competing orders and account for realized and open-position equity."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import mean

from backtest import FEE, INITIAL, SLIP
from compare import COINS
from flow_features import Decision, Proposal
from perp_orders import funding_payments, make_order, resolve, trade_pnl


@dataclass
class Ticket:
    decision: Decision
    proposal: Proposal
    score: float
    quantity: float
    pnl: float


def replay(rows, scores, cutoff):
    cash = dict.fromkeys(COINS, INITIAL)
    free_at = dict.fromkeys(COINS, 0)
    ledger = []
    for d, pair in zip(rows, scores, strict=True):
        if d.start < free_at[d.coin] or max(pair) < cutoff:
            continue
        if pair[0] == pair[1]:
            continue
        pick = 0 if pair[0] > pair[1] else 1
        proposal = d.proposals[pick]
        o, x = proposal.order, proposal.outcome
        free_at[d.coin] = x.end + 1
        quantity = min(cash[d.coin] * 0.005 / o.risk, cash[d.coin] / (o.entry * (1 + FEE)))
        pnl = 0.0
        if x.fill is not None:
            pnl = quantity * (trade_pnl(o.side, o.entry, x.price) + x.funding)
            cash[d.coin] += pnl
        ledger.append(Ticket(d, proposal, float(pair[pick]), quantity, pnl))
    return ledger


def summary(ledger):
    fills = [t for t in ledger if t.proposal.outcome.fill is not None]
    pnl = [t.pnl for t in fills]
    wins = [v for v in pnl if v > 0]
    losses = [-v for v in pnl if v < 0]
    return dict(orders=len(ledger), fills=len(fills), wins=len(wins),
                fill_pct=100 * len(fills) / len(ledger) if ledger else None,
                win_pct=100 * len(wins) / len(fills) if fills else None,
                net_usdt=sum(pnl), avg_win_loss=mean(wins) / mean(losses) if wins and losses else None,
                expectancy_r=mean(t.pnl / (t.quantity * t.proposal.order.risk) for t in fills) if fills else None,
                profit_factor=sum(wins) / sum(losses) if losses else None,
                funding_usdt=sum(t.quantity * t.proposal.outcome.funding for t in fills),
                exits=dict(Counter(t.proposal.outcome.reason for t in fills)))


def max_drawdown(ledger, markets):
    # Deltas at the same UTC close are combined before computing portfolio equity.
    delta = defaultdict(float)
    for t in ledger:
        o, x = t.proposal.order, t.proposal.outcome
        if x.fill is None:
            continue
        m = markets[t.decision.coin]
        carry = prior = 0.0
        funding = dict(funding_payments(m, o.side, x.fill, x.end))
        for j in range(x.fill, x.end + 1):
            carry += funding.get(j, 0.0)
            bar = m.bars[j]
            marked_exit = bar.close * (1 - o.side * SLIP)
            marked = t.quantity * (trade_pnl(o.side, o.entry, marked_exit) + carry)
            value = t.pnl if j == x.end else marked
            delta[bar.time] += value - prior
            prior = value
    equity = peak = len(COINS) * INITIAL
    worst = 0.0
    for _, change in sorted(delta.items()):
        equity += change
        peak = max(equity, peak)
        worst = max(worst, 1 - equity / peak)
    if abs(equity - len(COINS) * INITIAL - sum(t.pnl for t in ledger)) > 1e-5:
        raise ValueError("Portfolio equity and ledger do not reconcile")
    return 100 * worst


def stress_pnl(ledger):
    """Reprice the same fills at double fees and double market slippage."""
    total = 0.0
    for t in ledger:
        o, x = t.proposal.order, t.proposal.outcome
        if x.fill is None:
            continue
        price = x.price
        if x.reason != "target":
            price *= (1 - o.side * 2 * SLIP) / (1 - o.side * SLIP)
        total += t.quantity * (trade_pnl(o.side, o.entry, price, fee=2 * FEE) + x.funding)
    return total


def stop_diagnostic(ledger, markets):
    comparison = {}
    for name, wide in (("wide", True), ("previous_width", False)):
        fills = stops = observed = recovered = 0
        distances = []
        for t in ledger:
            d, p = t.decision, t.proposal
            if p.outcome.fill is None:
                continue
            m = markets[d.coin]
            order = make_order(p.order.side, d.close, d.atr, d.low, d.high, wide=wide)
            outcome = p.outcome if wide else resolve(m, order, d.start)
            if outcome.fill != p.outcome.fill:
                raise ValueError("Stop comparison changed entry")
            fills += 1
            distances.append(100 * abs(order.entry - order.stop) / order.entry)
            if outcome.reason == "stop":
                stops += 1
                future = m.bars[outcome.end + 1:outcome.end + 145]
                if len(future) == 144:
                    observed += 1
                    recovered += (any(b.high >= order.entry for b in future) if order.side == 1
                                  else any(b.low <= order.entry for b in future))
        comparison[name] = dict(fills=fills, stops=stops, observed_12h=observed,
                                back_to_entry_12h=recovered,
                                avg_stop_distance_pct=mean(distances) if distances else None)
    return comparison
