import pandas as pd

def calculate_ema(prices: list[float], period: int) -> float | None:
    if len(prices) < period:
        return None
    series = pd.Series(prices)
    ema = series.ewm(span=period, adjust=False).mean()
    return round(ema.iloc[-1], 4)


def calculate_rsi(prices: list[float], period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    df = pd.Series(prices)
    delta = df.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))

    return round(rsi.iloc[-1], 2)
