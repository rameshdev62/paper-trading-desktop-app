# User Guide & How It Works (`use.md`)

This guide explains how the **Yahoo Nifty 50 Paper Trading & Backtesting System** works internally and how to use it step-by-step.

---

## 1. System Overview & Architecture

The system is a modular, paper-only trading framework built for NSE equities (Nifty 50 constituents with the `.NS` Yahoo suffix). It supports both **15-minute intraday (`15m`)** and **Daily (`1d`)** timeframes.

```
                  ┌──────────────────────┐
                  │    watchlist.txt     │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │    data_yahoo.py     │  ◄── Downloads OHLCV via yfinance
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │     strategy.py      │  ◄── Evaluates Breakout & Volume signals
                  └──────────┬───────────┘
                             │
             ┌───────────────┴───────────────┐
             ▼                               ▼
   ┌───────────────────┐           ┌───────────────────┐
   │   run_paper.py    │           │    backtest.py    │
   │  (Live Paper Loop)│           │ (Historical Test) │
   └─────────┬─────────┘           └─────────┬─────────┘
             │                               │
             ▼                               ▼
   ┌───────────────────┐           ┌───────────────────┐
   │  paper_engine.py  │           │ CSV Trade Logs    │
   │  (Portfolio, PnL) │           │ & Summary Report  │
   └───────────────────┘           └───────────────────┘
```

---

## 2. Core Components

### 1. `config.py` (Configuration)
Loads settings from `.env` with validation:
- **`TIMEFRAME`**: `"1d"` for daily bars or `"15m"` for intraday bars.
- **`PAPER_MODE=true`**: Enforces simulation safety (cannot run real orders).
- **`INITIAL_CAPITAL_INR`**: Starting balance (e.g. ₹100,000).
- **`RISK_PER_TRADE_INR`**: Maximum rupee risk per trade (e.g. ₹100).
- **`MAX_POSITION_VALUE_INR`**: Max capital allocated to any single trade (e.g. ₹10,000).
- **`STOP_LOSS_PCT`**, **`TARGET_PCT`**, **`TRAILING_STOP_PCT`**: Risk parameters (e.g., 1.0% stop, 2.0% target, 0.75% trailing stop).

### 2. `data_yahoo.py` (Data Ingestion)
- Reads symbols from `watchlist.txt`.
- Fetches OHLCV candles using `yfinance`.
- Converts timestamps to Indian Standard Time (`Asia/Kolkata`).
- Filters incomplete bars (avoids lookahead bias) and enforces NSE trading hours (09:15 to 15:30 IST) for intraday data.

### 3. `strategy.py` (Breakout Signal Generation)
Implements a breakout strategy based strictly on **completed prior candles**:
- **BUY Signal**:
  1. Candle Close > Highest High of the previous $N$ bars (`LOOKBACK_BREAKOUT`, default 12).
  2. Candle Volume > $M \times$ Moving Average of the previous $K$ bars (`LOOKBACK_VOLUME`, default 20; `VOLUME_MULTIPLIER`, default 1.2x).
  3. Bullish candle close: Close is in the upper 30% of the candle's high-low range.
- **BEARISH_EXIT Signal**:
  1. Candle Close < Lowest Low of the previous $N$ bars.
  2. Volume > $M \times$ average volume.
  3. Close is in the bottom 30% of the candle's range.
- **WAIT**: If neither condition is met.

### 4. `paper_engine.py` (Virtual Portfolio & Execution)
- Calculates position size dynamically:
  $$\text{Qty} = \min\left(\left\lfloor\frac{\text{Risk}}{\text{Entry} - \text{Stop}}\right\rfloor, \left\lfloor\frac{\text{Max Position Value}}{\text{Entry}}\right\rfloor, \text{Max Shares}\right)$$
- Tracks open positions, stops, trailing stops, and profit targets.
- Uses conservative execution logic: if both stop and target levels are crossed within the same bar, the stop takes priority.
- Writes trade records to `logs/paper_trades.csv` and state to `logs/paper_state.json`.

---

## 3. How `run_paper.py` Works (Live Paper Scanner)

When you execute:
```bash
./.venv/bin/python3 run_paper.py
```
Here is the step-by-step lifecycle:
1. **Initializes**: Loads `Config` and verifies `PAPER_MODE=true`. Sets up logger and initializes `PaperEngine`.
2. **Checks Market Hours**: Runs between 09:15 AM and 03:30 PM IST (Mon–Fri). If market is closed, it pauses and waits.
3. **Scans Watchlist**: Loops over each symbol in `watchlist.txt`:
   - Fetches recent candles via `fetch_candles(symbol, cfg)`.
   - Checks that the latest candle is completed and has not already been processed.
   - Computes breakout and volume indicators via `add_signals(...)`.
