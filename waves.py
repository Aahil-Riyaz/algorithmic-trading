"""Confirm price swings using only completed closes."""


def wave_side(closes, atr):
    pivots = []
    for i in range(2, len(closes) - 2):
        price = closes[i]
        neighbors = closes[i-2:i] + closes[i+1:i+3]
        if price > max(neighbors):
            kind = 1
        elif price < min(neighbors):
            kind = -1
        else:
            continue
        if pivots and pivots[-1][0] == kind:
            if kind * (price - pivots[-1][1]) <= 0:
                continue
            pivots.pop()
        pivots.append((kind, price, i))
    if len(pivots) < 3:
        return 0
    a, b, c = pivots[-3:]
    side = b[0]
    impulse = side * (b[1] - a[1])
    if impulse <= 0 or impulse < 2 * atr or len(closes) - c[2] > 8:
        return 0
    retrace = side * (b[1] - c[1]) / impulse
    if 0.30 <= retrace <= 0.75 and side * c[1] < side * closes[-1] < side * b[1]:
        return side
    return 0
