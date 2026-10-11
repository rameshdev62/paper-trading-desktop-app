# Yahoo Finance Nifty 50 Paper Trading & Backtesting System

A Python paper-trading and backtesting system for NSE equities (Nifty 50 constituents) using Yahoo Finance via `yfinance`. It supports all key execution timeframes: **`1m`, `3m`, `5m`, `15m`, `30m`, `60m` (1h), `1d` (Daily), `1w` (Weekly), and `1mo` (Monthly)**, evaluates breakout and volume signals, sizes positions dynamically, enforces stop-loss / trailing-stop / target exits, and generates comprehensive trade logs.

> [!NOTE]
> Detailed user guide and architectural explanation is documented in [use.md](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/use.md).

---

## Key Features
- **Configurable Timeframes**: Supports intraday (`1m`, `3m`, `5m`, `15m`, `30m`, `60m`) and swing/macro (`1d`, `1w`, `1mo`) timeframes with native resampling.
- **Selectable Strategy Engines (GUI Dropdown with Multiple Items)**:
  - **1. R-L-H Pattern (ATR Filtered)** *(Recommended)*: 3-candle progression (`Range(L) < Range(R) < Range(H)`, `Body(H) > Body(R)`) with Stop Loss at $L$'s wick and **ATR Volatility Filtering**:
    - **$\text{TR}(R) > \text{ATR}$**: The $R$ candle's True Range must be greater than the ATR (initial expansion).
    - **$\text{TR}(L) \le \text{ATR}$**: The $L$ candle's True Range must not be greater than the ATR (compression / coil).
    - **$\text{TR}(H) > \text{ATR}$**: The $H$ candle's True Range must be greater than the ATR (breakout impulse).
    - Stop Loss at $L$'s wick, color-flip trailing target exits, and 7-day reappearance filter for both **LONG** and **SHORT** setups.
  - **2. R-L-H Pattern (ATR + 20/50 EMA Trend)**: Dual confluence executing R-L-H expansion entries strictly in the direction of the 20/50 EMA trend (Long when 20 EMA > 50 EMA; Short when 20 EMA < 50 EMA).
  - **3. 20/50 EMA Golden/Death Cross Trend Strategy**: Generates BUY entries on 20 EMA crossing strictly above 50 EMA (Golden Cross) and SHORT entries on 20 EMA crossing strictly below 50 EMA (Death Cross).
  - **4. R-L-H Pattern (Classic Range)**: Geometry-only R-L-H progression without ATR volatility filter.
  - **5. 20-Bar Volume Breakout**: Volume-confirmed high-water breakout signals with upper candle body positioning.
  - **6. Combined (R-L-H ATR + 20/50 EMA + Breakout)**: Multi-strategy confluence executing high-conviction signals from all three engines.
  - **7. RLH Support Zone (3-Touch Breakdown SHORT)**: After RLH pattern rallies, the $L$ candle wick and body start form a support zone. Monitors retests with badge counters (`T:1`, `T:2`, `T:3`). On the 3rd touch, when price closes below support, a SHORT Breakdown signal fires with stop loss at the zone upper boundary. Includes interactive shaded chart bands and breakdown arrows.
- **20/50 EMA Cross Trend Detection**: Real-time trend state classification (`BULLISH` vs `BEARISH`), Golden Cross & Death Cross event tracking, dynamic chart overlay with amber/purple EMA lines, and higher-timeframe trend filtering.
- **Strict Paper Trading**: Strictly paper-only simulation (`PAPER_MODE=true`). No real broker connectivity or live execution risk.
- **Dynamic Risk Sizing**: Automatically sizes positions according to rupee risk budget, maximum position caps, and available virtual cash.
- **Color-Flip & Trailing Exits**: Dynamic exits based on candle color flips and wick-based stop loss enforcement.
- **Comprehensive Logging**: Generates CSV records for every paper trade and backtest run.

---

## Quick Start

### 1. Installation
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configuration (`.env`)
```ini
# Timeframe: "1d" (Daily) or "15m" (15-Minute)
TIMEFRAME=1d

# Safety
PAPER_MODE=true

# Strategy Settings
LOOKBACK_BREAKOUT=12
LOOKBACK_VOLUME=20
VOLUME_MULTIPLIER=1.2

# Risk & Capital Management
INITIAL_CAPITAL_INR=100000
RISK_PER_TRADE_INR=100
MAX_POSITION_VALUE_INR=10000
MAX_OPEN_POSITIONS=3
STOP_LOSS_PCT=1.0
TARGET_PCT=2.0
TRAILING_STOP_PCT=0.75
```