4. **Executes Paper Orders**:
   - If `BUY` and capacity allows: calls `engine.buy()`, logs to `logs/paper_trades.csv`, deducts virtual cash.
   - If position is open: calls `engine.mark_candle()` to evaluate if Stop Loss, Trailing Stop, or Target was hit.
   - If `BEARISH_EXIT`: closes open position early.
5. **Updates State**: Writes total portfolio equity, cash, and open positions to `logs/paper_state.json` and sleeps for `POLL_SECONDS` before the next iteration.

---

## 4. How `backtest.py` Works (Historical Testing)

When you execute:
```bash
./.venv/bin/python3 backtest.py
```
1. Loads full historical candles for all watchlist symbols (up to 365 days for `1d`, or up to 59 days for `15m`).
2. Iterates bar-by-bar:
   - Identifies `BUY` signals on completed bars.
   - Simulates entry at the **next bar's Open price** (preventing lookahead bias).
   - Tracks High/Low in subsequent bars to trigger Stop Loss, Trailing Stop, or Profit Target.
3. Generates individual CSVs per stock (`logs/backtest_<SYMBOL>.csv`) and a master summary (`logs/backtest_all_trades.csv`).
4. Prints performance statistics:
   - Total trade count
   - Win rate (%)
   - Gross profit and gross loss
   - Net P&L in INR
   - Profit Factor

---

## 5. How to Use / Step-by-Step Instructions

### Step 1: Environment Setup
```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies if not already done
pip install -r requirements.txt
```

### Step 2: Configure Parameters
Edit `.env` to customize settings:
```ini
# Timeframe: choose "1d" (Daily) or "15m" (15 Minutes)
TIMEFRAME=1d

# Safety
PAPER_MODE=true

# Strategy settings
LOOKBACK_BREAKOUT=12
LOOKBACK_VOLUME=20
VOLUME_MULTIPLIER=1.2

# Risk & Money Management
INITIAL_CAPITAL_INR=100000
RISK_PER_TRADE_INR=100
MAX_POSITION_VALUE_INR=10000
MAX_OPEN_POSITIONS=3
STOP_LOSS_PCT=1.0
TARGET_PCT=2.0
TRAILING_STOP_PCT=0.75
```

### Step 3: Launch Desktop GUI Application (Modules 2, 3, & 4)
```bash
./run_gui.sh
# or
./.venv/bin/python3 app_gui.py
```
This launches the modern dark-mode CustomTkinter desktop application containing all 3 integrated suites:

- **Collapsible Sidebar (Hide/Show Toggle)**:
  - **Click Toggle**: Click the **`◀ Hide Sidebar` / `▶ Show Sidebar`** button in the top navigation header or the **`◀ Hide`** button at the top of the sidebar.
  - **Full-Width Workspace**: When hidden, backtest candlestick charts, equity curves, drawdown views, trade journal, and live positions tables automatically expand to full width.
  - **Quick Restore Banner**: A **`▶ Show Sidebar Parameters`** banner appears in the workspace to reopen the sidebar at any time.
  - **Universal Keyboard Shortcut**: Press **`Ctrl+B`** anytime to toggle the sidebar.

#### 🔴 Module 2: Live Paper Trading Monitor
- **Real-Time Portfolio Tracking**: Live portfolio equity, available cash, invested capital, floating unrealized P&L, and realized P&L.
- **Active Open Positions Table**: Monitor open trades with real-time mark-to-market prices, stop-loss, trailing stop, and profit targets.
- **Manual Order Desk**: Place manual paper BUY orders with price auto-fetch and risk-sized quantity calculation.
- **1-Click Position Exit**: Instantly close any open trade at market price.
- **Continuous Scanner**: Automated background polling loop with market hours enforcement and **⚡ Scan Watchlist Now (Single Pass)** button.
- **Live Terminal & History**: Real-time console showing breakout scanner detections, executions, and `logs/paper_trades.csv` history.

#### 📈 Module 3: Historical Backtesting Lab (Multiple Timeframe Support)
- **Flexible Timeframes**: Backtest across `1m`, `3m`, `5m`, `15m`, `30m`, `60m` (Hourly), `1d` (Daily), `1w` (Weekly), and `1mo` (Monthly) candles.
  - *Native & Resampled*: Yahoo Finance native intervals + custom real-time resampling for `3m` bars from `1m` tick feeds.
