import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def _int(name, default):
    v = os.getenv(name, "").strip()
    return int(v) if v else default

def _float(name, default):
    v = os.getenv(name, "").strip()
    return float(v) if v else default

@dataclass(frozen=True)
class Config:
    paper_mode: bool = os.getenv("PAPER_MODE", "true").lower() == "true"
    timeframe: str = os.getenv("TIMEFRAME", "1d")
    lookback_breakout: int = _int("LOOKBACK_BREAKOUT", 12)
    lookback_volume: int = _int("LOOKBACK_VOLUME", 20)
    volume_multiplier: float = _float("VOLUME_MULTIPLIER", 1.2)
    initial_capital: float = _float("INITIAL_CAPITAL_INR", 100000)
    risk_per_trade: float = _float("RISK_PER_TRADE_INR", 100)
    max_position_value: float = _float("MAX_POSITION_VALUE_INR", 10000)
    max_open_positions: int = _int("MAX_OPEN_POSITIONS", 3)
    max_shares_per_stock: int = _int("MAX_SHARES_PER_STOCK", 500)
    stop_loss_pct: float = _float("STOP_LOSS_PCT", 1.0)
    target_pct: float = _float("TARGET_PCT", 2.0)
    trailing_stop_pct: float = _float("TRAILING_STOP_PCT", 0.75)
    close_buffer_seconds: int = _int("CANDLE_CLOSE_BUFFER_SECONDS", 60)
    poll_seconds: int = _int("POLL_SECONDS", 90)
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    htf_filter: bool = os.getenv("HTF_FILTER", "false").lower() == "true"
    htf_timeframe: str = os.getenv("HTF_TIMEFRAME", "1d")
    htf_ema_period: int = _int("HTF_EMA_PERIOD", 20)

    strategy_type: str = os.getenv("STRATEGY_TYPE", "rlh_atr").lower()
    allow_short: bool = os.getenv("ALLOW_SHORT", "true").lower() == "true"
    atr_period: int = _int("ATR_PERIOD", 14)
    rlh_use_atr: bool = os.getenv("RLH_USE_ATR", "true").lower() == "true"
    rlh_cooldown_days: int = _int("RLH_COOLDOWN_DAYS", 7)
    rlh_proximity_pct: float = _float("RLH_PROXIMITY_PCT", 2.0)
    rlh_prefer_l_color: bool = os.getenv("RLH_PREFER_L_COLOR", "false").lower() == "true"

    ema_fast_period: int = _int("EMA_FAST_PERIOD", 20)
    ema_slow_period: int = _int("EMA_SLOW_PERIOD", 50)
    use_ema_trend_filter: bool = os.getenv("USE_EMA_TREND_FILTER", "false").lower() == "true"

    def validate(self):
        if not self.paper_mode:
            raise ValueError("This project is paper-only. Set PAPER_MODE=true.")
        valid_strats = ("rlh_atr", "rlh", "rlh_classic", "rlh_ema", "ema_cross", "breakout", "combined", "rlh_support_zone")
        if self.strategy_type not in valid_strats:
            raise ValueError(f"Strategy '{self.strategy_type}' not supported. Choose from {valid_strats}.")
        supported_tf = ("1m", "3m", "5m", "15m", "30m", "60m", "1h", "1d", "1w", "1wk", "1mo", "1M")
        if self.timeframe not in supported_tf:
            raise ValueError(f"Timeframe '{self.timeframe}' not supported. Choose from {supported_tf}.")
        if self.htf_timeframe not in supported_tf:
            raise ValueError(f"HTF Timeframe '{self.htf_timeframe}' not supported. Choose from {supported_tf}.")
        if min(self.lookback_breakout, self.lookback_volume, self.max_open_positions,
               self.max_shares_per_stock) < 1:
            raise ValueError("Lookbacks and position limits must be positive.")
        if min(self.initial_capital, self.risk_per_trade, self.max_position_value,
               self.volume_multiplier, self.stop_loss_pct, self.target_pct,
               self.trailing_stop_pct) <= 0:
            raise ValueError("Risk and strategy settings must be positive.")
        if self.stop_loss_pct >= 100:
            raise ValueError("STOP_LOSS_PCT must be below 100.")
