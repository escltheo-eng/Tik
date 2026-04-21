"""Indicateurs techniques basiques implémentés en numpy/pandas.

Volontairement simples pour ne pas dépendre de TA-Lib.
"""

import numpy as np
import pandas as pd


def sma(prices: pd.Series, window: int) -> pd.Series:
    """Simple Moving Average."""
    return prices.rolling(window=window, min_periods=window).mean()


def ema(prices: pd.Series, window: int) -> pd.Series:
    """Exponential Moving Average."""
    return prices.ewm(span=window, adjust=False).mean()


def rsi(prices: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index (méthode Wilder)."""
    delta = prices.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    prices: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD, signal line, histogram."""
    macd_line = ema(prices, fast) - ema(prices, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(
    prices: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands (mid, upper, lower)."""
    mid = sma(prices, window)
    std = prices.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return mid, upper, lower


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