- **Selectable Strategy Engines (Dropdown with Multiple Items)**:
  - Users can select from 7 built-in strategy engines directly in the GUI dropdown box:
    1. **`1. R-L-H Pattern (ATR Filtered)`** *(Recommended)*:
       - Combines the 3-candle R-L-H geometry with Average True Range volatility expansion and contraction filtering.
       - **The R candle's TR (True Range) must be greater than the ATR**: $\text{TR}(R) > \text{ATR}$ (impulse expansion).
       - **The L candle's TR must not be greater than the ATR**: $\text{TR}(L) \le \text{ATR}$ (volatility compression / coil).
       - **The H candle's TR must be greater than the ATR**: $\text{TR}(H) > \text{ATR}$ (breakout expansion).
       - Configurable ATR Lookback Period (default: 14 bars).
    2. **`2. R-L-H Pattern (ATR + 20/50 EMA Trend)`**:
       - Dual confluence: R-L-H ATR expansion filtered with **20 EMA and 50 EMA Trend Alignment**:
         - *LONG*: Only allowed when 20 EMA > 50 EMA (Bullish Trend / Golden State).
         - *SHORT*: Only allowed when 20 EMA < 50 EMA (Bearish Trend / Death State).
    3. **`3. 20/50 EMA Golden/Death Cross Trend Strategy`**:
       - Trend detection & crossover strategy based on the 20-period Fast EMA and 50-period Slow EMA:
         - **Golden Cross**: 20 EMA crosses strictly above 50 EMA $\rightarrow$ **BUY / LONG** entry (Stop Loss at 50 EMA level).
         - **Death Cross**: 20 EMA crosses strictly below 50 EMA $\rightarrow$ **SHORT** entry (Stop Loss at 50 EMA level).
         - Dynamic exit on opposing cross or trailing stop.
    4. **`4. R-L-H Pattern (Classic Range)`**:
       - Uses candle size and body progression rules without ATR volatility thresholds.
    5. **`5. 20-Bar Volume Breakout`**:
       - 12-bar price high/low breakout confirmed by 20-bar volume surge (multiplier 1.2x).
    6. **`6. Combined (R-L-H ATR + 20/50 EMA + Breakout)`**:
       - Multi-strategy confluence executing high-conviction signals from R-L-H ATR, 20/50 EMA crosses, and Volume Breakout.
    7. **`7. RLH Support Zone (3-Touch Breakdown SHORT)`**:
       - **Support Zone Geometry**: After a bullish RLH pattern matches and price expands upward, the subsequent pullback support zone is created by the $L$ candle:
         - **Zone Lower Bound**: $\min(L.\text{low}, L.\text{open})$ (Wick bottom)
         - **Zone Upper Bound**: $\max(L.\text{low}, L.\text{open})$ (Body start)
       - **Multi-Touch Retest Mechanism**: As price pulls back to test the support zone and bounces upward, each distinct test is tracked and badge-labeled (`T:1`, `T:2`, `T:3`).
       - **3rd-Touch Breakdown SHORT**: On or after the **3rd test**, when price fails to hold support and closes below the lower wick bound ($\text{Close} < \text{Zone Lower}$), a high-conviction **SHORT Breakdown** signal fires.
       - **Dynamic Stop-Loss**: Placed at the upper bound of the support zone ($\text{Zone Upper}$), which now flips to act as overhead resistance.
       - **Interactive Visuals**: Shaded amber support zone band, touch count badges (`T:1`, `T:2`, `T:3`), and orange breakdown arrows (`⬇ SZ Breakdown`) displayed on the chart.
  - **R-L-H Pattern Details (Long & Short)**:
    - **Pattern Geometry**: 3-candle sequence: `R` (Reference, $t-2$), `L` (Contraction, $t-1$), `H` (Expansion, $t$).
    - **Rule 1 & 2 (Size Progression)**: $\text{Range}(L) < \text{Range}(R) < \text{Range}(H)$.
    - **Rule 6 (Body Progression)**: $\text{Body}(H) > \text{Body}(R)$.
    - **LONG Setup**:
      - $H$ candle is green ($\text{Close} > \text{Open}$).
      - Body of $H$ is entirely above body of $L$ ($\min(H.\text{open}, H.\text{close}) > \max(L.\text{open}, L.\text{close})$).
      - $L$ is preferably red (green also acceptable).
      - **Stop-Loss**: Placed precisely at the low wick of the $L$ candle ($L.\text{low}$).
    - **SHORT Setup**:
      - $H$ candle is red ($\text{Close} < \text{Open}$).
      - Body of $H$ is entirely below body of $L$ ($\max(H.\text{open}, H.\text{close}) < \min(L.\text{open}, L.\text{close})$).
      - $L$ is preferably green (red also acceptable).
      - **Stop-Loss**: Placed precisely at the high wick of the $L$ candle ($L.\text{high}$).
    - **Rule 7 (7-Day Reappearance Cooldown)**: On 4h, Daily (`1d`), and Weekly (`1w`), if the same pattern forms at that price level ($< 2\%$ distance) within 7 days, it is flagged as high-risk / triggers stop-loss to avoid bull/bear traps.
    - **Rule 8 (Target & Color-Flip Exit)**: Trade continues as long as candles remain the same color as entry:
      - *LONG*: Hold through consecutive green candles (and dojis). Exit on the **first red candle**.
      - *SHORT*: Hold through consecutive red candles (and dojis). Exit on the **first green candle**.
      - *Doji*: Do not exit on dojis / zero-body bars; hold and evaluate subsequent candle.
