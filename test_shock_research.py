import unittest
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np

from perp_market import Bar
from perp_orders import Order
from shock_research import (
    EMBARGO_SECONDS, MAX_LIFETIME_SECONDS, SCENARIOS, _risk_sized_trades,
    atr_regime, chronological_split, indicators, net_pnl, order_geometry,
    random_time_side_baseline,
)
from shock_signal import ceil_to_step, floor_to_step, fmt, live_model_gate, risk_card


def bars_from_closes(closes):
    rows = []
    start = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())
    for i, close in enumerate(closes):
        rows.append(Bar(start + i * 300, close, close * 1.001, close * .999,
                        close, 10., 1000., 550.))
    return rows


class ShockResearchTest(unittest.TestCase):
    def test_target_is_1_5_r_after_maker_fees(self):
        for side in (-1, 1):
            order = order_geometry(side, 100., 0.2, 98., 102.)
            self.assertIsNotNone(order)
            target = SimpleNamespace(fill=4, price=order.target, reason="target", funding=0.)
            pnl = net_pnl(order, target, "maker_maker_best_case")
            self.assertAlmostEqual(pnl / order.risk, 1.5, places=8)
            self.assertLess(net_pnl(order, target, "taker_taker"), pnl)
            stop = SimpleNamespace(fill=4, price=order.stop * (1 - side * 0.0002),
                                   reason="stop", funding=0.)
            self.assertAlmostEqual(net_pnl(order, stop, "maker_taker_stop") / order.risk,
                                   -1.0, places=8)

    def test_shock_and_partial_hour_atr_are_prefix_invariant(self):
        rng = np.random.default_rng(22)
        returns = rng.normal(0, 0.00015, 12 * 24 * 10)
        prices = 100 * np.exp(np.cumsum(returns))
        full_bars = bars_from_closes(prices)
        i = 9 * 24 * 12 + 7
        prefix_bars = full_bars[:i + 1]
        full = indicators(SimpleNamespace(bars=full_bars))
        prefix = indicators(SimpleNamespace(bars=prefix_bars))
        self.assertEqual(full["z_by_index"].get(i), prefix["z_by_index"].get(i))
        full_regime = atr_regime(SimpleNamespace(bars=full_bars), full, i)
        prefix_regime = atr_regime(SimpleNamespace(bars=prefix_bars), prefix, i)
        self.assertAlmostEqual(full_regime, prefix_regime, places=12)
        changed = list(full_bars)
        for j in range(i + 1, len(changed)):
            b = changed[j]
            changed[j] = Bar(b.time, b.open * 2, b.high * 2, b.low * 2,
                             b.close * 2, b.volume, b.quote, b.buy_quote)
        changed_arrays = indicators(SimpleNamespace(bars=changed))
        changed_regime = atr_regime(SimpleNamespace(bars=changed), changed_arrays, i)
        self.assertAlmostEqual(full_regime, changed_regime, places=12)

    def test_training_rows_are_purged_from_calibration_and_test(self):
        first = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
        rows = [dict(time=first - 500 * 86400 + i * 6 * 3600) for i in range(4000)]
        train, calibration = chronological_split(rows, datetime(2025, 1, 1).date())
        cal_start = min(r["time"] for r in calibration)
        self.assertLess(max(r["time"] for r in train) + MAX_LIFETIME_SECONDS + EMBARGO_SECONDS,
                        cal_start)
        self.assertLess(max(r["time"] for r in calibration) + MAX_LIFETIME_SECONDS + EMBARGO_SECONDS,
                        first)

    def test_risk_sizing_respects_coin_sleeve_and_daily_halt(self):
        base = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
        order = Order(1, 100., 99., 101., 1.)
        rows = []
        for i in range(20):
            coin = ("BTC", "ETH", "SOL", "AVAX")[i % 4]
            rows.append(dict(coin=coin, time=base + i * 2 * 3600,
                             end=base + i * 2 * 3600 + 3600, order=order,
                             fill=True, r=-40., reason="stop",
                             pnl_scenarios={s: -40. for s in SCENARIOS}))
        result = _risk_sized_trades(rows, lambda _: True)
        self.assertGreater(result["skips"]["daily_halt"], 0)
        self.assertLess(result["cash"], result["initial"])
        self.assertGreater(result["max_drawdown"], 0)
        self.assertLessEqual(max(t["quantity"] * t["order"].entry for t in result["tickets"]),
                             2500.)

    def test_live_card_rounds_prices_and_never_ignores_failed_evidence(self):
        self.assertEqual(floor_to_step(1.239, .01), 1.23)
        self.assertEqual(ceil_to_step(1.231, .01), 1.24)
        self.assertEqual(fmt(76930., .1), "76,930.0")
        order = order_geometry(1, 100., .2, 98., 102.)
        setup = dict(order=order, side=1, coin="BTC", time=1_750_000_000,
                     event_time=1_749_999_100, current_close=100., atr_regime=1.1,
                     values=dict(shock_z=3.4))
        score = dict(p_fill=.8, p_tp_given_fill=.55, expected_net_r=.1)
        filters = dict(tick=.1, step=.001, min_qty=.001, min_notional=5.)
        evidence = dict(actionable=False, historical_fills=74,
                        historical_net_r_per_fill=-.12, historical_ci_low=-.38,
                        enough_oos_fills=False, prospective_paper_weeks=0,
                        paper_weeks_required=8)
        card = risk_card(setup, score, 10000., filters, evidence)
        self.assertEqual(card["decision"], "WAIT")
        self.assertLessEqual(card["actual_stop_risk_usdt"], card["planned_risk_usdt"] + 1e-8)
        self.assertIn("historical net edge", " ".join(card["blockers"]))

    def test_live_gate_requires_positive_oos_lower_bound_and_sample(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "results.json"
            path.write_text(json.dumps({"pooled_oos": {"model": {"maker_taker_stop": {
                "fills": 74, "mean_net_r": -0.12,
                "bootstrap": {"net_r_per_fill_95": [-0.38, 0.18]},
            }}}}))
            self.assertFalse(live_model_gate(path)["actionable"])

    def test_random_control_is_seeded_and_matches_model_order_count(self):
        order = Order(1, 100., 99., 101., 1.)
        short = Order(-1, 100., 101., 99., 1.)
        row = dict(fold="2025-Q1", coin="BTC", time=1_750_000_000,
                   end=1_750_003_600, order=order, fill=True, reason="stop", r=-1.,
                   pnl_scenarios={s: -1. for s in SCENARIOS}, model_trade=True,
                   continuation_order=short, continuation_fill=False,
                   continuation_reason="expired", continuation_end=1_750_025_200,
                   continuation_r=0., continuation_pnl_scenarios={s: 0. for s in SCENARIOS})
        rows = [row, dict(row, time=row["time"] + 36 * 3600, model_trade=False)]
        a = random_time_side_baseline(rows, reps=5, seed=12)
        b = random_time_side_baseline(rows, reps=5, seed=12)
        self.assertEqual(a, b)
        self.assertEqual(a["matched_submitted_orders"], 1)


if __name__ == "__main__":
    unittest.main()