### 3. Launch Desktop GUI Application (3 Integrated Modules)
```bash
./run_gui.sh
# Or alternatively:
./.venv/bin/python3 app_gui.py
```
The desktop terminal provides three integrated modules accessible from the top navigation bar:
- **🗂️ Collapsible Sidebar**: Click **`◀ Hide Sidebar` / `▶ Show Sidebar`** in the top header or press **`Ctrl+B`** to toggle the sidebar and expand charts & tables to 100% full width.
- **🔴 Module 1: Live Paper Trading Monitor**
  - Real-time Portfolio Equity, available cash, invested capital, and unrealized/realized P&L.
  - Active Open Positions table with 1-click **Close Position** action.
  - Continuous scanner controller with market hours toggle, custom poll intervals, and **⚡ Scan Watchlist Now (Single Pass)**.
  - Manual Paper Execution desk (Market price fetch, risk-sized quantities, manual BUY orders).
  - Live activity feed terminal & historical paper trades log (`logs/paper_trades.csv`).
- **📈 Module 2: Historical Backtesting Lab (Multiple Timeframe Support)**
  - Multiple timeframe support: `1m`, `3m`, `5m`, `15m`, `30m`, `60m` (1h), `1d` (Daily), `1w` (Weekly), and `1mo` (Monthly).
  - **Multi-TF Compare Mode**: Simulates `1m`, `3m`, `5m`, `15m`, `30m`, `1d`, `1w`, and `1mo` side-by-side with automatic best timeframe detection and overlaid comparative equity curves.
  - **Multi-Timeframe Trend Confluence**: Filter lower-timeframe breakouts with a Higher Timeframe (Daily `1d`, Weekly `1w`, or Hourly `60m`) 20 EMA macro trend filter.
  - Single symbol or entire 50-stock watchlist batch testing.
  - **Scan All Watchlist & Interactive Stock Chart Inspection**: Scan all watchlist tickers at once; choose any stock from the chart toolbar dropdown or double-click in the **Symbol Performance Matrix** to instantly view its candlestick chart, volume, and trade signals without re-fetching.
  - Interactive **Equity Curve** & **Underwater Drawdown** charts.
  - **Unified Price Action & Volume Chart**: Candlesticks, 20/50 EMAs (green EMA 20, red EMA 50), trade markers (`▲` BUY, `▼` SHORT, `★` target, `✕` loss), default **Last 200** candle window, and volume bars rendered together on the **same chart** (TradingView-style).
  - Filterable **Trade Journal** with 1-click CSV Export.
  - **Symbol Performance Matrix** comparing all watchlist tickers with 1-click chart jump.
- **⚙️ Module 3: Watchlist & Strategy Configuration Editor**
  - Complete `.env` parameters editor: tune breakout lookbacks, volume multipliers, risk budgets, stop-loss %, target %, and trailing stop %.
  - Save directly to `.env` with hot-reload into active runtime.
  - Full **Watchlist Manager**: search, add, delete, and persist Nifty 50 tickers in `watchlist.txt`.

### 4. Run CLI Historical Backtest
```bash
python backtest.py
```
- Fetches historical bars for each symbol in `watchlist.txt`.
- Simulates trades with next-bar open entry.
- Outputs individual logs (`logs/backtest_<SYMBOL>.csv`) and consolidated performance (`logs/backtest_all_trades.csv`).

### 5. Run Live Paper Scanner
```bash
python run_paper.py
```
- Polls Yahoo Finance during NSE market hours (09:15 to 15:30 IST).
- Only processes completed candles to avoid lookahead bias.
- Updates virtual portfolio equity and persists state to `logs/paper_state.json`.

---

## Project Structure
| File | Description |
|---|---|
| [`app_gui.py`](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/app_gui.py) | Modern CustomTkinter desktop GUI application for historical backtesting |
| [`backtest_lab.py`](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/backtest_lab.py) | Analytical backtesting engine (metrics, equity curves, batch testing) |
| [`run_gui.sh`](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/run_gui.sh) | Quick bash launcher for the desktop application |
| [`config.py`](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/config.py) | Dataclass configuration loader and validator with `.env` support |
| [`data_yahoo.py`](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/data_yahoo.py) | Data fetcher with multi-timeframe (`1m`, `3m`, `5m`, `15m`, `30m`, `1d`, `1w`, `1mo`) handling, resampling, and IST normalization |
| [`strategy.py`](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/strategy.py) | Core breakout and volume signal generation logic |
| [`paper_engine.py`](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/paper_engine.py) | Simulated trade execution, position sizing, stop/target tracking, and PnL logging |
| [`run_paper.py`](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/run_paper.py) | Real-time paper scanner loop running during market hours |
| [`backtest.py`](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/backtest.py) | Historical multi-symbol backtesting engine |
| [`use.md`](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/use.md) | In-depth guide explaining how each module functions |
| [`watchlist.txt`](file:///var/www/html/demo/.dev/yahoo_nifty50_paper_trader/watchlist.txt) | NSE ticker list (e.g. `RELIANCE.NS`, `TCS.NS`, etc.) |

---

## Data Notice & Limitations
- **Educational / Simulation Only**: Uses unofficial Yahoo Finance endpoints (`yfinance`). Data may experience delays, missing candles, rate-limits, or revisions.
- **Intraday Caps**: Yahoo Finance limits 15-minute intraday history to ~60 days. Daily data provides longer history (up to 365+ days).
- **Execution Modeling**: Slippage, order queues, liquidity depth, and gap openings are simulated conservatively but cannot replace live exchange conditions.
