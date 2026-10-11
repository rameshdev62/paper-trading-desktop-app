import numpy as np
import pandas as pd

def is_doji(bar: pd.Series, threshold_ratio: float = 0.1, threshold_pct: float = 0.001) -> bool:
    """Check if a candle is a Doji or has negligible body."""
    rng = float(bar["high"]) - float(bar["low"])
    body = abs(float(bar["close"]) - float(bar["open"]))
    if rng <= 0 or float(bar["close"]) <= 0:
        return True
    return (body / rng < threshold_ratio) or (body / float(bar["close"]) < threshold_pct)


def compute_true_range_and_atr(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series]:
    """Compute True Range (TR) and Average True Range (ATR)."""
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return tr, atr


def compute_ema_cross_trend(
    df: pd.DataFrame,
    fast_period: int = 20,
    slow_period: int = 50,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Compute 20 EMA and 50 EMA, cross events, and trend direction.

    Returns:
    - ema_fast: Fast Exponential Moving Average (default 20 periods)
    - ema_slow: Slow Exponential Moving Average (default 50 periods)
    - is_bullish: True when fast EMA > slow EMA (Golden state / Uptrend)
    - golden_cross: True on bar where fast EMA crosses strictly above slow EMA
    - death_cross: True on bar where fast EMA crosses strictly below slow EMA
    """
    close = df["close"]
    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=slow_period, adjust=False).mean()

    is_bullish = ema_fast > ema_slow
    prev_fast = ema_fast.shift(1)
    prev_slow = ema_slow.shift(1)

    golden_cross = (ema_fast > ema_slow) & (prev_fast <= prev_slow)
    death_cross = (ema_fast < ema_slow) & (prev_fast >= prev_slow)

    return ema_fast, ema_slow, is_bullish, golden_cross, death_cross


def add_rlh_signals(
    df: pd.DataFrame,
    timeframe: str = "1d",
    allow_short: bool = True,
    cooldown_days: int = 7,
    proximity_pct: float = 2.0,
    prefer_l_color: bool = False,
    use_atr_filter: bool = True,
    atr_period: int = 14,
    use_ema_filter: bool = False,
    ema_fast_period: int = 20,
    ema_slow_period: int = 50,
) -> pd.DataFrame:
    """Generate BUY and SHORT signals based on the R-L-H Candlestick Pattern.

    Candle Progression:
    - R: Reference candle (t-2)
    - L: Contraction candle (t-1)
    - H: Expansion candle (t)

    Rules:
    1. Range(L) < Range(R) < Range(H)
    2. Body(H) > Body(R)
    3. LONG: H is Green, Body(H) entirely above Body(L). SL = L Low.
       L preferably Red, but Green acceptable.
    4. SHORT: H is Red, Body(H) entirely below Body(L). SL = L High.
       L preferably Green, but Red acceptable.
    5. Volatility ATR Rules (if use_atr_filter=True):
       - The R candle's TR must be greater than the ATR. (TR(R) > ATR)
       - The L candle's TR must not be greater than the ATR. (TR(L) <= ATR)
       - The H candle's TR must be greater than the ATR. (TR(H) > ATR)
    6. Trend Confluence Filter (if use_ema_filter=True):
       - LONG only when 20 EMA > 50 EMA (Bullish Trend / Golden State).
       - SHORT only when 20 EMA < 50 EMA (Bearish Trend / Death State).
    7. Reappearance Rule (Rule 7): On 4h, 1d, 1w timeframes, if a pattern appears
       at the same location within 7 days, flag as 7d reappearance.
    """
    out = df.copy()
    if len(out) < 3:
        out["signal"] = "WAIT"
        out["rlh_pattern"] = None
        out["rlh_stop"] = np.nan
        out["rlh_7d_reappearance"] = False
        return out

    out["range"] = out["high"] - out["low"]
    out["body"] = (out["close"] - out["open"]).abs()
    out["is_green"] = out["close"] > out["open"]
    out["is_red"] = out["close"] < out["open"]
    out["body_top"] = out[["open", "close"]].max(axis=1)
    out["body_bottom"] = out[["open", "close"]].min(axis=1)

    # Compute TR and ATR
    tr, atr = compute_true_range_and_atr(out, period=atr_period)
    out["tr"] = tr
    out["atr"] = atr

    # Compute 20 EMA and 50 EMA Trend & Cross Detection
    ema_fast, ema_slow, is_bullish, golden_cross, death_cross = compute_ema_cross_trend(
        out, fast_period=ema_fast_period, slow_period=ema_slow_period
    )
    out["ema_20"] = ema_fast
    out["ema_50"] = ema_slow
    out["ema_bullish"] = is_bullish
    out["ema_golden_cross"] = golden_cross
    out["ema_death_cross"] = death_cross
    out["ema_trend"] = np.where(is_bullish, "BULLISH", "BEARISH")

    # Shifted series: R is t-2, L is t-1, H is t
    r_range = out["range"].shift(2)
    l_range = out["range"].shift(1)
    h_range = out["range"]

    r_body = out["body"].shift(2)
    h_body = out["body"]

    l_open = out["open"].shift(1)
    l_close = out["close"].shift(1)
    l_low = out["low"].shift(1)
    l_high = out["high"].shift(1)
    l_body_top = out["body_top"].shift(1)
    l_body_bottom = out["body_bottom"].shift(1)

    h_open = out["open"]
    h_close = out["close"]
    h_body_top = out["body_top"]
    h_body_bottom = out["body_bottom"]

    # Rule 1 & 2: Range(L) < Range(R) < Range(H)
    size_cond = (l_range < r_range) & (r_range < h_range)

    # Rule 6: Body(H) > Body(R)
    body_size_cond = h_body > r_body

    # ATR Filter (User Rules):
    # - The R candle's TR must be greater than the ATR.
    # - The L candle's TR must not be greater than the ATR.
    # - The H candle's TR must be greater than the ATR.
    if use_atr_filter:
        r_tr = tr.shift(2)
        l_tr = tr.shift(1)
        h_tr = tr
        r_atr = atr.shift(2)
        l_atr = atr.shift(1)
        h_atr = atr
        atr_cond = (r_tr > r_atr) & (l_tr <= l_atr) & (h_tr > h_atr)
    else:
        atr_cond = pd.Series(True, index=out.index)

    # Rule 3: L color preferences
    l_is_red = l_close < l_open
    l_is_green = l_close > l_open

    # Rule 5: Body relative positioning
    # LONG: H green, Body(H) entirely above Body(L)
    long_pos_cond = h_body_bottom > l_body_top
    long_valid = (
        size_cond
        & body_size_cond
        & (h_close > h_open)
        & long_pos_cond
        & atr_cond
    )
    if prefer_l_color:
        long_valid = long_valid & l_is_red

    # SHORT: H red, Body(H) entirely below Body(L)
    short_pos_cond = h_body_top < l_body_bottom
    short_valid = (
        size_cond
        & body_size_cond
        & (h_close < h_open)
        & short_pos_cond
        & atr_cond
    )
    if prefer_l_color:
        short_valid = short_valid & l_is_green

    # 20 EMA & 50 EMA Trend Confluence:
    # Bullish Trend (20 EMA > 50 EMA) for LONG; Bearish Trend (20 EMA < 50 EMA) for SHORT
    if use_ema_filter:
        long_valid = long_valid & is_bullish
        short_valid = short_valid & (~is_bullish)

    out["signal"] = "WAIT"
    out["rlh_pattern"] = None
    out["rlh_stop"] = np.nan
    out["rlh_7d_reappearance"] = False

    # Apply 7-day reappearance rule chronologically
    tf_lower = timeframe.lower()
    applies_7d_rule = tf_lower in ("4h", "1d", "1w", "1wk")

    last_long_time = None
    last_long_level = None
    last_short_time = None
    last_short_level = None

    for i in range(2, len(out)):
        curr_time = out.index[i]

        if long_valid.iloc[i]:
            sl = float(l_low.iloc[i])
            is_reappearance = False
            if applies_7d_rule and last_long_time is not None:
                days = (curr_time - last_long_time).total_seconds() / 86400.0
                if days < cooldown_days:
                    diff_pct = abs(sl - last_long_level) / last_long_level * 100.0 if last_long_level > 0 else 0
                    if diff_pct <= proximity_pct:
                        is_reappearance = True

            out.iat[i, out.columns.get_loc("rlh_pattern")] = "LONG"
            out.iat[i, out.columns.get_loc("rlh_stop")] = sl

            if is_reappearance:
                out.iat[i, out.columns.get_loc("rlh_7d_reappearance")] = True
                out.iat[i, out.columns.get_loc("signal")] = "REAPPEARANCE_STOP"
            else:
                out.iat[i, out.columns.get_loc("signal")] = "BUY"
                last_long_time = curr_time
                last_long_level = sl

        elif short_valid.iloc[i] and allow_short:
            sl = float(l_high.iloc[i])
            is_reappearance = False
            if applies_7d_rule and last_short_time is not None:
                days = (curr_time - last_short_time).total_seconds() / 86400.0
                if days < cooldown_days:
                    diff_pct = abs(sl - last_short_level) / last_short_level * 100.0 if last_short_level > 0 else 0
                    if diff_pct <= proximity_pct:
                        is_reappearance = True

            out.iat[i, out.columns.get_loc("rlh_pattern")] = "SHORT"
            out.iat[i, out.columns.get_loc("rlh_stop")] = sl

            if is_reappearance:
                out.iat[i, out.columns.get_loc("rlh_7d_reappearance")] = True
                out.iat[i, out.columns.get_loc("signal")] = "REAPPEARANCE_STOP"
            else:
                out.iat[i, out.columns.get_loc("signal")] = "SHORT"
                last_short_time = curr_time
                last_short_level = sl

    return out


def add_signals(df: pd.DataFrame, breakout_lookback: int = 12, volume_lookback: int = 20, volume_multiplier: float = 1.2) -> pd.DataFrame:
    """Generate BUY/BEARISH_EXIT signals for a long-only breakout strategy."""
    out = df.copy()
    if out.empty:
        out["signal"] = pd.Series(dtype=str)
        return out

    # Compute 20/50 EMA trend for charting and indicators
    ema_fast, ema_slow, is_bullish, golden_cross, death_cross = compute_ema_cross_trend(out)
    out["ema_20"] = ema_fast
    out["ema_50"] = ema_slow
    out["ema_bullish"] = is_bullish
    out["ema_golden_cross"] = golden_cross
    out["ema_death_cross"] = death_cross
    out["ema_trend"] = np.where(is_bullish, "BULLISH", "BEARISH")

    out["prior_high"] = out["high"].shift(1).rolling(breakout_lookback).max()
    out["prior_low"] = out["low"].shift(1).rolling(breakout_lookback).min()
    out["prior_volume_avg"] = out["volume"].shift(1).rolling(volume_lookback).mean()
    candle_range = (out["high"] - out["low"]).where((out["high"] - out["low"]) > 0)
    close_location = (out["close"] - out["low"]) / candle_range

    volume_ok = out["volume"] >= out["prior_volume_avg"] * volume_multiplier
    bullish = (
        (out["close"] > out["prior_high"]) &
        volume_ok &
        (close_location >= 0.70)
    )
    bearish = (
        (out["close"] < out["prior_low"]) &
        volume_ok &
        (close_location <= 0.30)
    )
    out["signal"] = "WAIT"
    out.loc[bullish.fillna(False), "signal"] = "BUY"
    out.loc[bearish.fillna(False), "signal"] = "BEARISH_EXIT"
    return out


def add_ema_cross_signals(
    df: pd.DataFrame,
    fast_period: int = 20,
    slow_period: int = 50,
    allow_short: bool = True,
) -> pd.DataFrame:
    """Generate BUY (Golden Cross) and SHORT (Death Cross) signals using 20 EMA and 50 EMA.

    - Golden Cross: 20 EMA crosses strictly above 50 EMA -> BUY / LONG
    - Death Cross: 20 EMA crosses strictly below 50 EMA -> SHORT
    - Trend State: 'BULLISH' when 20 EMA > 50 EMA; 'BEARISH' when 20 EMA < 50 EMA
    """
    out = df.copy()
    if len(out) < 2:
        out["signal"] = "WAIT"
        out["rlh_pattern"] = None
        out["rlh_stop"] = np.nan
        out["rlh_7d_reappearance"] = False
        return out

    ema_fast, ema_slow, is_bullish, golden_cross, death_cross = compute_ema_cross_trend(
        out, fast_period=fast_period, slow_period=slow_period
    )
    out["ema_20"] = ema_fast
    out["ema_50"] = ema_slow
    out["ema_bullish"] = is_bullish
    out["ema_golden_cross"] = golden_cross
    out["ema_death_cross"] = death_cross
    out["ema_trend"] = np.where(is_bullish, "BULLISH", "BEARISH")

    out["signal"] = "WAIT"
    out["rlh_pattern"] = None
    out["rlh_stop"] = np.nan
    out["rlh_7d_reappearance"] = False

    # Stop Loss placed at slow EMA (50 EMA) level
    out.loc[golden_cross.fillna(False), "signal"] = "BUY"
    out.loc[golden_cross.fillna(False), "rlh_pattern"] = "LONG"
    out.loc[golden_cross.fillna(False), "rlh_stop"] = ema_slow[golden_cross.fillna(False)]

    if allow_short:
        out.loc[death_cross.fillna(False), "signal"] = "SHORT"
        out.loc[death_cross.fillna(False), "rlh_pattern"] = "SHORT"
        out.loc[death_cross.fillna(False), "rlh_stop"] = ema_slow[death_cross.fillna(False)]

    return out


def generate_signals(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """Unified signal generator routing between selectable strategies.

    Strategies supported:
    - 'rlh_atr': R-L-H Pattern with ATR Filter
    - 'rlh_ema': R-L-H Pattern with ATR Filter AND 20/50 EMA Trend Confluence
    - 'ema_cross': 20/50 EMA Golden/Death Cross Trend Strategy
    - 'rlh_classic': Classic R-L-H Pattern based on candle sizes
    - 'breakout': 20-Bar Volume Breakout
    - 'combined': Multi-strategy R-L-H ATR + 20/50 EMA Cross + Volume Breakout
    - 'rlh_support_zone': R-L-H Support Zone — 3-touch breakdown SHORT signal
    """
    strat = getattr(cfg, "strategy_type", "rlh_atr").lower()
    fast_ema = getattr(cfg, "ema_fast_period", 20)
    slow_ema = getattr(cfg, "ema_slow_period", 50)
    use_ema_filter = getattr(cfg, "use_ema_trend_filter", False) or ("ema" in strat and "cross" not in strat)

    if "ema_cross" in strat or strat == "ema_cross" or "cross" in strat:
        return add_ema_cross_signals(
            df,
            fast_period=fast_ema,
            slow_period=slow_ema,
            allow_short=getattr(cfg, "allow_short", True),
        )
    elif "support_zone" in strat or "sz" in strat:
        return add_rlh_support_zone_signals(
            df,
            timeframe=getattr(cfg, "timeframe", "1d"),
            allow_short=getattr(cfg, "allow_short", True),
            cooldown_days=getattr(cfg, "rlh_cooldown_days", 7),
            proximity_pct=getattr(cfg, "rlh_proximity_pct", 2.0),
            atr_period=getattr(cfg, "atr_period", 14),
            ema_fast_period=fast_ema,
            ema_slow_period=slow_ema,
            breakdown_touches=3,
        )
    elif "classic" in strat or strat == "rlh_classic":
        return add_rlh_signals(
            df,
            timeframe=getattr(cfg, "timeframe", "1d"),
            allow_short=getattr(cfg, "allow_short", True),
            cooldown_days=getattr(cfg, "rlh_cooldown_days", 7),
            proximity_pct=getattr(cfg, "rlh_proximity_pct", 2.0),
            prefer_l_color=getattr(cfg, "rlh_prefer_l_color", False),
            use_atr_filter=False,
            atr_period=getattr(cfg, "atr_period", 14),
            use_ema_filter=use_ema_filter,
            ema_fast_period=fast_ema,
            ema_slow_period=slow_ema,
        )
    elif "rlh" in strat or "atr" in strat:
        return add_rlh_signals(
            df,
            timeframe=getattr(cfg, "timeframe", "1d"),
            allow_short=getattr(cfg, "allow_short", True),
            cooldown_days=getattr(cfg, "rlh_cooldown_days", 7),
            proximity_pct=getattr(cfg, "rlh_proximity_pct", 2.0),
            prefer_l_color=getattr(cfg, "rlh_prefer_l_color", False),
            use_atr_filter=True,
            atr_period=getattr(cfg, "atr_period", 14),
            use_ema_filter=use_ema_filter or ("ema" in strat),
            ema_fast_period=fast_ema,
            ema_slow_period=slow_ema,
        )
    elif "combined" in strat or "multi" in strat:
        s_rlh = add_rlh_signals(
            df,
            timeframe=getattr(cfg, "timeframe", "1d"),
            allow_short=getattr(cfg, "allow_short", True),
            cooldown_days=getattr(cfg, "rlh_cooldown_days", 7),
            proximity_pct=getattr(cfg, "rlh_proximity_pct", 2.0),
            prefer_l_color=getattr(cfg, "rlh_prefer_l_color", False),
            use_atr_filter=True,
            atr_period=getattr(cfg, "atr_period", 14),
            use_ema_filter=use_ema_filter,
            ema_fast_period=fast_ema,
            ema_slow_period=slow_ema,
        )
        s_bk = add_signals(
            df,
            breakout_lookback=getattr(cfg, "lookback_breakout", 12),
            volume_lookback=getattr(cfg, "lookback_volume", 20),
            volume_multiplier=getattr(cfg, "volume_multiplier", 1.2),
        )
        out = s_rlh.copy()
        bk_buys = (out["signal"] == "WAIT") & (s_bk["signal"] == "BUY")
        out.loc[bk_buys, "signal"] = "BUY"
        return out
    else:
        return add_signals(
            df,
            breakout_lookback=getattr(cfg, "lookback_breakout", 12),
            volume_lookback=getattr(cfg, "lookback_volume", 20),
            volume_multiplier=getattr(cfg, "volume_multiplier", 1.2),
        )


def add_rlh_support_zone_signals(
    df: pd.DataFrame,
    timeframe: str = "1d",
    allow_short: bool = True,
    cooldown_days: int = 7,
    proximity_pct: float = 2.0,
    atr_period: int = 14,
    ema_fast_period: int = 20,
    ema_slow_period: int = 50,
    breakdown_touches: int = 3,
) -> pd.DataFrame:
    """RLH Support Zone Strategy.

    After each RLH LONG pattern fires and price rallies:
    - The L candle's LOW (wick) and OPEN (body start) define a support zone.
    - Each time price retests (touches) that zone and bounces up, the touch count increments.
    - When price touches the zone for the N-th time (default: 3) and closes BELOW
      the zone lower bound (L wick low), a SHORT/breakdown signal fires.

    Columns added to output DataFrame:
        rlh_sz_lower        float  Active support zone lower bound (L candle low)
        rlh_sz_upper        float  Active support zone upper bound (L candle open)
        rlh_sz_touch_count  int    Cumulative touch count on the active zone
        rlh_sz_breakdown    bool   True on the bar where breakdown SHORT fires
    """
    # Step 1: Get standard RLH LONG entries (no short from RLH itself here)
    out = add_rlh_signals(
        df,
        timeframe=timeframe,
        allow_short=False,
        cooldown_days=cooldown_days,
        proximity_pct=proximity_pct,
        prefer_l_color=False,
        use_atr_filter=True,
        atr_period=atr_period,
        use_ema_filter=False,
        ema_fast_period=ema_fast_period,
        ema_slow_period=ema_slow_period,
    )

    # Initialise zone tracking columns
    out["rlh_sz_lower"] = np.nan
    out["rlh_sz_upper"] = np.nan
    out["rlh_sz_touch_count"] = 0
    out["rlh_sz_breakdown"] = False

    # Active zone state variables
    sz_lower = None       # L candle low  (wick bottom)  → zone lower bound
    sz_upper = None       # L candle open (body start)   → zone upper bound
    sz_touches = 0        # number of times price has re-tested the zone
    in_long = False       # True while holding the initial RLH LONG trade
    long_entry_i = -1     # bar index of most recent LONG entry

    for i in range(len(out)):
        bar = out.iloc[i]
        bar_low   = float(bar["low"])
        bar_high  = float(bar["high"])
        bar_close = float(bar["close"])
        bar_open  = float(bar["open"])

        # --- A. New BUY signal: capture L candle support zone ---
        if bar.get("signal") == "BUY" and bar.get("rlh_pattern") == "LONG":
            l_low   = float(bar.get("rlh_stop", bar_low))        # L wick low = stop
            l_open  = float(out.iloc[i - 1]["open"]) if i >= 1 else l_low  # L body start
            sz_lower   = min(l_low, l_open)
            sz_upper   = max(l_low, l_open)
            sz_touches = 0
            in_long    = True
            long_entry_i = i

        # --- Propagate zone values to current row ---
        if sz_lower is not None:
            out.iat[i, out.columns.get_loc("rlh_sz_lower")]       = sz_lower
            out.iat[i, out.columns.get_loc("rlh_sz_upper")]       = sz_upper
            out.iat[i, out.columns.get_loc("rlh_sz_touch_count")] = sz_touches

        # --- B. Exit the LONG phase on first red (non-entry) candle ---
        if in_long and i > long_entry_i:
            if bar_close < bar_open:   # first red candle = color-flip exit
                in_long = False

        # --- C. After LONG exits: watch for touches and breakdown ---
        if not in_long and sz_lower is not None and i > long_entry_i:
            touches_zone = (bar_low <= sz_upper) and (bar_high >= sz_lower)

            if touches_zone:
                sz_touches += 1
                out.iat[i, out.columns.get_loc("rlh_sz_touch_count")] = sz_touches

                # Breakdown: closes BELOW zone lower on touch >= breakdown_touches
                if sz_touches >= breakdown_touches and bar_close < sz_lower:
                    if allow_short and out.iat[i, out.columns.get_loc("signal")] == "WAIT":
                        out.iat[i, out.columns.get_loc("signal")]       = "SHORT"
                        out.iat[i, out.columns.get_loc("rlh_pattern")]  = "SHORT"
                        out.iat[i, out.columns.get_loc("rlh_stop")]     = sz_upper  # stop = zone top
                        out.iat[i, out.columns.get_loc("rlh_sz_breakdown")] = True
                    # Consume zone
                    sz_lower   = None
                    sz_upper   = None
                    sz_touches = 0

    return out
