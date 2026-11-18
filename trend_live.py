"""Print today's target weight per coin from the latest closed daily candle. Read-only; never places orders."""
import json
import time

import numpy as np

from flow_data import fetch
from trend import COINS, scale, signal, targets

URL = "https://api.binance.com/api/v3/klines?symbol={}&interval=1d&limit=300"


def closed(sym):
    now = time.time() * 1000
    rows = [r for r in json.loads(fetch(URL.format(sym))) if r[6] < now]
    return np.array([float(r[4]) for r in rows]), rows[-1][0]


def main():
    for s in COINS:
        c, t = closed(s)
        print(f"{s} candle {time.strftime('%Y-%m-%d', time.gmtime(t / 1000))} close {c[-1]:.2f} signal {signal(c)[-1]:.2f} "
              f"scale {scale(c)[-1]:.2f} target weight {targets(c, 'trend')[-1]:.3f} "
              "(paper only; trade at next open if |target-held|>0.10)")


if __name__ == "__main__":
    main()