- **Multi-Timeframe Comparative Mode ("Multi-TF Compare")**:
  - Automatically simulates `1m`, `3m`, `5m`, `15m`, `30m`, `1d`, `1w`, and `1mo` side-by-side for any stock.
  - Generates a **Comparative Matrix Table** (`Trades`, `Win Rate %`, `Net P&L`, `ROI %`, `Profit Factor`, `Max DD`, `Reward:Risk`).
  - Automatically highlights the **🏆 Best Performing Timeframe**!
  - Overlays equity curves with vibrant color coding (`1m`: Pink, `3m`: Rose, `5m`: Amber, `15m`: Cyan, `30m`: Sky Blue, `60m`: Purple, `1d`: Emerald, `1w`: Mint, `1mo`: Violet).
  - Double-click any timeframe row in the matrix to immediately load its candlestick chart and trade journal!
- **Multi-Timeframe (MTF) 20/50 EMA Trend Confluence Filter**:
  - Filter lower-timeframe signals with a Higher Timeframe (e.g. Daily `1d`, Weekly `1w`, or Hourly `60m`) 20 EMA & 50 EMA macro trend.
  - *Bullish Confluence*: Higher Timeframe 20 EMA > 50 EMA.
  - *Bearish Confluence*: Higher Timeframe 20 EMA < 50 EMA.
  - Zero-lookahead `pd.merge_asof` ensures trades align strictly with the macro higher timeframe trend.
- **KPI Metrics Dashboard**: Net P&L (₹), Win Rate (%), Profit Factor, Long vs Short breakdown, Total Trades, Max Drawdown (₹ and %), and Reward-to-Risk ratio.
- **Watchlist Scanning & Interactive Stock Chart Inspection ("Scan All Watchlist" Workflow)**:
  - **1-Click Full Watchlist Scan**: In the left sidebar, select **`All Watchlist`** under **Symbol** and click **`▶ Run Backtest`**. The backtest engine scans all stocks in `watchlist.txt`, calculates individual symbol metrics, aggregates portfolio performance, and caches candlestick and trade data in memory.
  - **Choose Any Stock from Chart Toolbar Dropdown**: On the **`🕯️ Price Action & Signals`** tab, use the **`Stock:`** dropdown combo directly on the chart toolbar to choose any scanned stock. The candlestick + volume chart, 20/50 EMAs, and execution markers update instantly with zero waiting time (defaults to **Last 200** candles for optimal clarity and fast rendering).
  - **Double-Click Any Stock in the Symbol Matrix**: On the **`🏢 Symbol Matrix`** tab, double-click any ticker row (or click **`🕯️ View Selected Stock Chart`**) to immediately jump to its candlestick chart and review its exact price action, entry/exit arrows, and 20/50 EMA trends.
- **Interactive Visualizations**: Embedded Matplotlib charts for cumulative Equity Curves, High-Water Marks, Underwater Drawdowns, and Unified Price Action + Volume chart (candlesticks, 20/50 EMAs with green EMA 20 and red EMA 50, execution markers, default **Last 200** candle window with selector `[Last 50, 100, 200, 500, All]`, and bottom volume bars seamlessly integrated on the **same chart** with toolbar toggle).
- **Trade Journal**: Sortable, filterable trade table (Wins, Losses, Longs, Shorts, Color Flips, Stops) with 1-click **Export CSV**.

#### ⚙️ Module 4: Watchlist & Strategy Configuration Editor
- **Strategy & Risk Parameters**: Tune Breakout Lookback, Volume MA Lookback, Volume Multiplier, Initial Capital, Risk Per Trade, Stop Loss %, Target %, and Trailing Stop % directly in the UI.
- **Instant .env Persistence**: Save changes to `.env` with hot-reload into active runtime.
- **Watchlist Manager**: View, search, add (`.NS` format), delete, and save tickers in `watchlist.txt`.

### Step 4: Run CLI Historical Backtest
```bash
./.venv/bin/python3 backtest.py
```
Check `logs/backtest_all_trades.csv` to review all simulated entries, exits, reasons, and P&L.

### Step 5: Run Live Paper Trading Scanner
```bash
./.venv/bin/python3 run_paper.py
```
Leave it running during market hours to paper trade in real time. Press `Ctrl + C` anytime to safely stop.
