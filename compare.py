"""Compare the breakout on six USDT spot markets using identical hourly windows."""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from backtest import simulate
from prices import Candle, load, validate


COINS = ("BTC", "ETH", "SOL", "HYPE", "AAVE", "XRP")
START = int(datetime(2025, 10, 1, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
DATA = Path("data/kucoin-2025-q4")


def check_period(rows):
    validate(rows)
    if len(rows) != (END - START) // 3600 or rows[0].time != START:
        raise ValueError("Incomplete hourly history for the comparison period")


def download(coin, path):
    bars = []
    for start in range(START, END, 1000 * 3600):
        end = min(start + 1000 * 3600, END)
        url = (f"https://api.kucoin.com/api/v1/market/candles?symbol={coin}-USDT"
               f"&type=1hour&startAt={start}&endAt={end - 1}")
        with urlopen(url, timeout=30) as response:
            payload = json.load(response)
        if payload["code"] != "200000":
            raise ValueError(f"{coin} download failed: {payload}")
        for stamp, opening, close, high, low, volume, _ in payload["data"]:
            bars.append(Candle(int(stamp), float(opening), float(high), float(low),
                               float(close), float(volume)))
    bars.sort()
    check_period(bars)
    temp = path.with_suffix(".tmp")
    with temp.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(Candle._fields)
        writer.writerows(bars)
    temp.replace(path)


def compare(refresh=False):
    DATA.mkdir(parents=True, exist_ok=True)
    all_trades = []
    for coin in COINS:
        path = DATA / f"{coin}.csv"
        if refresh or not path.exists():
            download(coin, path)
        bars = load(path)
        check_period(bars)
        cuts = [0, len(bars) * 6 // 10, len(bars) * 8 // 10, len(bars)]
        for period, start, end in zip(("development", "validation", "test"), cuts, cuts[1:]):
            metrics, trades = simulate(bars, start, end)
            date = datetime.fromtimestamp(bars[start].time, timezone.utc).isoformat()
            print(coin, period, date, json.dumps({k: round(v, 3) if isinstance(v, float) else v
                                                  for k, v in metrics.items()}))
            all_trades.extend(dict(coin=coin, period=period, **trade) for trade in trades)
    with open("coin-trades.csv", "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["coin", "period", "time", "entry", "quantity",
                                                  "stop", "target", "exit_bar", "exit", "reason", "pnl"])
        writer.writeheader()
        writer.writerows(all_trades)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="download each dataset again")
    compare(parser.parse_args().refresh)
