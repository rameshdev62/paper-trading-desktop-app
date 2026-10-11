"""Backtesting Lab Engine for Yahoo Finance Nifty 50 Paper Trader.

Provides detailed single-symbol and multi-symbol backtesting,
trade metrics calculation, equity curve generation, and data export.
"""

import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from config import Config
from data_yahoo import fetch_candles, load_watchlist
from strategy import add_signals, generate_signals, is_doji

log = logging.getLogger(__name__)


def calculate_metrics(trades: pd.DataFrame, initial_capital: float = 100000.0) -> Dict:
    """Calculate comprehensive performance metrics from backtest trades."""
    if trades.empty or "pnl_inr" not in trades.columns:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "long_trades": 0,
            "short_trades": 0,
            "long_win_rate": 0.0,
            "short_win_rate": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "net_pnl": 0.0,
            "net_roi_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "avg_trade_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "reward_risk_ratio": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "target_exits": 0,
            "stop_exits": 0,
            "color_flip_exits": 0,
        }

    total_trades = len(trades)
    pnls = trades["pnl_inr"].astype(float)
    winning_pnls = pnls[pnls > 0]
    losing_pnls = pnls[pnls < 0]

    wins = int(len(winning_pnls))
    losses = int(len(losing_pnls))
    win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

    gross_profit = float(winning_pnls.sum()) if not winning_pnls.empty else 0.0
    gross_loss = float(abs(losing_pnls.sum())) if not losing_pnls.empty else 0.0
    net_pnl = float(pnls.sum())
    net_roi_pct = (net_pnl / initial_capital * 100.0) if initial_capital > 0 else 0.0

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    avg_trade_pnl = net_pnl / total_trades if total_trades > 0 else 0.0
    avg_win = float(winning_pnls.mean()) if not winning_pnls.empty else 0.0
    avg_loss = float(abs(losing_pnls.mean())) if not losing_pnls.empty else 0.0
    reward_risk_ratio = (avg_win / avg_loss) if avg_loss > 0 else (float("inf") if avg_win > 0 else 0.0)

    largest_win = float(winning_pnls.max()) if not winning_pnls.empty else 0.0
    largest_loss = float(losing_pnls.min()) if not losing_pnls.empty else 0.0

    # Consecutive wins & losses
    max_c_wins = 0
    max_c_losses = 0
    curr_c_wins = 0
    curr_c_losses = 0
    for p in pnls:
        if p > 0:
            curr_c_wins += 1
            curr_c_losses = 0
            if curr_c_wins > max_c_wins:
                max_c_wins = curr_c_wins
        elif p < 0:
            curr_c_losses += 1
            curr_c_wins = 0
            if curr_c_losses > max_c_losses:
                max_c_losses = curr_c_losses
        else:
            curr_c_wins = 0
            curr_c_losses = 0

    # Drawdown calculation
    sorted_trades = trades.sort_values(by="exit_time") if "exit_time" in trades.columns else trades
    cum_pnl = sorted_trades["pnl_inr"].cumsum()
    equity = initial_capital + cum_pnl
    peak = equity.cummax()
    dd = equity - peak
    max_dd = float(dd.min()) if not dd.empty else 0.0
    dd_pct = (dd / peak * 100.0)
    max_dd_pct = float(dd_pct.min()) if not dd_pct.empty else 0.0

    # Reason breakdowns
    reasons = trades["reason"].value_counts().to_dict() if "reason" in trades.columns else {}
    target_exits = int(reasons.get("target", 0))
    stop_exits = int(reasons.get("stop_loss", 0) + reasons.get("stop_or_trailing_stop", 0) + reasons.get("rlh_7d_reappearance", 0))
    color_flip_exits = int(reasons.get("color_flip_target", 0))

    # Long vs Short breakdown
    sides = trades["side"].astype(str) if "side" in trades.columns else pd.Series(["LONG"] * total_trades)
    long_trades = int((sides == "LONG").sum())
    short_trades = int((sides == "SHORT").sum())
    long_wins = int(((sides == "LONG") & (pnls > 0)).sum())
    short_wins = int(((sides == "SHORT") & (pnls > 0)).sum())
    long_win_rate = (long_wins / long_trades * 100.0) if long_trades > 0 else 0.0
    short_win_rate = (short_wins / short_trades * 100.0) if short_trades > 0 else 0.0

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "long_trades": long_trades,
        "short_trades": short_trades,
        "long_win_rate": round(long_win_rate, 2),
        "short_win_rate": round(short_win_rate, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "net_pnl": round(net_pnl, 2),
        "net_roi_pct": round(net_roi_pct, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
        "max_drawdown": round(float(max_dd), 2),
        "max_drawdown_pct": round(float(max_dd_pct), 2),
        "avg_trade_pnl": round(avg_trade_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "reward_risk_ratio": round(reward_risk_ratio, 2) if reward_risk_ratio != float("inf") else 999.0,
        "largest_win": round(largest_win, 2),
        "largest_loss": round(largest_loss, 2),
        "max_consecutive_wins": max_c_wins,
        "max_consecutive_losses": max_c_losses,
        "target_exits": target_exits,
        "stop_exits": stop_exits,
        "color_flip_exits": color_flip_exits,
    }


def compute_equity_curve(trades: pd.DataFrame, initial_capital: float = 100000.0) -> pd.DataFrame:
    """Generate time series of equity, cumulative PnL, peak equity, and drawdown."""
    if trades.empty or "exit_time" not in trades.columns:
        return pd.DataFrame(columns=[
            "time", "trade_num", "pnl_inr", "cum_pnl", "equity", "peak", "drawdown", "drawdown_pct"
        ])

    df = trades.sort_values(by="exit_time").copy()
    start_time = df["entry_time"].iloc[0] if "entry_time" in df.columns else df["exit_time"].iloc[0]

    records = [{
        "time": start_time,
        "trade_num": 0,
        "pnl_inr": 0.0,
        "cum_pnl": 0.0,
        "equity": float(initial_capital),
        "peak": float(initial_capital),
        "drawdown": 0.0,
        "drawdown_pct": 0.0,
    }]

    running_equity = float(initial_capital)
    peak_equity = float(initial_capital)
    cum_pnl = 0.0

    for i, (_, row) in enumerate(df.iterrows(), start=1):
        pnl = float(row["pnl_inr"])
        cum_pnl += pnl
        running_equity += pnl
        if running_equity > peak_equity:
            peak_equity = running_equity
        dd = running_equity - peak_equity
        dd_pct = (dd / peak_equity * 100.0) if peak_equity > 0 else 0.0

        records.append({
            "time": row["exit_time"],
            "trade_num": i,
            "pnl_inr": pnl,
            "cum_pnl": cum_pnl,
            "equity": running_equity,
            "peak": peak_equity,
            "drawdown": dd,
            "drawdown_pct": dd_pct,
        })

    return pd.DataFrame(records)


def run_symbol_backtest(symbol: str, cfg: Config, candles: Optional[pd.DataFrame] = None) -> Dict:
    """Run breakout backtest on a single symbol with detailed metrics & signals."""
    if candles is None:
        candles = fetch_candles(symbol, cfg)

    if candles is None or candles.empty:
        return {
            "symbol": symbol,
            "success": False,
            "error": "No candle data available from Yahoo Finance",
            "candles": pd.DataFrame(),
            "trades": pd.DataFrame(),
            "equity_curve": pd.DataFrame(),
            "metrics": calculate_metrics(pd.DataFrame(), cfg.initial_capital),
        }

    # Generate signals
    data = generate_signals(candles, cfg)
    data = data.dropna(subset=["open", "high", "low", "close", "volume"]).sort_index()

    # Multi-Timeframe (MTF) Trend Confluence Filter (Zero lookahead)
    if getattr(cfg, "htf_filter", False):
        try:
            htf_tf = getattr(cfg, "htf_timeframe", "1d")
            htf_cfg = Config(timeframe=htf_tf, paper_mode=True)
            htf_candles = fetch_candles(symbol, htf_cfg)
            if not htf_candles.empty:
                fast_p = getattr(cfg, "ema_fast_period", 20)
                slow_p = getattr(cfg, "ema_slow_period", 50)
                htf_candles["ema_fast"] = htf_candles["close"].ewm(span=fast_p, adjust=False).mean()
                htf_candles["ema_slow"] = htf_candles["close"].ewm(span=slow_p, adjust=False).mean()
                htf_candles["htf_bullish"] = htf_candles["ema_fast"] > htf_candles["ema_slow"]
                htf_candles["htf_bearish"] = htf_candles["ema_fast"] < htf_candles["ema_slow"]
                # Shift 1 bar to strictly use completed HTF candle before current bar
                htf_ready = htf_candles[["htf_bullish", "htf_bearish"]].shift(1).reset_index()
                ltf_ready = data.reset_index()
                merged = pd.merge_asof(ltf_ready, htf_ready, on="time", direction="backward").set_index("time")
                data["htf_bullish"] = merged["htf_bullish"].fillna(False)
                data["htf_bearish"] = merged["htf_bearish"].fillna(False)
                # Filter BUY when macro is bearish, filter SHORT when macro is bullish
                data.loc[(data["signal"] == "BUY") & (~data["htf_bullish"]), "signal"] = "WAIT"
                data.loc[(data["signal"] == "SHORT") & (~data["htf_bearish"]), "signal"] = "WAIT"
        except Exception as exc:
            log.warning("MTF trend filter failed for %s: %s", symbol, exc)

    trades = []
    pos = None
    is_rlh = "rlh" in getattr(cfg, "strategy_type", "rlh").lower()
    is_ema_cross = "cross" in getattr(cfg, "strategy_type", "").lower()

    for i in range(1, len(data)):
        bar = data.iloc[i]
        prior = data.iloc[i - 1]

        # 1. Evaluate open position
        if pos:
            side = pos.get("side", "LONG")
            exit_price = None
            reason = None

            if side == "LONG":
                # Check stop loss (wick of L or configured stop)
                if float(bar["low"]) <= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "stop_loss"
                # Check Rule 7: 7-day reappearance at same location
                elif is_rlh and bar.get("rlh_7d_reappearance", False) and bar.get("rlh_pattern") == "LONG":
                    exit_price = pos["stop"]
                    reason = "rlh_7d_reappearance"
                # Check Rule 8: Color flip exit (first red candle, non-doji)
                elif is_rlh:
                    if not is_doji(bar) and bar["close"] < bar["open"]:
                        exit_price = float(bar["close"])
                        reason = "color_flip_target"
                # Check 20/50 EMA Death Cross Exit
                elif is_ema_cross and bar.get("ema_death_cross", False):
                    exit_price = float(bar["close"])
                    reason = "death_cross_exit"
                else:
                    # Breakout strategy target & trailing stop
                    stop_level = max(pos["stop"], pos.get("trailing_stop", 0))
                    stop_hit = float(bar["low"]) <= stop_level
                    target_hit = float(bar["high"]) >= pos["target"]
                    if stop_hit or target_hit:
                        exit_price = stop_level if stop_hit else pos["target"]
                        reason = "stop_loss" if stop_hit else "target"

            elif side == "SHORT":
                # Check stop loss (wick of L or configured stop)
                if float(bar["high"]) >= pos["stop"]:
                    exit_price = pos["stop"]
                    reason = "stop_loss"
                # Check Rule 7: 7-day reappearance at same location
                elif is_rlh and bar.get("rlh_7d_reappearance", False) and bar.get("rlh_pattern") == "SHORT":
                    exit_price = pos["stop"]
                    reason = "rlh_7d_reappearance"
                # Check Rule 8: Color flip exit (first green candle, non-doji)
                elif is_rlh:
                    if not is_doji(bar) and bar["close"] > bar["open"]:
                        exit_price = float(bar["close"])
                        reason = "color_flip_target"
                # Check 20/50 EMA Golden Cross Exit
                elif is_ema_cross and bar.get("ema_golden_cross", False):
                    exit_price = float(bar["close"])
                    reason = "golden_cross_exit"
                else:
                    stop_level = min(pos["stop"], pos.get("trailing_stop", float("inf")))
                    stop_hit = float(bar["high"]) >= stop_level
                    target_hit = float(bar["low"]) <= pos["target"]
                    if stop_hit or target_hit:
                        exit_price = stop_level if stop_hit else pos["target"]
                        reason = "stop_loss" if stop_hit else "target"

            if exit_price is not None:
                if side == "LONG":
                    pnl = (exit_price - pos["entry"]) * pos["qty"]
                    ret_pct = ((exit_price - pos["entry"]) / pos["entry"]) * 100.0
                else:
                    pnl = (pos["entry"] - exit_price) * pos["qty"]
                    ret_pct = ((pos["entry"] - exit_price) / pos["entry"]) * 100.0

                entry_time = pos["entry_time"]
                exit_time = data.index[i]
                try:
                    duration_mins = int((exit_time - entry_time).total_seconds() / 60)
                except Exception:
                    duration_mins = 0

                trades.append({
                    "symbol": symbol,
                    "side": side,
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                    "duration_mins": duration_mins,
                    "entry": round(float(pos["entry"]), 2),
                    "exit": round(float(exit_price), 2),
                    "qty": int(pos["qty"]),
                    "pnl_inr": round(float(pnl), 2),
                    "return_pct": round(float(ret_pct), 2),
                    "reason": reason,
                })
                pos = None
            else:
                if not is_rlh and side == "LONG":
                    pos["high_water"] = max(pos["high_water"], float(bar["high"]))
                    pos["trailing_stop"] = max(
                        pos["trailing_stop"],
                        pos["high_water"] * (1 - cfg.trailing_stop_pct / 100.0)
                    )

        # 2. Evaluate new entry
        if pos is None:
            if prior["signal"] == "BUY":
                entry = float(bar["open"])
                if entry > 0:
                    if is_rlh and pd.notna(prior.get("rlh_stop")):
                        stop = float(prior["rlh_stop"])
                    else:
                        stop = entry * (1 - cfg.stop_loss_pct / 100.0)

                    risk_diff = max(entry - stop, 0.1)
                    risk_qty = int(cfg.risk_per_trade // risk_diff)
                    max_value_qty = int(cfg.max_position_value // entry)
                    qty = min(risk_qty, max_value_qty, cfg.max_shares_per_stock)

                    if qty >= 1:
                        pos = {
                            "side": "LONG",
                            "entry_time": data.index[i],
                            "entry": entry,
                            "qty": qty,
                            "stop": stop,
                            "target": entry * (1 + cfg.target_pct / 100.0),
                            "trailing_stop": entry * (1 - cfg.trailing_stop_pct / 100.0),
                            "high_water": entry,
                        }

            elif prior["signal"] == "SHORT" and getattr(cfg, "allow_short", True):
                entry = float(bar["open"])
                if entry > 0:
                    if is_rlh and pd.notna(prior.get("rlh_stop")):
                        stop = float(prior["rlh_stop"])
                    else:
                        stop = entry * (1 + cfg.stop_loss_pct / 100.0)

                    risk_diff = max(stop - entry, 0.1)
                    risk_qty = int(cfg.risk_per_trade // risk_diff)
                    max_value_qty = int(cfg.max_position_value // entry)
                    qty = min(risk_qty, max_value_qty, cfg.max_shares_per_stock)

                    if qty >= 1:
                        pos = {
                            "side": "SHORT",
                            "entry_time": data.index[i],
                            "entry": entry,
                            "qty": qty,
                            "stop": stop,
                            "target": entry * (1 - cfg.target_pct / 100.0),
                            "trailing_stop": entry * (1 + cfg.trailing_stop_pct / 100.0),
                            "low_water": entry,
                        }

    trades_df = pd.DataFrame(trades)
    equity_curve = compute_equity_curve(trades_df, cfg.initial_capital)
    metrics = calculate_metrics(trades_df, cfg.initial_capital)

    return {
        "symbol": symbol,
        "success": True,
        "candles": data,
        "trades": trades_df,
        "equity_curve": equity_curve,
        "metrics": metrics,
    }


def run_batch_backtest(
    symbols: List[str],
    cfg: Config,
    progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict:
    """Run historical backtest across multiple symbols in the watchlist."""
    all_trades = []
    symbol_results = []
    results_by_symbol = {}
    total = len(symbols)

    for i, symbol in enumerate(symbols, start=1):
        if cancel_check and cancel_check():
            if progress_callback:
                progress_callback(i, total, symbol, "Cancelled by user")
            break

        if progress_callback:
            progress_callback(i, total, symbol, f"Fetching data for {symbol} ({i}/{total})...")

        try:
            res = run_symbol_backtest(symbol, cfg)
            results_by_symbol[symbol] = res
            if res["success"]:
                t_df = res["trades"]
                if not t_df.empty:
                    all_trades.append(t_df)

                sym_m = res["metrics"]
                symbol_results.append({
                    "symbol": symbol,
                    "trades": sym_m["total_trades"],
                    "win_rate": sym_m["win_rate"],
                    "net_pnl": sym_m["net_pnl"],
                    "profit_factor": sym_m["profit_factor"],
                    "max_drawdown": sym_m["max_drawdown"],
                    "status": "OK",
                })
            else:
                symbol_results.append({
                    "symbol": symbol,
                    "trades": 0,
                    "win_rate": 0.0,
                    "net_pnl": 0.0,
                    "profit_factor": 0.0,
                    "max_drawdown": 0.0,
                    "status": res.get("error", "Failed"),
                })
        except Exception as exc:
            log.warning("Batch backtest error for %s: %s", symbol, exc)
            results_by_symbol[symbol] = {"success": False, "error": str(exc), "symbol": symbol}
            symbol_results.append({
                "symbol": symbol,
                "trades": 0,
                "win_rate": 0.0,
                "net_pnl": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "status": f"Error: {exc}",
            })

    if all_trades:
        combined_trades = pd.concat(all_trades, ignore_index=True)
        combined_trades = combined_trades.sort_values(by="exit_time").reset_index(drop=True)
    else:
        combined_trades = pd.DataFrame()

    summary_df = pd.DataFrame(symbol_results)
    portfolio_equity = compute_equity_curve(combined_trades, cfg.initial_capital)
    portfolio_metrics = calculate_metrics(combined_trades, cfg.initial_capital)

    return {
        "success": True,
        "all_trades": combined_trades,
        "symbol_summary": summary_df,
        "results_by_symbol": results_by_symbol,
        "equity_curve": portfolio_equity,
        "metrics": portfolio_metrics,
        "total_symbols": total,
    }


def run_multi_timeframe_comparison(
    symbol: str,
    base_cfg: Config,
    timeframes: Optional[List[str]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict:
    """Run backtests across multiple timeframes for a symbol to compare performance."""
    if timeframes is None:
        timeframes = ["1m", "3m", "5m", "15m", "30m", "1d", "1w", "1mo"]

    results_by_tf = {}
    summary_rows = []
    total = len(timeframes)

    for i, tf in enumerate(timeframes, start=1):
        if cancel_check and cancel_check():
            break

        if progress_callback:
            progress_callback(i, total, f"Testing {symbol} on {tf} ({i}/{total})...")

        try:
            cfg_tf = Config(
                timeframe=tf,
                paper_mode=base_cfg.paper_mode,
                initial_capital=base_cfg.initial_capital,
                risk_per_trade=base_cfg.risk_per_trade,
                max_position_value=base_cfg.max_position_value,
                lookback_breakout=base_cfg.lookback_breakout,
                lookback_volume=base_cfg.lookback_volume,
                volume_multiplier=base_cfg.volume_multiplier,
                stop_loss_pct=base_cfg.stop_loss_pct,
                target_pct=base_cfg.target_pct,
                trailing_stop_pct=base_cfg.trailing_stop_pct,
                htf_filter=base_cfg.htf_filter,
                htf_timeframe=base_cfg.htf_timeframe,
                htf_ema_period=base_cfg.htf_ema_period,
                strategy_type=base_cfg.strategy_type,
                allow_short=base_cfg.allow_short,
                rlh_cooldown_days=base_cfg.rlh_cooldown_days,
                rlh_proximity_pct=base_cfg.rlh_proximity_pct,
                rlh_prefer_l_color=base_cfg.rlh_prefer_l_color,
                atr_period=getattr(base_cfg, "atr_period", 14),
                rlh_use_atr=getattr(base_cfg, "rlh_use_atr", True),
            )
            res = run_symbol_backtest(symbol, cfg_tf)
            results_by_tf[tf] = res

            if res["success"]:
                m = res["metrics"]
                summary_rows.append({
                    "timeframe": tf,
                    "trades": m["total_trades"],
                    "win_rate": m["win_rate"],
                    "net_pnl": m["net_pnl"],
                    "net_roi_pct": m["net_roi_pct"],
                    "profit_factor": m["profit_factor"],
                    "max_drawdown": m["max_drawdown"],
                    "avg_trade_pnl": m["avg_trade_pnl"],
                    "reward_risk": m["reward_risk_ratio"],
                })
            else:
                summary_rows.append({
                    "timeframe": tf,
                    "trades": 0,
                    "win_rate": 0.0,
                    "net_pnl": 0.0,
                    "net_roi_pct": 0.0,
                    "profit_factor": 0.0,
                    "max_drawdown": 0.0,
                    "avg_trade_pnl": 0.0,
                    "reward_risk": 0.0,
                })
        except Exception as exc:
            log.warning("Multi-TF error on %s for %s: %s", symbol, tf, exc)

    df_summary = pd.DataFrame(summary_rows)
    best_tf = None
    if not df_summary.empty and "net_pnl" in df_summary.columns:
        best_idx = df_summary["net_pnl"].idxmax()
        best_tf = df_summary.loc[best_idx, "timeframe"]

    return {
        "success": True,
        "symbol": symbol,
        "results_by_tf": results_by_tf,
        "comparison_table": df_summary,
        "best_timeframe": best_tf,
    }

