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


def median_abs_return_pct(close: pd.Series, n_bars: int) -> float | None:
    """Amplitude typique : médiane des |variations| sur `n_bars` barres, en %.

    Mesure de VOLATILITÉ réalisée (« de combien le prix bouge typiquement sur
    cette durée, à la hausse comme à la baisse »), PAS une prévision du sens.

    Pourquoi c'est honnête alors que Tik n'a aucun edge directionnel mesuré
    (go/no-go 2026-05-27) : le *signe* d'un rendement est ~imprévisible (proche
    d'une marche aléatoire), mais son *amplitude* est statistiquement
    persistante (volatility clustering). On peut donc estimer combien ça bouge
    sans prétendre savoir dans quel sens (cf. ADR-025).

    On prend la médiane (et non la moyenne) pour la robustesse aux outliers /
    queues épaisses des rendements crypto. Retourne None si pas assez de barres.

    Args:
        close: série des prix de clôture (chronologique).
        n_bars: nombre de barres correspondant à l'horizon (ex. swing 4h sur
            ~5 j = 30 barres ; flash 1m sur ~1 h = 60 barres).
    """
    if close is None or len(close) <= n_bars:
        return None
    changes = close.pct_change(n_bars).abs().dropna()
    if changes.empty:
        return None
    return round(float(changes.median()) * 100, 2)
