import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

def load_watchlist(path="watchlist.txt"):
    symbols = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            value = line.strip()
            if value and not value.startswith("#"):
                symbols.append(value)
    if not symbols:
        raise ValueError("watchlist.txt is empty.")
    return list(dict.fromkeys(symbols))

def _parse_timeframe_delta(tf: str):
    tf_l = "1mo" if tf == "1M" else tf.lower()
    if tf_l in ("1m", "3m", "5m", "15m", "30m"):
        return pd.Timedelta(minutes=int(tf_l.rstrip("m")))
    elif tf_l in ("60m", "1h"):
        return pd.Timedelta(hours=1)
    elif tf_l == "1d":
        return pd.Timedelta(days=1)
    elif tf_l in ("1w", "1wk"):
        return pd.Timedelta(weeks=1)
    elif tf_l in ("1mo", "1month"):
        return pd.Timedelta(days=30)
    return None

def fetch_candles(symbol, cfg, history_days=59):
    """Fetch NSE equity ticker from Yahoo Finance using yfinance.
    Supports intervals: 1m, 3m, 5m, 15m, 30m, 60m, 1h, 1d, 1w, 1mo (or 1M).
    """
    now = datetime.now(IST)
    tf = "1mo" if cfg.timeframe == "1M" else cfg.timeframe.lower()
    is_3m = (tf == "3m")

    if tf == "1m" or is_3m:
        interval = "1m"
        period = "7d"  # Yahoo Finance limits 1m to 7 days
    elif tf in ("5m", "15m", "30m"):
        interval = tf
        period = f"{min(history_days, 60)}d"
    elif tf in ("60m", "1h"):
        interval = "60m"
        period = "730d"
    elif tf in ("1w", "1wk"):
        interval = "1wk"
        period = "5y"
    elif tf in ("1mo", "1month"):
        interval = "1mo"
        period = "5y"
    else:
        interval = "1d"
        period = "2y"

    try:
        frame = yf.download(
            tickers=symbol,
            period=period,
            interval=interval,
            auto_adjust=False,
            prepost=False,
            progress=False,
            threads=False,
            timeout=20,
            multi_level_index=False,
        )
    except Exception as exc:
        log.warning("%s download failed: %s", symbol, exc)
        return pd.DataFrame()

    if frame is None or frame.empty:
        log.warning("%s returned no Yahoo Finance candles.", symbol)
        return pd.DataFrame()

    if isinstance(frame.columns, pd.MultiIndex):
        # Robustly flatten yfinance's optional multi-level response.
        frame.columns = [col[0] if isinstance(col, tuple) else col for col in frame.columns]

    frame = frame.rename(columns={c: str(c).lower().replace(" ", "_") for c in frame.columns})
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        log.warning("%s missing OHLCV columns: %s", symbol, list(frame.columns))
        return pd.DataFrame()

    idx = pd.to_datetime(frame.index, errors="coerce")
    frame = frame.copy()
    if idx.tz is None:
        frame.index = idx.tz_localize(IST)
    else:
        frame.index = idx.tz_convert(IST)
    frame.index.name = "time"
    frame = frame[~frame.index.isna()]
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()

    # If 3m requested, resample 1m candles into 3m OHLCV bars
    if is_3m:
        frame = frame.resample("3min").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["open", "high", "low", "close", "volume"])

    # For intraday intervals, filter out incomplete latest bar & out-of-session bars
    is_intraday = tf in ("1m", "3m", "5m", "15m", "30m", "60m", "1h")
    if is_intraday:
        delta = _parse_timeframe_delta(cfg.timeframe)
        if delta is not None:
            buf = getattr(cfg, 'close_buffer_seconds', 60)
            cutoff = pd.Timestamp.now(tz=IST) - pd.Timedelta(seconds=buf)
            frame = frame[frame.index + delta <= cutoff]
        # Apply typical NSE session filter for intraday data
        local = frame.index
        mins = local.hour * 60 + local.minute
        frame = frame[(local.dayofweek < 5) & (mins >= 9 * 60 + 15) & (mins < 15 * 60 + 30)]

    return frame[["open", "high", "low", "close", "volume"]]
