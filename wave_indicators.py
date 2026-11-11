"""Trailing five-minute close indicators for the Aahil Wave feature comparison."""
import numpy as np


def indicator_series(closes):
    """Element j uses closes through j. Pass completed, contiguous positive prices.

    RSI uses Wilder smoothing seeded by the first 14 changes. Bollinger bands
    use an unweighted 20-close mean and two population standard deviations.
    Warmup elements are NaN. Percent B and bandwidth are fractions.
    """
    prices = np.asarray(closes, dtype=float)
    if prices.ndim != 1 or not np.isfinite(prices).all() or np.any(prices <= 0):
        raise ValueError("Expected a one-dimensional series of positive finite closes")

    rsi = np.full(prices.size, np.nan)
    percent_b = np.full(prices.size, np.nan)
    bandwidth = np.full(prices.size, np.nan)

    if prices.size > 14:
        changes = np.diff(prices)
        gains = np.maximum(changes, 0)
        losses = np.maximum(-changes, 0)
        average_gain = gains[:14].mean()
        average_loss = losses[:14].mean()
        for j in range(14, prices.size):
            if j > 14:
                average_gain = (13 * average_gain + gains[j - 1]) / 14
                average_loss = (13 * average_loss + losses[j - 1]) / 14
            total = average_gain + average_loss
            rsi[j] = 100 * (average_gain / total) if total else 50

    if prices.size >= 20:
        windows = np.lib.stride_tricks.sliding_window_view(prices, 20)
        # Center relative to a close first so a constant decimal price yields
        # exactly zero width even when its 20-term floating-point sum rounds.
        relative = windows - windows[:, :1]
        center = relative.mean(axis=1)
        width = 4 * relative.std(axis=1, ddof=0)
        bandwidth[19:] = width / (windows[:, 0] + center)
        percent_b[19:] = 0.5 + np.divide(
            relative[:, -1] - center, width, out=np.zeros_like(width), where=width > 0
        )

    return {"rsi14": rsi, "bb_percent_b": percent_b, "bb_bandwidth": bandwidth}
