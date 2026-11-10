"""Read-only live depth panel and five-minute model decisions. All timestamps are UTC."""
import argparse
from html import escape
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import time

from xgboost import XGBRegressor

from flow_data import FUTURES, persist, request_json, save_json
from flow_live import FORWARD, capture
from perp_market import Funding, Market, bars_from_rest
from paper_quotes import run as update_paper
from regime_data import rest_candles
from regime_filters import NAMES, live_book, observation, rolling_atr
from quote_replay import QUOTE_TTL_BARS
from train_quotes import MODELS, setup


def evaluate(coin, record, cutoff):
    bands = record["book"]["bands_bps"]
    panel = {k: round(100*v["imbalance"], 2) if v["imbalance"] is not None else None
             for k,v in bands.items()}
    output = dict(depth_imbalance_pct=panel, taker_buy_15m_pct=record["taker"]["15"]["buy_pct"],
                  observed_ms=record["book"]["observed_ms"], received_ms=record["received_ms"])
    if live_book(record, cutoff) is None:
        return dict(output, status="incomplete_or_stale_depth")
    symbol = coin+"USDT"
    rows = rest_candles(coin, cutoff-2200*300, cutoff)
    bars = bars_from_rest(rows)
    raw = request_json(FUTURES+"/fundingRate", dict(symbol=symbol, startTime=(cutoff-43200)*1000,
                                                    endTime=cutoff*1000-1))
    funding = [Funding(r["fundingTime"], float(r["fundingRate"]), float(r["markPrice"])) for r in raw]
    market = Market(bars, [], funding, [f.ms for f in funding], {}, {}, "")
    spot = request_json("https://api.kucoin.com/api/v1/market/candles",
                        dict(symbol=coin+"-USDT", type="5min", startAt=cutoff-300, endAt=cutoff-1))
    prices = {int(r[0]): float(r[2]) for r in spot["data"]}
    atr, baseline = rolling_atr(bars)
    i = len(bars)
    reading = observation(market, prices, atr, baseline, i, record)
    if reading is None or not all(math.isfinite(v) for v in reading.values):
        return dict(output, status="missing_features")
    model = XGBRegressor()
    model.load_model(MODELS/f"{coin}.json")
    score = float(model.predict([reading.values])[0])
    output.update(expected_r=score, features=dict(zip(NAMES, reading.values)))
    status = reading.block or ("nonpositive_ev" if score <= 0 else "qualifies")
    if status == "qualifies":
        order = setup(bars, i, atr)
        if order is None:
            status = "invalid_order"
        else:
            output.update(entry=order.entry, stop=order.stop, target=order.target, risk=order.risk)
    return dict(output, status=status)


def depth_heatmap(report):
    """Standalone signed depth heatmap. Missing bands get a separate neutral cell."""
    rows = []
    for coin, result in report["coins"].items():
        panel = result.get("depth_imbalance_pct", {})
        cells = []
        for band in ("5","10","20","100","200"):
            value = panel.get(band)
            if value is None:
                cells.append('<td class="missing">n/a</td>')
            else:
                rgb = "0,128,94" if value >= 0 else "205,85,25"
                cells.append(f'<td style="background:rgba({rgb},{.08+.8*abs(value)/100:.3f})">{value:+.1f}%</td>')
        rows.append("<tr><th>"+escape(coin)+"</th>"+"".join(cells)+"<td>"+escape(result["status"])+"</td></tr>")
    clock = datetime.fromtimestamp(report["cutoff"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>Live book depth</title>
<style>body{{font:16px system-ui;margin:3vw;color:#1d2627}}table{{border-collapse:collapse;font-variant-numeric:tabular-nums}}
td,th{{padding:.65em;text-align:right;border:1px solid #ccc}}.missing{{color:#686868;background:#eee}}</style>
<h1>Visible perpetual futures liquidity</h1><p>{clock}. Bid minus ask notional, divided by total displayed notional.
Green is bid-heavy and orange is ask-heavy. Grey means the full band was unavailable.</p>
<table><caption>Distance either side of the midprice in basis points</caption>
<thead><tr><th>Coin</th><th>5</th><th>10</th><th>20</th><th>100</th><th>200</th><th>Model decision</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></html>"""


def run(latest=False):
    if latest:
        batch = json.loads((FORWARD/"latest.json").read_bytes())
    else:
        # Sample in the last minute before a boundary, leaving time for all venues.
        time.sleep((240-int(time.time())%300) % 300)
        batch = capture()
    cutoff = (batch["captured_ms"]//300000+1)*300
    time.sleep(max(0, cutoff+2-time.time()))
    def score(item):
        coin, record = item
        try:
            result = evaluate(coin, record, cutoff)
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            result = dict(status="unavailable", error=str(error))
        result["scored_ms"] = time.time_ns()//1000000
        result["before_activation"] = result["scored_ms"] < (cutoff+300)*1000
        return coin, result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(score, batch["coins"].items()))
    report = dict(cutoff=cutoff, activation=cutoff+300, expiry=cutoff+(1+QUOTE_TTL_BARS)*300, coins=results)
    path = FORWARD/"quote-scores"/f"{cutoff}-{time.time_ns()}.json"
    save_json(path, report)
    persist(FORWARD/"depth-heatmap.html", depth_heatmap(report).encode())
    print(datetime.fromtimestamp(cutoff, timezone.utc).isoformat(), " | depth imbalance %, bid-positive")
    print("coin     5bp    10bp    20bp   100bp   200bp     expected R    decision")
    for coin,r in results.items():
        panel = r.get("depth_imbalance_pct", {})
        values = " ".join(f"{panel[k]:7.1f}" if panel.get(k) is not None else "      ." for k in ("5","10","20","100","200"))
        print(f"{coin:5} {values}    {r.get('expected_r',float('nan')):9.4f}    {r['status']}")
    print(path, FORWARD/"depth-heatmap.html")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", action="store_true", help="score the last recorded snapshot, including delayed audits")
    parser.add_argument("--count", type=int, default=1, help="number of five-minute boundaries to record")
    args = parser.parse_args()
    if args.count < 1 or (args.latest and args.count != 1):
        parser.error("use a positive count, or score one saved snapshot with --latest")
    for _ in range(args.count):
        run(args.latest)
        update_paper()
