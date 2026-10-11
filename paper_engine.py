import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from strategy import is_doji

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
TRADE_FIELDS = [
    "timestamp", "symbol", "event", "side", "qty", "price", "stop_loss",
    "target", "trailing_stop", "pnl_inr", "reason"
]

class PaperEngine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.cash = cfg.initial_capital
        self.positions = {}
        Path("logs").mkdir(exist_ok=True)
        self.trades_path = Path("logs/paper_trades.csv")
        if not self.trades_path.exists():
            with self.trades_path.open("w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=TRADE_FIELDS).writeheader()
        self.load_state()

    def _log_trade(self, symbol, event, **kwargs):
        row = {k: "" for k in TRADE_FIELDS}
        row.update(timestamp=datetime.now(IST).isoformat(), symbol=symbol, event=event, **kwargs)
        with self.trades_path.open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=TRADE_FIELDS).writerow(row)
        log.info("PAPER %s %s %s", symbol, event, kwargs)

    def buy(self, symbol, price, stop=None, target=None, reason="rlh_long"):
        if symbol in self.positions or len(self.positions) >= self.cfg.max_open_positions:
            return False
        if price <= 0:
            return False
        if stop is None:
            stop = price * (1 - self.cfg.stop_loss_pct / 100)
        risk_per_share = max(price - stop, 0.1)
        risk_qty = int(self.cfg.risk_per_trade // risk_per_share)
        capital_qty = int(min(self.cfg.max_position_value, self.cash) // price)
        qty = min(risk_qty, capital_qty, self.cfg.max_shares_per_stock)
        if qty < 1:
            log.info("%s skipped: position size below one share.", symbol)
            return False
        cost = qty * price
        if cost > self.cash:
            return False
        pos = {
            "side": "LONG", "qty": qty, "entry": float(price), "stop": float(stop),
            "target": float(target) if target else price * (1 + self.cfg.target_pct / 100),
            "trailing_stop": price * (1 - self.cfg.trailing_stop_pct / 100),
            "high_water": float(price), "cost": cost
        }
        self.cash -= cost
        self.positions[symbol] = pos
        self.save_state()
        self._log_trade(symbol, "BUY", side="LONG", qty=qty, price=price, stop_loss=stop,
                        target=pos["target"], trailing_stop=pos["trailing_stop"],
                        reason=reason)
        return True

    def short(self, symbol, price, stop=None, target=None, reason="rlh_short"):
        if symbol in self.positions or len(self.positions) >= self.cfg.max_open_positions:
            return False
        if price <= 0 or not getattr(self.cfg, "allow_short", True):
            return False
        if stop is None:
            stop = price * (1 + self.cfg.stop_loss_pct / 100)
        risk_per_share = max(stop - price, 0.1)
        risk_qty = int(self.cfg.risk_per_trade // risk_per_share)
        capital_qty = int(min(self.cfg.max_position_value, self.cash) // price)
        qty = min(risk_qty, capital_qty, self.cfg.max_shares_per_stock)
        if qty < 1:
            log.info("%s skipped: position size below one share.", symbol)
            return False
        margin = qty * price
        if margin > self.cash:
            return False
        pos = {
            "side": "SHORT", "qty": qty, "entry": float(price), "stop": float(stop),
            "target": float(target) if target else price * (1 - self.cfg.target_pct / 100),
            "trailing_stop": price * (1 + self.cfg.trailing_stop_pct / 100),
            "low_water": float(price), "cost": margin
        }
        self.cash -= margin
        self.positions[symbol] = pos
        self.save_state()
        self._log_trade(symbol, "SHORT", side="SHORT", qty=qty, price=price, stop_loss=stop,
                        target=pos["target"], trailing_stop=pos["trailing_stop"],
                        reason=reason)
        return True

    def mark_candle(self, symbol, candle):
        """Evaluate stop/target against completed candle OHLC."""
        pos = self.positions.get(symbol)
        if not pos:
            return
        side = pos.get("side", "LONG")
        high, low, close, open_p = float(candle["high"]), float(candle["low"]), float(candle["close"]), float(candle["open"])
        is_rlh = "rlh" in getattr(self.cfg, "strategy_type", "rlh").lower()

        if side == "LONG":
            stop_level = pos["stop"]
            stop_hit = low <= stop_level
            if stop_hit:
                self.close(symbol, stop_level, "stop_loss")
            elif is_rlh:
                # Color flip exit on first red candle (Rule 8)
                if not is_doji(candle) and close < open_p:
                    self.close(symbol, close, "color_flip_target")
            else:
                target_hit = high >= pos["target"]
                if target_hit:
                    self.close(symbol, pos["target"], "target")
                else:
                    pos["high_water"] = max(pos.get("high_water", high), high)
                    pos["trailing_stop"] = max(
                        pos.get("trailing_stop", pos["stop"]),
                        pos["high_water"] * (1 - self.cfg.trailing_stop_pct / 100)
                    )

        elif side == "SHORT":
            stop_level = pos["stop"]
            stop_hit = high >= stop_level
            if stop_hit:
                self.close(symbol, stop_level, "stop_loss")
            elif is_rlh:
                # Color flip exit on first green candle (Rule 8)
                if not is_doji(candle) and close > open_p:
                    self.close(symbol, close, "color_flip_target")
            else:
                target_hit = low <= pos["target"]
                if target_hit:
                    self.close(symbol, pos["target"], "target")

    def close(self, symbol, price, reason):
        pos = self.positions.get(symbol)
        if not pos:
            return
        side = pos.get("side", "LONG")
        qty = pos["qty"]
        price = float(price)
        if side == "LONG":
            proceeds = qty * price
            pnl = (price - pos["entry"]) * qty
            self.cash += proceeds
            event = "SELL"
        else:
            pnl = (pos["entry"] - price) * qty
            margin_and_pnl = pos.get("cost", qty * pos["entry"]) + pnl
            self.cash += margin_and_pnl
            event = "COVER"

        del self.positions[symbol]
        self.save_state()
        self._log_trade(symbol, event, side=side, qty=qty, price=price,
                        stop_loss=pos["stop"], target=pos["target"],
                        trailing_stop=pos.get("trailing_stop", pos["stop"]), pnl_inr=round(pnl, 2),
                        reason=reason)
        log.info("%s paper realized P&L INR %.2f (%s)", symbol, pnl, reason)

    def equity_value(self, last_prices):
        floating_pnl = 0.0
        for s, p in self.positions.items():
            curr = float(last_prices.get(s, p["entry"]))
            if p.get("side", "LONG") == "LONG":
                floating_pnl += (curr - p["entry"]) * p["qty"]
            else:
                floating_pnl += (p["entry"] - curr) * p["qty"]
        invested = sum(p.get("cost", p["qty"] * p["entry"]) for p in self.positions.values())
        return self.cash + invested + floating_pnl

    def save_state(self, path="logs/paper_state.json"):
        state = {"cash": self.cash, "positions": self.positions}
        Path(path).write_text(json.dumps(state, indent=2), encoding="utf-8")

    def load_state(self, path="logs/paper_state.json"):
        p = Path(path)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if "cash" in data:
                    self.cash = float(data["cash"])
                if "positions" in data and isinstance(data["positions"], dict):
                    self.positions = data["positions"]
                log.info("Loaded paper state: cash=%.2f, positions=%d", self.cash, len(self.positions))
                return True
            except Exception as exc:
                log.warning("Could not load paper state: %s", exc)
        return False

    def reset_state(self, initial_capital=None, path="logs/paper_state.json"):
        self.cash = float(initial_capital) if initial_capital is not None else float(self.cfg.initial_capital)
        self.positions = {}
        self.save_state(path)
        log.info("Reset paper state: cash=%.2f", self.cash)

    def get_positions_summary(self, current_prices=None):
        current_prices = current_prices or {}
        rows = []
        for sym, pos in self.positions.items():
            entry = float(pos["entry"])
            qty = int(pos["qty"])
            side = pos.get("side", "LONG")
            curr = float(current_prices.get(sym, entry))
            cost = float(pos.get("cost", qty * entry))
            if side == "LONG":
                curr_val = qty * curr
                pnl = curr_val - cost
                pnl_pct = ((curr - entry) / entry * 100.0) if entry > 0 else 0.0
            else:
                pnl = (entry - curr) * qty
                curr_val = cost + pnl
                pnl_pct = ((entry - curr) / entry * 100.0) if entry > 0 else 0.0

            rows.append({
                "symbol": sym,
                "side": side,
                "qty": qty,
                "entry": entry,
                "current": curr,
                "cost": cost,
                "current_value": curr_val,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": pnl_pct,
                "stop": float(pos["stop"]),
                "target": float(pos["target"]),
                "trailing_stop": float(pos.get("trailing_stop", pos["stop"])),
            })
        return rows
