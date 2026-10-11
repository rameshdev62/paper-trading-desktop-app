"""Service layer for Live Paper Trading Scanner and Manual Execution.

Coordinates between the UI, PaperEngine, and Yahoo Finance real-time data.
Supports background continuous scanning, single-pass on-demand scanning,
manual orders, position closing, and portfolio state tracking.
"""

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo
import pandas as pd

from config import Config
from data_yahoo import fetch_candles
from paper_engine import PaperEngine
from strategy import add_signals, generate_signals

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def is_market_open() -> bool:
    """Check if Indian Standard Time is within NSE regular trading hours (09:15 - 15:30 Mon-Fri)."""
    now = datetime.now(IST)
    return now.weekday() < 5 and (now.hour, now.minute) >= (9, 15) and (now.hour, now.minute) < (15, 30)


class PaperTradingService:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.engine = PaperEngine(cfg)
        self.is_scanning = False
        self.stop_requested = False
        self.scanner_thread: Optional[threading.Thread] = None
        self.processed_candles: Dict[str, str] = {}
        self.last_prices: Dict[str, float] = {}
        self._lock = threading.Lock()

    def update_config(self, cfg: Config):
        with self._lock:
            self.cfg = cfg
            self.engine.cfg = cfg

    def get_portfolio_summary(self) -> Dict:
        with self._lock:
            cash = self.engine.cash
            pos_summary = self.engine.get_positions_summary(self.last_prices)
            invested = sum(p["cost"] for p in pos_summary)
            current_val = sum(p["current_value"] for p in pos_summary)
            unrealized_pnl = current_val - invested
            equity = cash + current_val

            # Read total realized PnL from trades log
            realized_pnl = 0.0
            trades_file = Path("logs/paper_trades.csv")
            if trades_file.exists():
                try:
                    df = pd.read_csv(trades_file)
                    if not df.empty and "pnl_inr" in df.columns:
                        realized_pnl = float(df["pnl_inr"].dropna().sum())
                except Exception:
                    pass

            return {
                "equity": equity,
                "cash": cash,
                "invested": invested,
                "current_val": current_val,
                "unrealized_pnl": unrealized_pnl,
                "realized_pnl": realized_pnl,
                "positions_count": len(self.engine.positions),
                "positions": pos_summary,
            }

    def scan_single_symbol(self, symbol: str, log_cb: Optional[Callable[[str], None]] = None) -> Dict:
        """Scan a single symbol for breakout signals or position exits."""
        try:
            candles = fetch_candles(symbol, self.cfg)
            min_req = max(self.cfg.lookback_breakout, self.cfg.lookback_volume) + 2
            if candles.empty or len(candles) < min_req:
                return {"symbol": symbol, "status": "insufficient_data"}

            signals = generate_signals(candles, self.cfg)
            last = signals.iloc[-1]
            candle_time = str(signals.index[-1])
            close_price = float(last["close"])

            with self._lock:
                self.last_prices[symbol] = close_price

            prev_time = self.processed_candles.get(symbol)
            is_new = prev_time != candle_time
            self.processed_candles[symbol] = candle_time

            action = "NONE"
            with self._lock:
                if symbol in self.engine.positions:
                    # Check exits against completed candle
                    pos_before = dict(self.engine.positions[symbol])
                    self.engine.mark_candle(symbol, last)

                    if symbol not in self.engine.positions:
                        action = "EXIT_STOP_OR_TARGET"
                        if log_cb:
                            log_cb(f"[{symbol}] Exit triggered at ₹{close_price:.2f}")
                    elif last["signal"] == "BEARISH_EXIT":
                        self.engine.close(symbol, close_price, "bearish_breakout_exit")
                        action = "EXIT_BEARISH"
                        if log_cb:
                            log_cb(f"[{symbol}] Bearish breakout exit executed at ₹{close_price:.2f}")
                elif last["signal"] == "BUY" and is_new:
                    stop_p = float(last["rlh_stop"]) if pd.notna(last.get("rlh_stop")) else None
                    bought = self.engine.buy(symbol, close_price, stop=stop_p, reason=f"{self.cfg.timeframe}_{self.cfg.strategy_type}")
                    if bought:
                        action = "BUY_EXECUTED"
                        if log_cb:
                            log_cb(f"[{symbol}] BUY executed! Qty={self.engine.positions[symbol]['qty']} @ ₹{close_price:.2f}")
                    else:
                        action = "BUY_SKIPPED"
                        if log_cb:
                            log_cb(f"[{symbol}] BUY signal detected but capacity/cash skipped order.")
                elif last["signal"] == "SHORT" and is_new and getattr(self.cfg, "allow_short", True):
                    stop_p = float(last["rlh_stop"]) if pd.notna(last.get("rlh_stop")) else None
                    shorted = self.engine.short(symbol, close_price, stop=stop_p, reason=f"{self.cfg.timeframe}_{self.cfg.strategy_type}")
                    if shorted:
                        action = "SHORT_EXECUTED"
                        if log_cb:
                            log_cb(f"[{symbol}] SHORT executed! Qty={self.engine.positions[symbol]['qty']} @ ₹{close_price:.2f}")
                    else:
                        action = "SHORT_SKIPPED"
                        if log_cb:
                            log_cb(f"[{symbol}] SHORT signal detected but capacity/cash skipped order.")

                self.engine.save_state()

            return {
                "symbol": symbol,
                "candle_time": candle_time,
                "close": close_price,
                "signal": last["signal"],
                "action": action,
            }
        except Exception as exc:
            log.warning("Scan error for %s: %s", symbol, exc)
            return {"symbol": symbol, "status": f"error: {exc}"}

    def scan_watchlist_pass(
        self,
        symbols: List[str],
        log_cb: Optional[Callable[[str], None]] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[Dict]:
        """Perform a single complete scan pass across all watchlist symbols."""
        results = []
        total = len(symbols)
        for i, sym in enumerate(symbols, start=1):
            if self.stop_requested:
                break
            if progress_cb:
                progress_cb(i, total, sym)
            res = self.scan_single_symbol(sym, log_cb=log_cb)
            results.append(res)
        return results

    def start_continuous_scanner(
        self,
        symbols: List[str],
        poll_seconds: int = 90,
        enforce_market_hours: bool = True,
        log_cb: Optional[Callable[[str], None]] = None,
        on_pass_complete_cb: Optional[Callable[[], None]] = None,
    ):
        """Start background scanner loop."""
        if self.is_scanning:
            return

        self.is_scanning = True
        self.stop_requested = False

        def worker():
            if log_cb:
                log_cb(f"Paper Trading Scanner started (Poll Interval: {poll_seconds}s).")

            while not self.stop_requested:
                if enforce_market_hours and not is_market_open():
                    if log_cb:
                        log_cb("Outside NSE market hours (09:15-15:30 IST). Pausing scanner...")
                    for _ in range(min(60, poll_seconds)):
                        if self.stop_requested:
                            break
                        time.sleep(1)
                    continue

                if log_cb:
                    log_cb(f"Starting watchlist scan cycle across {len(symbols)} symbols...")

                self.scan_watchlist_pass(symbols, log_cb=log_cb)

                if on_pass_complete_cb:
                    on_pass_complete_cb()

                if log_cb:
                    summary = self.get_portfolio_summary()
                    log_cb(f"Cycle complete. Equity: ₹{summary['equity']:,.2f} | Open Positions: {summary['positions_count']}")

                # Sleep with interrupt check
                for _ in range(poll_seconds):
                    if self.stop_requested:
                        break
                    time.sleep(1)

            self.is_scanning = False
            if log_cb:
                log_cb("Paper Trading Scanner stopped.")

        self.scanner_thread = threading.Thread(target=worker, daemon=True)
        self.scanner_thread.start()

    def stop_continuous_scanner(self):
        self.stop_requested = True
        self.is_scanning = False

    def manual_buy(self, symbol: str, price: Optional[float] = None, qty: Optional[int] = None) -> bool:
        """Execute a manual paper BUY order."""
        with self._lock:
            if price is None or price <= 0:
                # Fetch recent price
                candles = fetch_candles(symbol, self.cfg)
                if candles.empty:
                    raise ValueError(f"Could not fetch market price for {symbol}")
                price = float(candles.iloc[-1]["close"])

            self.last_prices[symbol] = price

            if qty is not None and qty > 0:
                cost = qty * price
                if cost > self.engine.cash:
                    raise ValueError(f"Insufficient cash (Requires ₹{cost:,.2f}, Available ₹{self.engine.cash:,.2f})")
                if len(self.engine.positions) >= self.cfg.max_open_positions:
                    raise ValueError(f"Max open positions reached ({self.cfg.max_open_positions})")

                stop = price * (1 - self.cfg.stop_loss_pct / 100.0)
                pos = {
                    "qty": qty, "entry": float(price), "stop": stop,
                    "target": price * (1 + self.cfg.target_pct / 100.0),
                    "trailing_stop": price * (1 - self.cfg.trailing_stop_pct / 100.0),
                    "high_water": float(price), "cost": cost
                }
                self.engine.cash -= cost
                self.engine.positions[symbol] = pos
                self.engine._log_trade(symbol, "BUY", qty=qty, price=price, stop_loss=stop,
                                       target=pos["target"], trailing_stop=pos["trailing_stop"],
                                       reason="manual_order")
                self.engine.save_state()
                return True
            else:
                success = self.engine.buy(symbol, price, reason="manual_order")
                if success:
                    self.engine.save_state()
                return success

    def manual_close(self, symbol: str, price: Optional[float] = None) -> bool:
        """Close an existing paper position."""
        with self._lock:
            if symbol not in self.engine.positions:
                return False
            if price is None or price <= 0:
                candles = fetch_candles(symbol, self.cfg)
                if not candles.empty:
                    price = float(candles.iloc[-1]["close"])
                else:
                    price = self.engine.positions[symbol]["entry"]

            self.engine.close(symbol, price, reason="manual_exit")
            self.engine.save_state()
            return True

    def reset_portfolio(self, initial_capital: Optional[float] = None):
        """Reset virtual cash balance and wipe open positions."""
        with self._lock:
            self.engine.reset_state(initial_capital)
            self.processed_candles.clear()
