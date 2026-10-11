import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from config import Config
from data_yahoo import fetch_candles, load_watchlist
from logging_setup import setup_logging
from strategy import add_signals, generate_signals
from paper_engine import PaperEngine

IST = ZoneInfo("Asia/Kolkata")
log = logging.getLogger(__name__)

def market_open():
    now = datetime.now(IST)
    return now.weekday() < 5 and (now.hour, now.minute) >= (9, 15) and (now.hour, now.minute) < (15, 30)

def main():
    cfg = Config()
    cfg.validate()
    setup_logging(cfg.log_level)
    if not cfg.paper_mode:
        raise RuntimeError("Safety stop: PAPER_MODE must remain true.")
    symbols = load_watchlist()
    engine = PaperEngine(cfg)
    processed = {}
    log.info("Yahoo Finance Nifty 50 paper scanner started (Strategy: %s).", cfg.strategy_type.upper())

    while True:
        try:
            if not market_open():
                time.sleep(max(30, cfg.poll_seconds))
                continue
            last_prices = {}
            for symbol in symbols:
                candles = fetch_candles(symbol, cfg)
                if candles.empty or len(candles) < 5:
                    continue
                signals = generate_signals(candles, cfg)
                last = signals.iloc[-1]
                candle_time = signals.index[-1]
                last_prices[symbol] = float(last["close"])

                # Only process each completed candle once.
                if processed.get(symbol) == candle_time:
                    continue
                processed[symbol] = candle_time
                log.info("%s time=%s close=%.2f signal=%s",
                         symbol, candle_time, last["close"], last["signal"])

                if symbol in engine.positions:
                    engine.mark_candle(symbol, last)
                elif last["signal"] == "BUY":
                    stop_p = float(last["rlh_stop"]) if "rlh_stop" in last and pd.notna(last["rlh_stop"]) else None
                    engine.buy(symbol, float(last["close"]), stop=stop_p, reason="rlh_long" if cfg.strategy_type == "rlh" else "breakout")
                elif last["signal"] == "SHORT" and getattr(cfg, "allow_short", True):
                    stop_p = float(last["rlh_stop"]) if "rlh_stop" in last and pd.notna(last["rlh_stop"]) else None
                    engine.short(symbol, float(last["close"]), stop=stop_p, reason="rlh_short")
            engine.save_state()
            log.info("Paper equity=INR %.2f | cash=INR %.2f | positions=%d",
                     engine.equity_value(last_prices), engine.cash, len(engine.positions))
            time.sleep(max(30, cfg.poll_seconds))
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception:
            log.exception("Scanner loop failed; retrying.")
            time.sleep(max(30, cfg.poll_seconds))

if __name__ == "__main__":
    main()
