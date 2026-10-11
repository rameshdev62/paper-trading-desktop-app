import argparse
import logging
from pathlib import Path
import pandas as pd

from strategy import add_signals

log = logging.getLogger(__name__)

def backtest_symbol(symbol: str, df: pd.DataFrame, cfg, output_dir: str = "logs") -> pd.DataFrame:
    """Run symbol backtest using unified backtesting engine supporting RLH & Breakout."""
    from backtest_lab import run_symbol_backtest
    res = run_symbol_backtest(symbol, cfg, candles=df)
    trades = res.get("trades", pd.DataFrame())
    if not trades.empty:
        Path(output_dir).mkdir(exist_ok=True)
        out_path = Path(output_dir) / f"backtest_{symbol.replace('.', '_')}.csv"
        trades.to_csv(out_path, index=False)
    return trades

def main():
    from config import Config
    from data_yahoo import fetch_candles, load_watchlist
    from logging_setup import setup_logging
    cfg = Config()
    cfg.validate()
    setup_logging(cfg.log_level)
    all_trades = []
    for symbol in load_watchlist():
        try:
            candles = fetch_candles(symbol, cfg)
        except Exception as exc:
            log.warning("%s fetch failed: %s", symbol, exc)
            continue
        if candles.empty:
            print(f"{symbol}: no data")
            continue
        result = backtest_symbol(symbol, candles, cfg)
        if not result.empty:
            all_trades.append(result)
        print(f"{symbol}: {len(result)} trades")
    if not all_trades:
        print("No backtest trades. Yahoo data may be unavailable or strategy thresholds may be too strict.")
        return
    combined = pd.concat(all_trades, ignore_index=True)
    combined.to_csv("logs/backtest_all_trades.csv", index=False)
    wins = int((combined["pnl_inr"] > 0).sum())
    gross_profit = combined.loc[combined.pnl_inr > 0, "pnl_inr"].sum()
    gross_loss = abs(combined.loc[combined.pnl_inr < 0, "pnl_inr"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf")
    print(f"Trades: {len(combined)}")
    print(f"Win rate: {wins / len(combined) * 100:.2f}%")
    print(f"Net P&L before costs: INR {combined.pnl_inr.sum():.2f}")
    print(f"Profit factor before costs: {profit_factor:.2f}")
    print("Saved logs/backtest_all_trades.csv")

if __name__ == "__main__":
    main()
