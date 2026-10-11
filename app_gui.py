"""Desktop GUI Application: Yahoo Finance Nifty 50 Paper Trader & Strategy Lab.

Implements all 3 core modules:
1. Live Paper Trading Monitor (Live equity, open positions, unrealized/realized PnL, manual orders, start/stop scanner)
2. Historical Backtesting Lab (Multi-timeframe backtests, interactive equity curves, drawdown, price action markers, trade journal)
3. Watchlist & Strategy Configuration Editor (Edit .env parameters, risk rules, and manage watchlist.txt tickers)
"""

import csv
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from zoneinfo import ZoneInfo

import customtkinter as ctk
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
import pandas as pd

from config import Config
from data_yahoo import fetch_candles, load_watchlist
from backtest_lab import (
    calculate_metrics,
    compute_equity_curve,
    run_batch_backtest,
    run_symbol_backtest,
    run_multi_timeframe_comparison,
)
from paper_service import PaperTradingService, is_market_open

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Styling & Color Palette (Dark High-Tech Terminal)
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

C_BG_DARK = "#090d16"         # Main window background
C_CARD_BG = "#131b2e"         # Surface / card background
C_CARD_INNER = "#1a243c"      # Inner elevated containers
C_BORDER = "#25334d"          # Borders and lines
C_ACCENT = "#00d2ff"          # Cyan accent
C_PROFIT = "#00e676"          # Bullish emerald green
C_LOSS = "#ff5252"            # Bearish red
C_AMBER = "#ffb300"           # Warning / Neutral amber
C_TEXT_PRI = "#f8fafc"        # Primary text
C_TEXT_SEC = "#94a3b8"        # Secondary muted text
C_INPUT_BG = "#1e293b"        # Input background


class NiftyPaperTraderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Nifty 50 Paper Trader & Historical Backtesting Lab")
        self.geometry("1420x920")
        self.minsize(1180, 780)
        self.configure(fg_color=C_BG_DARK)

        # Core Services & Config
        self.cfg = self._load_current_config()
        self.paper_service = PaperTradingService(self.cfg)
        self.symbols_list = self._load_symbols_safe()

        # Backtest state
        self.bt_running = False
        self.bt_cancel_requested = False
        self.bt_worker = None
        self.last_bt_result = None

        # Sidebar visibility tracking
        self.bt_sidebar_visible = True
        self.live_sidebar_visible = True
        self.cfg_sidebar_visible = True

        # Build UI Architecture
        self._setup_treeview_styles()
        self._build_top_header()
        self._build_module_views()

        # Keyboard shortcuts (Ctrl+B to toggle sidebar)
        self.bind("<Control-b>", lambda event: self.toggle_sidebar())
        self.bind("<Control-B>", lambda event: self.toggle_sidebar())

        # Start live UI refresh timer (clock & portfolio status)
        self._start_periodic_refresh()

        # Switch to default view
        self._switch_main_module("📈 Historical Backtesting Lab")

    # -------------------------------------------------------------------------
    # Initialization Helpers
    # -------------------------------------------------------------------------
    def _load_current_config(self) -> Config:
        try:
            cfg = Config()
            cfg.validate()
            return cfg
        except Exception as exc:
            log.warning("Config validation warning: %s. Using default safe config.", exc)
            return Config()

    def _load_symbols_safe(self):
        try:
            return load_watchlist("watchlist.txt")
        except Exception:
            return [
                "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
                "BHARTIARTL.NS", "ITC.NS", "SBIN.NS", "LT.NS", "BAJFINANCE.NS"
            ]

    def _setup_treeview_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            "Treeview",
            background=C_CARD_BG,
            foreground=C_TEXT_PRI,
            rowheight=28,
            fieldbackground=C_CARD_BG,
            font=("Segoe UI", 10),
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background="#1e293b",
            foreground="#38bdf8",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padding=5,
        )
        style.map(
            "Treeview",
            background=[("selected", "#0284c7")],
            foreground=[("selected", "#ffffff")],
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#0f172a")],
        )

    # -------------------------------------------------------------------------
    # Master Navigation Header
    # -------------------------------------------------------------------------
    def _build_top_header(self):
        self.header_frame = ctk.CTkFrame(self, fg_color=C_CARD_BG, corner_radius=0, height=70)
        self.header_frame.pack(fill="x", padx=0, pady=0)

        # Brand / Title
        brand_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        brand_frame.pack(side="left", padx=18, pady=10)

        title_lbl = ctk.CTkLabel(
            brand_frame,
            text="⚡ NIFTY 50 PAPER TRADER",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#38bdf8",
        )
        title_lbl.pack(anchor="w")

        sub_lbl = ctk.CTkLabel(
            brand_frame,
            text="Breakout System & Virtual Execution Suite (Yahoo Finance)",
            font=ctk.CTkFont(size=11),
            text_color=C_TEXT_SEC,
        )
        sub_lbl.pack(anchor="w")

        # Sidebar Toggle Button in Header (Click to Hide / Show)
        self.btn_toggle_sidebar = ctk.CTkButton(
            self.header_frame,
            text="◀ Hide Sidebar",
            width=118,
            height=34,
            fg_color="#1e293b",
            hover_color="#334155",
            border_width=1,
            border_color=C_BORDER,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8",
            command=self.toggle_sidebar,
        )
        self.btn_toggle_sidebar.pack(side="left", padx=(6, 12))

        # Center Navigation Tabs (The 3 Modules)
        self.nav_var = ctk.StringVar(value="📈 Historical Backtesting Lab")
        self.nav_seg = ctk.CTkSegmentedButton(
            self.header_frame,
            values=[
                "🔴 Live Paper Trading Monitor",
                "📈 Historical Backtesting Lab",
                "⚙️ Watchlist & Config Editor",
            ],
            variable=self.nav_var,
            command=self._switch_main_module,
            selected_color=C_ACCENT,
            selected_hover_color="#0284c7",
            unselected_color="#1e293b",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
        )
        self.nav_seg.pack(side="left", expand=True, padx=20)

        # Right Status: Market State & Time
        right_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        right_frame.pack(side="right", padx=18, pady=10)

        self.market_badge = ctk.CTkLabel(
            right_frame,
            text="● NSE STATUS",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#064e3b",
            text_color=C_PROFIT,
            corner_radius=6,
            padx=10,
            pady=3,
        )
        self.market_badge.pack(side="right", padx=(8, 0))

        self.clock_lbl = ctk.CTkLabel(
            right_frame,
            text="--:--:-- IST",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C_TEXT_PRI,
        )
        self.clock_lbl.pack(side="right", padx=8)

    def _switch_main_module(self, selected_module):
        if hasattr(self, "nav_var") and self.nav_var.get() != selected_module:
            self.nav_var.set(selected_module)

        self.frame_live.pack_forget()
        self.frame_backtest.pack_forget()
        self.frame_config.pack_forget()

        if "Live Paper" in selected_module:
            self.frame_live.pack(fill="both", expand=True, padx=14, pady=12)
            self._refresh_live_portfolio_ui()
            self._reload_paper_trades_table()
        elif "Backtesting" in selected_module:
            self.frame_backtest.pack(fill="both", expand=True, padx=14, pady=12)
            self._redraw_current_bt_charts()
        elif "Config" in selected_module:
            self.frame_config.pack(fill="both", expand=True, padx=14, pady=12)
            self._reload_config_form_values()
            self._reload_config_watchlist_listbox()

        self._update_sidebar_toggle_ui(selected_module)

    def toggle_sidebar(self):
        """Toggle left sidebar visibility between shown and hidden across views."""
        curr_module = self.nav_var.get()
        if "Backtesting" in curr_module:
            self.bt_sidebar_visible = not self.bt_sidebar_visible
            if self.bt_sidebar_visible:
                if hasattr(self, "bt_show_bar"):
                    self.bt_show_bar.pack_forget()
                self.bt_sidebar.pack(side="left", fill="y", padx=(0, 12), pady=0, before=self.bt_workspace)
            else:
                self.bt_sidebar.pack_forget()
                if hasattr(self, "bt_show_bar"):
                    self.bt_show_bar.pack(fill="x", pady=(0, 8), before=self.bt_kpi_row)
            self._update_sidebar_toggle_ui()
            self.update_idletasks()
            self._redraw_current_bt_charts()

        elif "Live Paper" in curr_module:
            self.live_sidebar_visible = not self.live_sidebar_visible
            if self.live_sidebar_visible:
                if hasattr(self, "live_show_bar"):
                    self.live_show_bar.pack_forget()
                self.live_sidebar.pack(side="left", fill="y", padx=(0, 12), pady=0, before=self.live_workspace)
            else:
                self.live_sidebar.pack_forget()
                if hasattr(self, "live_show_bar"):
                    self.live_show_bar.pack(fill="x", pady=(0, 8), before=self.live_pos_card)
            self._update_sidebar_toggle_ui()
            self.update_idletasks()

        elif "Config" in curr_module:
            self.cfg_sidebar_visible = not self.cfg_sidebar_visible
            if self.cfg_sidebar_visible:
                if hasattr(self, "cfg_show_bar"):
                    self.cfg_show_bar.pack_forget()
                self.cfg_sidebar.pack(side="left", fill="both", expand=True, padx=(0, 10), before=self.cfg_workspace)
            else:
                self.cfg_sidebar.pack_forget()
                if hasattr(self, "cfg_show_bar"):
                    self.cfg_show_bar.pack(fill="x", padx=15, pady=(10, 4), before=self.cfg_head_wl)
            self._update_sidebar_toggle_ui()
            self.update_idletasks()

    def _update_sidebar_toggle_ui(self, module=None):
        """Update toggle button text and styling based on active view's sidebar state."""
        if not hasattr(self, "btn_toggle_sidebar"):
            return
        curr_module = module or (self.nav_var.get() if hasattr(self, "nav_var") else "")
        if "Backtesting" in curr_module:
            is_vis = getattr(self, "bt_sidebar_visible", True)
        elif "Live Paper" in curr_module:
            is_vis = getattr(self, "live_sidebar_visible", True)
        else:
            is_vis = getattr(self, "cfg_sidebar_visible", True)

        if is_vis:
            self.btn_toggle_sidebar.configure(
                text="◀ Hide Sidebar",
                text_color="#38bdf8",
                fg_color="#1e293b",
                hover_color="#334155",
            )
        else:
            self.btn_toggle_sidebar.configure(
                text="▶ Show Sidebar",
                text_color="#ffb300",
                fg_color="#0f172a",
                hover_color="#1e293b",
            )

    def _redraw_current_bt_charts(self):
        """Trigger idle redraw of backtest charts after layout resize."""
        try:
            if hasattr(self, "canvas_bt_equity") and self.canvas_bt_equity:
                self.canvas_bt_equity.draw_idle()
            if hasattr(self, "canvas_bt_sig") and self.canvas_bt_sig:
                self.canvas_bt_sig.draw_idle()
        except Exception as exc:
            log.debug("Error redrawing charts on sidebar toggle: %s", exc)

    def _build_module_views(self):
        # 1. Live Paper Trading Monitor View
        self.frame_live = ctk.CTkFrame(self, fg_color="transparent")
        self._build_live_monitor_view(self.frame_live)

        # 2. Historical Backtesting Lab View
        self.frame_backtest = ctk.CTkFrame(self, fg_color="transparent")
        self._build_backtest_lab_view(self.frame_backtest)

        # 3. Watchlist & Strategy Configuration Editor View
        self.frame_config = ctk.CTkFrame(self, fg_color="transparent")
        self._build_config_editor_view(self.frame_config)

    # =========================================================================
    # MODULE 1: Live Paper Trading Monitor (Option 2)
    # =========================================================================
    def _build_live_monitor_view(self, parent):
        # Top KPI Metric Cards (6 Cards)
        kpi_row = ctk.CTkFrame(parent, fg_color="transparent", height=85)
        kpi_row.pack(fill="x", pady=(0, 10))
        kpi_row.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        self.live_card_eq = self._create_card(kpi_row, 0, "PORTFOLIO EQUITY", "₹ 100,000.00", "Cash + Holdings")
        self.live_card_cash = self._create_card(kpi_row, 1, "AVAILABLE CASH", "₹ 100,000.00", "Liquid Virtual Funds")
        self.live_card_inv = self._create_card(kpi_row, 2, "INVESTED VALUE", "₹ 0.00", "Cost in Open Trades")
        self.live_card_unreal = self._create_card(kpi_row, 3, "UNREALIZED P&L", "₹ 0.00", "0.00% Floating")
        self.live_card_real = self._create_card(kpi_row, 4, "REALIZED P&L", "₹ 0.00", "Closed Trades P&L")
        self.live_card_pos = self._create_card(kpi_row, 5, "ACTIVE POSITIONS", "0", "Max Allowed: 3")

        # Two-column layout: Left Controls, Right Open Positions & Terminal
        live_body = ctk.CTkFrame(parent, fg_color="transparent")
        live_body.pack(fill="both", expand=True)

        # Left Column: Scanner Control & Manual Orders
        self.live_sidebar = ctk.CTkScrollableFrame(live_body, width=340, fg_color=C_CARD_BG, corner_radius=10, border_width=1, border_color=C_BORDER)
        self.live_sidebar.pack(side="left", fill="y", padx=(0, 12), pady=0)
        ctrl_col = self.live_sidebar

        # Scanner Controller Card Header with Hide Button
        live_side_hdr = ctk.CTkFrame(ctrl_col, fg_color="transparent")
        live_side_hdr.pack(fill="x", padx=10, pady=(10, 6))

        sec_scanner = ctk.CTkLabel(live_side_hdr, text="⚡ LIVE SCANNER ENGINE", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8")
        sec_scanner.pack(side="left")

        self.btn_live_side_hide = ctk.CTkButton(
            live_side_hdr,
            text="◀ Hide",
            width=54,
            height=24,
            fg_color="#1e293b",
            hover_color="#334155",
            border_width=1,
            border_color=C_BORDER,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=C_TEXT_SEC,
            command=self.toggle_sidebar,
        )
        self.btn_live_side_hide.pack(side="right")

        self.btn_scanner_toggle = ctk.CTkButton(
            ctrl_col,
            text="▶ START LIVE SCANNER",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=38,
            command=self._toggle_live_scanner,
        )
        self.btn_scanner_toggle.pack(fill="x", padx=10, pady=(0, 8))

        self.btn_scan_now = ctk.CTkButton(
            ctrl_col,
            text="⚡ Scan Watchlist Now (Single Pass)",
            font=ctk.CTkFont(size=11),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=30,
            command=self._run_single_scan_pass,
        )
        self.btn_scan_now.pack(fill="x", padx=10, pady=(0, 8))

        # Scanner Settings
        self.chk_market_hours_var = ctk.BooleanVar(value=True)
        chk_hours = ctk.CTkCheckBox(
            ctrl_col,
            text="Enforce NSE Market Hours (09:15-15:30)",
            variable=self.chk_market_hours_var,
            font=ctk.CTkFont(size=11),
            text_color=C_TEXT_SEC,
        )
        chk_hours.pack(anchor="w", padx=10, pady=(0, 6))

        row_poll = ctk.CTkFrame(ctrl_col, fg_color="transparent")
        row_poll.pack(fill="x", padx=10, pady=(0, 10))
        lbl_poll = ctk.CTkLabel(row_poll, text="Poll Interval:", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        lbl_poll.pack(side="left")

        self.combo_poll = ctk.CTkComboBox(
            row_poll,
            values=["30s", "60s", "90s", "3m", "5m"],
            width=90,
            height=26,
            fg_color=C_INPUT_BG,
            border_color=C_BORDER,
        )
        self.combo_poll.set("90s")
        self.combo_poll.pack(side="right")

        self._add_divider(ctrl_col)

        # Manual Order Desk
        sec_manual = ctk.CTkLabel(ctrl_col, text="💼 MANUAL PAPER EXECUTION", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8")
        sec_manual.pack(anchor="w", padx=10, pady=(10, 6))

        lbl_m_sym = ctk.CTkLabel(ctrl_col, text="Symbol:", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        lbl_m_sym.pack(anchor="w", padx=10)

        self.combo_manual_sym = ctk.CTkComboBox(
            ctrl_col,
            values=self.symbols_list,
            fg_color=C_INPUT_BG,
            border_color=C_BORDER,
        )
        if "RELIANCE.NS" in self.symbols_list:
            self.combo_manual_sym.set("RELIANCE.NS")
        self.combo_manual_sym.pack(fill="x", padx=10, pady=(0, 8))

        # Price row
        row_m_px = ctk.CTkFrame(ctrl_col, fg_color="transparent")
        row_m_px.pack(fill="x", padx=10, pady=(0, 6))
        lbl_m_px = ctk.CTkLabel(row_m_px, text="Price (₹):", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        lbl_m_px.pack(side="left")

        self.entry_manual_px = ctk.CTkEntry(row_m_px, placeholder_text="e.g. 1172.50", width=90, height=26, fg_color=C_INPUT_BG, border_color=C_BORDER)
        self.entry_manual_px.pack(side="right")

        btn_fetch_px = ctk.CTkButton(
            ctrl_col,
            text="🔍 Fetch Latest Market Price",
            font=ctk.CTkFont(size=10),
            fg_color="#1e293b",
            hover_color="#334155",
            height=24,
            command=self._fetch_latest_price_for_manual,
        )
        btn_fetch_px.pack(fill="x", padx=10, pady=(0, 8))

        # Qty row
        row_m_qty = ctk.CTkFrame(ctrl_col, fg_color="transparent")
        row_m_qty.pack(fill="x", padx=10, pady=(0, 10))
        lbl_m_qty = ctk.CTkLabel(row_m_qty, text="Quantity (Shares):", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        lbl_m_qty.pack(side="left")

        self.entry_manual_qty = ctk.CTkEntry(row_m_qty, placeholder_text="Auto or #", width=90, height=26, fg_color=C_INPUT_BG, border_color=C_BORDER)
        self.entry_manual_qty.pack(side="right")

        btn_manual_buy = ctk.CTkButton(
            ctrl_col,
            text="🟢 Execute Paper BUY",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#065f46",
            hover_color="#047857",
            height=34,
            command=self._execute_manual_buy,
        )
        btn_manual_buy.pack(fill="x", padx=10, pady=(0, 12))

        self._add_divider(ctrl_col)

        # Portfolio Reset Action
        sec_maint = ctk.CTkLabel(ctrl_col, text="🛡️ ACCOUNT MAINTENANCE", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8")
        sec_maint.pack(anchor="w", padx=10, pady=(10, 6))

        btn_reset_port = ctk.CTkButton(
            ctrl_col,
            text="↺ Reset Virtual Portfolio (₹100k)",
            font=ctk.CTkFont(size=11),
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            height=30,
            command=self._reset_virtual_portfolio,
        )
        btn_reset_port.pack(fill="x", padx=10, pady=(0, 15))

        # Right Column: Open Positions Table & Tabview (Logs + History)
        self.live_workspace = ctk.CTkFrame(live_body, fg_color="transparent")
        self.live_workspace.pack(side="right", fill="both", expand=True)
        right_panel = self.live_workspace

        # Banner shown when live sidebar is hidden
        self.live_show_bar = ctk.CTkFrame(self.live_workspace, fg_color=C_CARD_BG, corner_radius=8, height=36, border_width=1, border_color=C_BORDER)
        btn_show_live = ctk.CTkButton(
            self.live_show_bar,
            text="▶ Show Controls Sidebar (Ctrl+B)",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=26,
            command=self.toggle_sidebar,
        )
        btn_show_live.pack(side="left", padx=10, pady=5)

        lbl_live_expand_hint = ctk.CTkLabel(
            self.live_show_bar,
            text="Sidebar collapsed — Positions table & Terminal expanded to full width",
            font=ctk.CTkFont(size=11),
            text_color=C_TEXT_SEC,
        )
        lbl_live_expand_hint.pack(side="left", padx=10)

        # Upper Card: Open Positions Table
        self.live_pos_card = ctk.CTkFrame(right_panel, fg_color=C_CARD_BG, corner_radius=10, border_width=1, border_color=C_BORDER)
        self.live_pos_card.pack(fill="x", pady=(0, 10))
        frame_pos = self.live_pos_card

        pos_header = ctk.CTkFrame(frame_pos, fg_color="transparent")
        pos_header.pack(fill="x", padx=12, pady=(10, 6))

        lbl_pos_title = ctk.CTkLabel(pos_header, text="📌 ACTIVE OPEN POSITIONS", font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8")
        lbl_pos_title.pack(side="left")

        btn_close_sel = ctk.CTkButton(
            pos_header,
            text="✕ Close Selected Position",
            font=ctk.CTkFont(size=11),
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            height=26,
            command=self._close_selected_position,
        )
        btn_close_sel.pack(side="right")

        # Treeview for Open Positions
        cols_pos = ("symbol", "qty", "entry", "current", "cost", "curr_val", "unreal_pnl", "pnl_pct", "stop", "target", "trailing")
        self.tree_live_pos = ttk.Treeview(frame_pos, columns=cols_pos, show="headings", height=5, selectmode="browse")

        self.tree_live_pos.heading("symbol", text="Ticker")
        self.tree_live_pos.heading("qty", text="Qty")
        self.tree_live_pos.heading("entry", text="Entry (₹)")
        self.tree_live_pos.heading("current", text="Current (₹)")
        self.tree_live_pos.heading("cost", text="Cost (₹)")
        self.tree_live_pos.heading("curr_val", text="Value (₹)")
        self.tree_live_pos.heading("unreal_pnl", text="Unrealized P&L")
        self.tree_live_pos.heading("pnl_pct", text="Return %")
        self.tree_live_pos.heading("stop", text="Stop Loss (₹)")
        self.tree_live_pos.heading("target", text="Target (₹)")
        self.tree_live_pos.heading("trailing", text="Trailing (₹)")

        self.tree_live_pos.column("symbol", width=110, anchor="center")
        self.tree_live_pos.column("qty", width=55, anchor="center")
        self.tree_live_pos.column("entry", width=85, anchor="e")
        self.tree_live_pos.column("current", width=85, anchor="e")
        self.tree_live_pos.column("cost", width=95, anchor="e")
        self.tree_live_pos.column("curr_val", width=95, anchor="e")
        self.tree_live_pos.column("unreal_pnl", width=110, anchor="e")
        self.tree_live_pos.column("pnl_pct", width=80, anchor="e")
        self.tree_live_pos.column("stop", width=85, anchor="e")
        self.tree_live_pos.column("target", width=85, anchor="e")
        self.tree_live_pos.column("trailing", width=85, anchor="e")

        self.tree_live_pos.tag_configure("win", foreground=C_PROFIT)
        self.tree_live_pos.tag_configure("loss", foreground=C_LOSS)

        self.tree_live_pos.pack(fill="x", padx=12, pady=(0, 10))

        # Lower Tabview: Live Activity Feed & Paper Trades Log
        tabview_live = ctk.CTkTabview(right_panel, fg_color=C_CARD_BG, corner_radius=10)
        tabview_live.pack(fill="both", expand=True)

        tab_feed = tabview_live.add("📡 Live Scanner Feed")
        tab_trades = tabview_live.add("📜 Realized Paper Trades Log")

        # Live Feed Console
        feed_top = ctk.CTkFrame(tab_feed, fg_color="transparent")
        feed_top.pack(fill="x", padx=10, pady=(6, 4))

        lbl_feed_title = ctk.CTkLabel(feed_top, text="Real-Time Breakout Scanner Activity", font=ctk.CTkFont(size=11, weight="bold"), text_color=C_TEXT_SEC)
        lbl_feed_title.pack(side="left")

        btn_clear_feed = ctk.CTkButton(
            feed_top, text="Clear Log", width=70, height=22, font=ctk.CTkFont(size=10),
            fg_color="#1e293b", hover_color="#334155", command=self._clear_scanner_log
        )
        btn_clear_feed.pack(side="right")

        self.txt_live_feed = ctk.CTkTextbox(tab_feed, font=ctk.CTkFont(family="Consolas", size=11), fg_color="#0b101d", text_color="#38bdf8")
        self.txt_live_feed.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Realized Paper Trades Table
        cols_hist = ("timestamp", "symbol", "event", "qty", "price", "stop", "target", "trailing", "pnl", "reason")
        self.tree_paper_hist = ttk.Treeview(tab_trades, columns=cols_hist, show="headings", selectmode="browse")

        self.tree_paper_hist.heading("timestamp", text="Timestamp (IST)")
        self.tree_paper_hist.heading("symbol", text="Ticker")
        self.tree_paper_hist.heading("event", text="Action")
        self.tree_paper_hist.heading("qty", text="Qty")
        self.tree_paper_hist.heading("price", text="Price (₹)")
        self.tree_paper_hist.heading("stop", text="Stop Loss")
        self.tree_paper_hist.heading("target", text="Target")
        self.tree_paper_hist.heading("trailing", text="Trailing")
        self.tree_paper_hist.heading("pnl", text="Realized P&L (₹)")
        self.tree_paper_hist.heading("reason", text="Reason")

        self.tree_paper_hist.column("timestamp", width=170, anchor="center")
        self.tree_paper_hist.column("symbol", width=95, anchor="center")
        self.tree_paper_hist.column("event", width=70, anchor="center")
        self.tree_paper_hist.column("qty", width=50, anchor="center")
        self.tree_paper_hist.column("price", width=85, anchor="e")
        self.tree_paper_hist.column("stop", width=85, anchor="e")
        self.tree_paper_hist.column("target", width=85, anchor="e")
        self.tree_paper_hist.column("trailing", width=85, anchor="e")
        self.tree_paper_hist.column("pnl", width=110, anchor="e")
        self.tree_paper_hist.column("reason", width=120, anchor="center")

        self.tree_paper_hist.tag_configure("win", foreground=C_PROFIT)
        self.tree_paper_hist.tag_configure("loss", foreground=C_LOSS)

        scroll_h = ttk.Scrollbar(tab_trades, orient="vertical", command=self.tree_paper_hist.yview)
        self.tree_paper_hist.configure(yscrollcommand=scroll_h.set)

        self.tree_paper_hist.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll_h.pack(side="right", fill="y", padx=(0, 10), pady=10)

    # -------------------------------------------------------------------------
    # Live Monitor Actions & Callbacks
    # -------------------------------------------------------------------------
    def _toggle_live_scanner(self):
        if self.paper_service.is_scanning:
            self.paper_service.stop_continuous_scanner()
            self.btn_scanner_toggle.configure(text="▶ START LIVE SCANNER", fg_color="#059669", hover_color="#047857")
            self._log_scanner_message("Scanner stopped by user.")
        else:
            poll_map = {"30s": 30, "60s": 60, "90s": 90, "3m": 180, "5m": 300}
            poll_sec = poll_map.get(self.combo_poll.get(), 90)
            enforce = self.chk_market_hours_var.get()

            self.paper_service.start_continuous_scanner(
                symbols=self.symbols_list,
                poll_seconds=poll_sec,
                enforce_market_hours=enforce,
                log_cb=self._log_scanner_message,
                on_pass_complete_cb=lambda: self.after(0, self._on_scanner_cycle_done),
            )
            self.btn_scanner_toggle.configure(text="⏹ STOP SCANNER", fg_color="#dc2626", hover_color="#b91c1c")
            self._log_scanner_message(f"Continuous scanner initiated across {len(self.symbols_list)} tickers.")

    def _run_single_scan_pass(self):
        self._log_scanner_message("Initiating on-demand single scan pass...")
        self.btn_scan_now.configure(state="disabled")

        def worker():
            self.paper_service.scan_watchlist_pass(self.symbols_list, log_cb=self._log_scanner_message)
            self.after(0, lambda: self.btn_scan_now.configure(state="normal"))
            self.after(0, self._on_scanner_cycle_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_scanner_cycle_done(self):
        self._refresh_live_portfolio_ui()
        self._reload_paper_trades_table()

    def _log_scanner_message(self, msg):
        def _append():
            ts = datetime.now(IST).strftime("%H:%M:%S")
            self.txt_live_feed.insert("end", f"[{ts}] {msg}\n")
            self.txt_live_feed.see("end")
        self.after(0, _append)

    def _clear_scanner_log(self):
        self.txt_live_feed.delete("1.0", "end")

    def _fetch_latest_price_for_manual(self):
        sym = self.combo_manual_sym.get().strip()
        if not sym:
            return

        def worker():
            try:
                candles = fetch_candles(sym, self.cfg)
                if not candles.empty:
                    px = float(candles.iloc[-1]["close"])
                    self.after(0, lambda: self.entry_manual_px.delete(0, "end"))
                    self.after(0, lambda: self.entry_manual_px.insert(0, f"{px:.2f}"))
                    self._log_scanner_message(f"Fetched latest market quote for {sym}: ₹{px:.2f}")
                else:
                    self._log_scanner_message(f"Could not fetch candle for {sym}")
            except Exception as exc:
                self._log_scanner_message(f"Fetch error: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _execute_manual_buy(self):
        sym = self.combo_manual_sym.get().strip()
        px_str = self.entry_manual_px.get().strip()
        qty_str = self.entry_manual_qty.get().strip()

        px = float(px_str) if px_str else None
        qty = int(qty_str) if qty_str and qty_str.isdigit() else None

        try:
            success = self.paper_service.manual_buy(sym, price=px, qty=qty)
            if success:
                messagebox.showinfo("Order Executed", f"Paper BUY executed successfully for {sym}!")
                self._refresh_live_portfolio_ui()
                self._reload_paper_trades_table()
                self._log_scanner_message(f"Manual BUY filled for {sym}")
            else:
                messagebox.showwarning("Order Skipped", f"Could not fill order for {sym} (Check cash or limits).")
        except Exception as exc:
            messagebox.showerror("Execution Error", str(exc))

    def _close_selected_position(self):
        sel = self.tree_live_pos.selection()
        if not sel:
            messagebox.showinfo("Select Position", "Please select an open position to close.")
            return

        item = self.tree_live_pos.item(sel[0])
        sym = item["values"][0]

        confirm = messagebox.askyesno("Confirm Exit", f"Are you sure you want to close position in {sym}?")
        if not confirm:
            return

        try:
            success = self.paper_service.manual_close(sym)
            if success:
                self._refresh_live_portfolio_ui()
                self._reload_paper_trades_table()
                self._log_scanner_message(f"Manual position closed: {sym}")
            else:
                messagebox.showwarning("Error", f"Failed to close position in {sym}")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _reset_virtual_portfolio(self):
        confirm = messagebox.askyesno(
            "Reset Portfolio",
            "Are you sure you want to reset your virtual portfolio?\nThis will clear open positions and restore ₹100,000 cash balance."
        )
        if not confirm:
            return

        self.paper_service.reset_portfolio()
        self._refresh_live_portfolio_ui()
        self._log_scanner_message("Virtual portfolio reset to initial cash balance.")

    def _refresh_live_portfolio_ui(self):
        summary = self.paper_service.get_portfolio_summary()

        self.live_card_eq["val"].configure(text=f"₹ {summary['equity']:,.2f}")
        self.live_card_cash["val"].configure(text=f"₹ {summary['cash']:,.2f}")
        self.live_card_inv["val"].configure(text=f"₹ {summary['invested']:,.2f}")

        unreal = summary["unrealized_pnl"]
        unreal_col = C_PROFIT if unreal > 0 else (C_LOSS if unreal < 0 else C_TEXT_PRI)
        sign = "+" if unreal > 0 else ""
        self.live_card_unreal["val"].configure(text=f"{sign}₹ {unreal:,.2f}", text_color=unreal_col)

        real = summary["realized_pnl"]
        real_col = C_PROFIT if real > 0 else (C_LOSS if real < 0 else C_TEXT_PRI)
        sign_r = "+" if real > 0 else ""
        self.live_card_real["val"].configure(text=f"{sign_r}₹ {real:,.2f}", text_color=real_col)

        self.live_card_pos["val"].configure(text=str(summary["positions_count"]))

        # Populate Positions Treeview
        for item in self.tree_live_pos.get_children():
            self.tree_live_pos.delete(item)

        for p in summary["positions"]:
            pnl = p["unrealized_pnl"]
            tag = "win" if pnl > 0 else ("loss" if pnl < 0 else "")
            p_sign = "+" if pnl > 0 else ""
            self.tree_live_pos.insert(
                "",
                "end",
                values=(
                    p["symbol"],
                    p["qty"],
                    f"₹ {p['entry']:.2f}",
                    f"₹ {p['current']:.2f}",
                    f"₹ {p['cost']:.2f}",
                    f"₹ {p['current_value']:.2f}",
                    f"{p_sign}₹ {pnl:.2f}",
                    f"{p_sign}{p['unrealized_pnl_pct']:.2f}%",
                    f"₹ {p['stop']:.2f}",
                    f"₹ {p['target']:.2f}",
                    f"₹ {p['trailing_stop']:.2f}",
                ),
                tags=(tag,),
            )

    def _reload_paper_trades_table(self):
        for item in self.tree_paper_hist.get_children():
            self.tree_paper_hist.delete(item)

        trades_path = Path("logs/paper_trades.csv")
        if not trades_path.exists():
            return

        try:
            df = pd.read_csv(trades_path)
            if df.empty:
                return

            for _, r in df.iterrows():
                pnl_val = r.get("pnl_inr", "")
                tag = ""
                pnl_str = ""
                if pd.notna(pnl_val) and str(pnl_val).strip():
                    try:
                        pnl_f = float(pnl_val)
                        tag = "win" if pnl_f > 0 else ("loss" if pnl_f < 0 else "")
                        pnl_str = f"{'+' if pnl_f > 0 else ''}₹ {pnl_f:.2f}"
                    except Exception:
                        pnl_str = str(pnl_val)

                self.tree_paper_hist.insert(
                    "",
                    "end",
                    values=(
                        str(r.get("timestamp", "")).split(".")[0],
                        r.get("symbol", ""),
                        r.get("event", ""),
                        r.get("qty", ""),
                        f"₹ {float(r['price']):.2f}" if pd.notna(r.get("price")) else "",
                        f"₹ {float(r['stop_loss']):.2f}" if pd.notna(r.get("stop_loss")) and str(r.get("stop_loss")).strip() else "",
                        f"₹ {float(r['target']):.2f}" if pd.notna(r.get("target")) and str(r.get("target")).strip() else "",
                        f"₹ {float(r['trailing_stop']):.2f}" if pd.notna(r.get("trailing_stop")) and str(r.get("trailing_stop")).strip() else "",
                        pnl_str,
                        r.get("reason", ""),
                    ),
                    tags=(tag,),
                )
        except Exception as exc:
            log.warning("Could not load paper trades table: %s", exc)

    # =========================================================================
    # MODULE 2: Historical Backtesting Lab (Option 3)
    # =========================================================================
    def _build_backtest_lab_view(self, parent):
        # 1. Left Sidebar for Backtest parameters
        self.bt_sidebar = ctk.CTkScrollableFrame(parent, width=320, fg_color=C_CARD_BG, corner_radius=10, border_width=1, border_color=C_BORDER)
        self.bt_sidebar.pack(side="left", fill="y", padx=(0, 12), pady=0)

        # Target Section Header with Hide Button
        bt_side_hdr = ctk.CTkFrame(self.bt_sidebar, fg_color="transparent")
        bt_side_hdr.pack(fill="x", padx=10, pady=(10, 6))

        sec_target = ctk.CTkLabel(bt_side_hdr, text="🎯 BACKTEST TARGET", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8")
        sec_target.pack(side="left")

        self.btn_bt_side_hide = ctk.CTkButton(
            bt_side_hdr,
            text="◀ Hide",
            width=54,
            height=24,
            fg_color="#1e293b",
            hover_color="#334155",
            border_width=1,
            border_color=C_BORDER,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=C_TEXT_SEC,
            command=self.toggle_sidebar,
        )
        self.btn_bt_side_hide.pack(side="right")

        self.bt_mode_var = ctk.StringVar(value="Single Symbol")
        mode_seg = ctk.CTkSegmentedButton(
            self.bt_sidebar,
            values=["Single Symbol", "Multi-TF Compare", "All Watchlist"],
            variable=self.bt_mode_var,
            command=self._on_bt_mode_change,
            selected_color=C_ACCENT,
            height=30,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        mode_seg.pack(fill="x", padx=10, pady=(0, 8))

        self.bt_sym_lbl = ctk.CTkLabel(self.bt_sidebar, text="Symbol:", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        self.bt_sym_lbl.pack(anchor="w", padx=10)

        self.bt_combo_sym = ctk.CTkComboBox(
            self.bt_sidebar,
            values=self.symbols_list,
            fg_color=C_INPUT_BG,
            border_color=C_BORDER,
            command=self._on_sidebar_sym_change,
        )
        if "RELIANCE.NS" in self.symbols_list:
            self.bt_combo_sym.set("RELIANCE.NS")
        self.bt_combo_sym.pack(fill="x", padx=10, pady=(0, 8))

        tf_lbl = ctk.CTkLabel(self.bt_sidebar, text="Execution Timeframe:", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        tf_lbl.pack(anchor="w", padx=10)

        self.bt_tf_var = ctk.StringVar(value="15m")
        self.bt_combo_tf = ctk.CTkComboBox(
            self.bt_sidebar,
            values=[
                "1m (1 Min)",
                "3m (3 Min)",
                "5m (5 Min)",
                "15m (15 Min)",
                "30m (30 Min)",
                "60m (Hourly)",
                "1d (Daily)",
                "1w (Weekly)",
                "1mo (Monthly)",
            ],
            variable=self.bt_tf_var,
            fg_color=C_INPUT_BG,
            border_color=C_BORDER,
        )
        self.bt_combo_tf.set("15m")
        self.bt_combo_tf.pack(fill="x", padx=10, pady=(0, 6))

        # Run & Stop Buttons (positioned directly under Timeframe dropdown)
        self.btn_bt_run = ctk.CTkButton(
            self.bt_sidebar, text="▶ RUN BACKTEST", font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#0284c7", hover_color="#0369a1", height=40, command=self.start_backtest
        )
        self.btn_bt_run.pack(fill="x", padx=10, pady=(4, 4))

        self.btn_bt_stop = ctk.CTkButton(
            self.bt_sidebar, text="⏹ Cancel Run", font=ctk.CTkFont(size=12),
            fg_color="#7f1d1d", hover_color="#991b1b", height=30, state="disabled", command=self.stop_backtest
        )
        self.btn_bt_stop.pack(fill="x", padx=10, pady=(0, 10))

        self._add_divider(self.bt_sidebar)

        # Multi-Timeframe Trend Confluence Filter Section
        sec_mtf = ctk.CTkLabel(self.bt_sidebar, text="🌐 MTF TREND CONFLUENCE", font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8")
        sec_mtf.pack(anchor="w", padx=10, pady=(4, 4))

        self.bt_chk_mtf_var = ctk.BooleanVar(value=False)
        chk_mtf = ctk.CTkCheckBox(
            self.bt_sidebar,
            text="Filter with Higher TF (20/50 EMA Trend)",
            variable=self.bt_chk_mtf_var,
            font=ctk.CTkFont(size=11),
            text_color=C_TEXT_SEC,
        )
        chk_mtf.pack(anchor="w", padx=10, pady=(0, 4))

        row_htf = ctk.CTkFrame(self.bt_sidebar, fg_color="transparent")
        row_htf.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(row_htf, text="Macro TF:", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC).pack(side="left")
        self.bt_combo_htf = ctk.CTkComboBox(
            row_htf,
            values=["1d (Daily)", "1w (Weekly)", "60m (Hourly)"],
            width=110,
            height=26,
            fg_color=C_INPUT_BG,
            border_color=C_BORDER,
        )
        self.bt_combo_htf.set("1d (Daily)")
        self.bt_combo_htf.pack(side="right")

        self._add_divider(self.bt_sidebar)

        # Strategy Parameters Section
        sec_strat = ctk.CTkLabel(self.bt_sidebar, text="⚙️ STRATEGY ENGINE & RULES", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8")
        sec_strat.pack(anchor="w", padx=10, pady=(10, 6))

        strat_lbl = ctk.CTkLabel(self.bt_sidebar, text="Active Strategy:", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        strat_lbl.pack(anchor="w", padx=10)

        self.bt_combo_strat = ctk.CTkComboBox(
            self.bt_sidebar,
            values=[
                "1. R-L-H Pattern (ATR Filtered)",
                "2. R-L-H Pattern (ATR + 20/50 EMA Trend)",
                "3. 20/50 EMA Golden/Death Cross",
                "4. R-L-H Pattern (Classic Range)",
                "5. 20-Bar Volume Breakout",
                "6. Combined (R-L-H ATR + 20/50 EMA + Breakout)",
                "7. RLH Support Zone (3-Touch Breakdown SHORT)",
            ],
            fg_color=C_INPUT_BG,
            border_color=C_BORDER,
        )
        self.bt_combo_strat.set("1. R-L-H Pattern (ATR Filtered)")
        self.bt_combo_strat.pack(fill="x", padx=10, pady=(0, 6))

        row_side = ctk.CTkFrame(self.bt_sidebar, fg_color="transparent")
        row_side.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(row_side, text="Trade Direction:", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC).pack(side="left")
        self.bt_combo_side = ctk.CTkComboBox(
            row_side,
            values=["Both (Long & Short)", "Long Only", "Short Only"],
            width=140,
            height=26,
            fg_color=C_INPUT_BG,
            border_color=C_BORDER,
        )
        self.bt_combo_side.set("Both (Long & Short)")
        self.bt_combo_side.pack(side="right")

        self.spin_bt_atr = self._create_spin_row(self.bt_sidebar, "ATR Period (bars):", 14)
        self.spin_bt_ema_f = self._create_spin_row(self.bt_sidebar, "Fast EMA Period (bars):", 20)
        self.spin_bt_ema_s = self._create_spin_row(self.bt_sidebar, "Slow EMA Period (bars):", 50)
        self.spin_bt_bk = self._create_spin_row(self.bt_sidebar, "Breakout Lookback (bars):", 12)
        self.spin_bt_v_lb = self._create_spin_row(self.bt_sidebar, "Volume MA Lookback (bars):", 20)
        self.spin_bt_v_m = self._create_spin_row(self.bt_sidebar, "Volume Multiplier (x):", 1.2)

        self._add_divider(self.bt_sidebar)

        # Risk Management Section
        sec_risk = ctk.CTkLabel(self.bt_sidebar, text="🛡️ RISK SIZING", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8")
        sec_risk.pack(anchor="w", padx=10, pady=(10, 6))

        self.spin_bt_cap = self._create_spin_row(self.bt_sidebar, "Initial Capital (₹):", 100000)
        self.spin_bt_risk = self._create_spin_row(self.bt_sidebar, "Risk Per Trade (₹):", 100)
        self.spin_bt_max_v = self._create_spin_row(self.bt_sidebar, "Max Position Value (₹):", 10000)
        self.spin_bt_sl = self._create_spin_row(self.bt_sidebar, "Stop Loss (%):", 1.0)
        self.spin_bt_tgt = self._create_spin_row(self.bt_sidebar, "Profit Target (%):", 2.0)
        self.spin_bt_trail = self._create_spin_row(self.bt_sidebar, "Trailing Stop (%):", 0.75)



        # 2. Right Workspace for Backtest Results
        self.bt_workspace = ctk.CTkFrame(parent, fg_color="transparent")
        self.bt_workspace.pack(side="right", fill="both", expand=True)

        # Collapsed banner (shown only when backtest sidebar is hidden)
        self.bt_show_bar = ctk.CTkFrame(self.bt_workspace, fg_color=C_CARD_BG, corner_radius=8, height=36, border_width=1, border_color=C_BORDER)
        btn_show_bt = ctk.CTkButton(
            self.bt_show_bar,
            text="▶ Show Sidebar Parameters (Ctrl+B)",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=26,
            command=self.toggle_sidebar,
        )
        btn_show_bt.pack(side="left", padx=10, pady=5)

        lbl_bt_expand_hint = ctk.CTkLabel(
            self.bt_show_bar,
            text="Sidebar collapsed — Chart & matrix views expanded to full width",
            font=ctk.CTkFont(size=11),
            text_color=C_TEXT_SEC,
        )
        lbl_bt_expand_hint.pack(side="left", padx=10)

        # 6 KPI Cards for Backtest
        self.bt_kpi_row = ctk.CTkFrame(self.bt_workspace, fg_color="transparent", height=85)
        self.bt_kpi_row.pack(fill="x", pady=(0, 10))
        self.bt_kpi_row.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)
        bt_kpi_row = self.bt_kpi_row

        self.bt_card_pnl = self._create_card(bt_kpi_row, 0, "NET P&L", "₹ 0.00", "0.00% ROI")
        self.bt_card_wr = self._create_card(bt_kpi_row, 1, "WIN RATE", "0.0%", "0 W / 0 L")
        self.bt_card_pf = self._create_card(bt_kpi_row, 2, "PROFIT FACTOR", "0.00", "Gross Profit / Loss")
        self.bt_card_trades = self._create_card(bt_kpi_row, 3, "TOTAL TRADES", "0", "Avg PnL: ₹ 0.00")
        self.bt_card_dd = self._create_card(bt_kpi_row, 4, "MAX DRAWDOWN", "₹ 0.00", "0.00% Peak DD")
        self.bt_card_rr = self._create_card(bt_kpi_row, 5, "REWARD : RISK", "0.00", "Avg Win / Avg Loss")

        # Multi-tab view for Backtesting
        self.bt_tabview = ctk.CTkTabview(self.bt_workspace, fg_color=C_CARD_BG, corner_radius=10)
        self.bt_tabview.pack(fill="both", expand=True)

        tab_eq = self.bt_tabview.add("📈 Equity & Drawdown")
        tab_sig = self.bt_tabview.add("🕯️ Price Action & Signals")
        tab_jrnl = self.bt_tabview.add("📋 Trade Journal")
        tab_mat = self.bt_tabview.add("🏢 Symbol Matrix")

        # Tab 1: Equity & Drawdown Chart
        self.fig_bt_equity = Figure(figsize=(8, 5), facecolor=C_CARD_BG, dpi=100)
        self.ax_bt_eq = self.fig_bt_equity.add_subplot(211)
        self.ax_bt_dd = self.fig_bt_equity.add_subplot(212, sharex=self.ax_bt_eq)
        self.fig_bt_equity.subplots_adjust(hspace=0.25, left=0.08, right=0.96, top=0.93, bottom=0.1)

        self.canvas_bt_equity = FigureCanvasTkAgg(self.fig_bt_equity, master=tab_eq)
        self.canvas_bt_equity.get_tk_widget().pack(fill="both", expand=True)

        # Tab 2: Signals Chart — Filter toolbar
        sig_toolbar = ctk.CTkFrame(tab_sig, fg_color=C_CARD_INNER, corner_radius=8, height=40)
        sig_toolbar.pack(fill="x", padx=8, pady=(6, 4))
        sig_toolbar.pack_propagate(False)

        ctk.CTkLabel(sig_toolbar, text="Stock:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8").pack(side="left", padx=(10, 4))
        self.sig_stock_var = ctk.StringVar(value=self.symbols_list[0] if self.symbols_list else "RELIANCE.NS")
        self.combo_sig_stock = ctk.CTkComboBox(
            sig_toolbar,
            values=self.symbols_list,
            variable=self.sig_stock_var,
            command=self._on_sig_stock_change,
            width=145, height=26,
            fg_color=C_INPUT_BG, border_color=C_BORDER,
            font=ctk.CTkFont(size=11),
            state="readonly",
        )
        self.combo_sig_stock.pack(side="left", padx=4)
        self.combo_sig_stock.bind("<Return>", lambda e: self.load_stock_chart(self.combo_sig_stock.get()))

        ctk.CTkLabel(sig_toolbar, text="│", text_color=C_BORDER, font=ctk.CTkFont(size=16)).pack(side="left", padx=5)

        ctk.CTkLabel(sig_toolbar, text="Filter:", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC).pack(side="left", padx=(2, 4))
        self.sig_chart_filter_var = ctk.StringVar(value="All Signals")
        self.combo_sig_filter = ctk.CTkComboBox(
            sig_toolbar,
            values=["All Signals", "Long Entries Only", "Short Entries Only", "Winning Trades", "Losing Trades", "Pattern Markers Only"],
            variable=self.sig_chart_filter_var,
            command=self._on_sig_chart_filter_change,
            width=175, height=26,
            fg_color=C_INPUT_BG, border_color=C_BORDER,
            font=ctk.CTkFont(size=11),
        )
        self.combo_sig_filter.pack(side="left", padx=4)

        ctk.CTkLabel(sig_toolbar, text="│", text_color=C_BORDER, font=ctk.CTkFont(size=16)).pack(side="left", padx=6)
        ctk.CTkLabel(sig_toolbar, text="Candles:", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC).pack(side="left", padx=(0, 4))
        self.sig_candle_count_var = ctk.StringVar(value="Last 200")
        self.combo_sig_candles = ctk.CTkComboBox(
            sig_toolbar,
            values=["Last 200", "Last 50", "Last 100", "Last 500", "All"],
            variable=self.sig_candle_count_var,
            command=self._on_sig_chart_filter_change,
            width=100, height=26,
            fg_color=C_INPUT_BG, border_color=C_BORDER,
            font=ctk.CTkFont(size=11),
        )
        self.combo_sig_candles.pack(side="left", padx=4)

        ctk.CTkLabel(sig_toolbar, text="│", text_color=C_BORDER, font=ctk.CTkFont(size=16)).pack(side="left", padx=6)
        self.chk_sig_ema_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(sig_toolbar, text="20/50 EMA", variable=self.chk_sig_ema_var,
                        command=self._on_sig_chart_filter_change,
                        font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC,
                        checkbox_width=16, checkbox_height=16).pack(side="left", padx=4)
        self.chk_sig_crosses_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(sig_toolbar, text="Crosses", variable=self.chk_sig_crosses_var,
                        command=self._on_sig_chart_filter_change,
                        font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC,
                        checkbox_width=16, checkbox_height=16).pack(side="left", padx=4)
        self.chk_sig_vol_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(sig_toolbar, text="Volume", variable=self.chk_sig_vol_var,
                        command=self._on_sig_chart_filter_change,
                        font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC,
                        checkbox_width=16, checkbox_height=16).pack(side="left", padx=4)

        self.lbl_sig_trade_count = ctk.CTkLabel(
            sig_toolbar, text="0 signals", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC
        )
        self.lbl_sig_trade_count.pack(side="right", padx=12)

        # Tab 2: Signals Chart — Canvas (Unified Candlestick + Volume on Same Chart)
        self.fig_bt_sig = Figure(figsize=(8, 5), facecolor=C_CARD_BG, dpi=100)
        self.ax_bt_price = self.fig_bt_sig.add_subplot(111)
        self.ax_bt_vol = self.ax_bt_price.twinx()
        self.fig_bt_sig.subplots_adjust(left=0.08, right=0.97, top=0.93, bottom=0.08)

        self.canvas_bt_sig = FigureCanvasTkAgg(self.fig_bt_sig, master=tab_sig)
        self.canvas_bt_sig.get_tk_widget().pack(fill="both", expand=True)

        # Storage for re-render on filter change
        self._sig_candles_cache: pd.DataFrame = pd.DataFrame()
        self._sig_trades_cache: pd.DataFrame = pd.DataFrame()
        self._sig_symbol_cache: str = ""

        # Tab 3: Trade Journal
        t_bar = ctk.CTkFrame(tab_jrnl, fg_color="transparent")
        t_bar.pack(fill="x", padx=10, pady=(6, 6))

        ctk.CTkLabel(t_bar, text="Filter:", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC).pack(side="left", padx=(0, 6))
        self.bt_filter_var = ctk.StringVar(value="All Trades")
        self.combo_bt_filter = ctk.CTkComboBox(
            t_bar, values=["All Trades", "Winning Trades Only", "Losing Trades Only", "LONG Only", "SHORT Only", "Color Flip Exits", "Stop Loss Exits"],
            variable=self.bt_filter_var, command=self._apply_bt_filter, width=170, height=26, fg_color=C_INPUT_BG, border_color=C_BORDER
        )
        self.combo_bt_filter.pack(side="left")

        ctk.CTkButton(t_bar, text="💾 Export CSV", width=110, height=26, font=ctk.CTkFont(size=11), fg_color="#0284c7", command=self.export_backtest_csv).pack(side="right")
        self.lbl_bt_count = ctk.CTkLabel(t_bar, text="0 trades", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        self.lbl_bt_count.pack(side="right", padx=15)

        cols_bt_j = ("num", "symbol", "side", "entry_time", "exit_time", "entry", "exit", "qty", "pnl", "ret", "reason")
        self.tree_bt_trades = ttk.Treeview(tab_jrnl, columns=cols_bt_j, show="headings", selectmode="browse")
        self.tree_bt_trades.heading("num", text="#")
        self.tree_bt_trades.heading("symbol", text="Symbol")
        self.tree_bt_trades.heading("side", text="Side")
        self.tree_bt_trades.heading("entry_time", text="Entry Time")
        self.tree_bt_trades.heading("exit_time", text="Exit Time")
        self.tree_bt_trades.heading("entry", text="Entry (₹)")
        self.tree_bt_trades.heading("exit", text="Exit (₹)")
        self.tree_bt_trades.heading("qty", text="Qty")
        self.tree_bt_trades.heading("pnl", text="P&L (₹)")
        self.tree_bt_trades.heading("ret", text="Return %")
        self.tree_bt_trades.heading("reason", text="Exit Reason")

        self.tree_bt_trades.column("num", width=35, anchor="center")
        self.tree_bt_trades.column("symbol", width=90, anchor="center")
        self.tree_bt_trades.column("side", width=65, anchor="center")
        self.tree_bt_trades.column("entry_time", width=150, anchor="center")
        self.tree_bt_trades.column("exit_time", width=150, anchor="center")
        self.tree_bt_trades.column("entry", width=85, anchor="e")
        self.tree_bt_trades.column("exit", width=85, anchor="e")
        self.tree_bt_trades.column("qty", width=45, anchor="center")
        self.tree_bt_trades.column("pnl", width=95, anchor="e")
        self.tree_bt_trades.column("ret", width=75, anchor="e")
        self.tree_bt_trades.column("reason", width=130, anchor="center")

        self.tree_bt_trades.tag_configure("win", foreground=C_PROFIT)
        self.tree_bt_trades.tag_configure("loss", foreground=C_LOSS)

        scroll_j = ttk.Scrollbar(tab_jrnl, orient="vertical", command=self.tree_bt_trades.yview)
        self.tree_bt_trades.configure(yscrollcommand=scroll_j.set)
        self.tree_bt_trades.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        scroll_j.pack(side="right", fill="y", padx=(0, 10), pady=(0, 10))

        # Tab 4: Symbol Matrix
        mat_top = ctk.CTkFrame(tab_mat, fg_color="transparent")
        mat_top.pack(fill="x", padx=10, pady=(6, 4))

        lbl_mat_hint = ctk.CTkLabel(
            mat_top,
            text="💡 Tip: Double-click any stock row to view its Candlestick + Volume Chart & Signals",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8",
        )
        lbl_mat_hint.pack(side="left")

        btn_view_mat_stock = ctk.CTkButton(
            mat_top,
            text="🕯️ View Selected Stock Chart",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=26,
            command=self._on_click_view_matrix_stock,
        )
        btn_view_mat_stock.pack(side="right")

        cols_mat = ("symbol", "trades", "win_rate", "net_pnl", "pf", "max_dd", "status")
        self.tree_bt_matrix = ttk.Treeview(tab_mat, columns=cols_mat, show="headings", selectmode="browse")
        self.tree_bt_matrix.heading("symbol", text="Ticker")
        self.tree_bt_matrix.heading("trades", text="Trades")
        self.tree_bt_matrix.heading("win_rate", text="Win Rate %")
        self.tree_bt_matrix.heading("net_pnl", text="Net P&L (₹)")
        self.tree_bt_matrix.heading("pf", text="Profit Factor")
        self.tree_bt_matrix.heading("max_dd", text="Max Drawdown (₹)")
        self.tree_bt_matrix.heading("status", text="Status")

        self.tree_bt_matrix.column("symbol", width=120, anchor="center")
        self.tree_bt_matrix.column("trades", width=70, anchor="center")
        self.tree_bt_matrix.column("win_rate", width=100, anchor="center")
        self.tree_bt_matrix.column("net_pnl", width=120, anchor="e")
        self.tree_bt_matrix.column("pf", width=100, anchor="center")
        self.tree_bt_matrix.column("max_dd", width=120, anchor="e")
        self.tree_bt_matrix.column("status", width=140, anchor="center")

        self.tree_bt_matrix.tag_configure("win", foreground=C_PROFIT)
        self.tree_bt_matrix.tag_configure("loss", foreground=C_LOSS)

        self.tree_bt_matrix.bind("<Double-1>", self._on_select_matrix_symbol_row)
        self.tree_bt_matrix.bind("<Return>", self._on_select_matrix_symbol_row)

        scroll_m = ttk.Scrollbar(tab_mat, orient="vertical", command=self.tree_bt_matrix.yview)
        self.tree_bt_matrix.configure(yscrollcommand=scroll_m.set)
        self.tree_bt_matrix.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        scroll_m.pack(side="right", fill="y", padx=(0, 10), pady=(0, 10))

        # Tab 5: Multi-Timeframe Comparison
        tab_mtf = self.bt_tabview.add("📊 Multi-TF Compare")

        mtf_top = ctk.CTkFrame(tab_mtf, fg_color="transparent")
        mtf_top.pack(fill="x", padx=10, pady=(8, 6))

        self.lbl_mtf_best_badge = ctk.CTkLabel(
            mtf_top,
            text="🏆 Multi-Timeframe Matrix (1m, 3m, 5m, 15m, 30m, 1d, 1w, 1mo) — Double-click any row to view its charts",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8",
        )
        self.lbl_mtf_best_badge.pack(side="left")

        cols_mtf = ("timeframe", "trades", "win_rate", "net_pnl", "net_roi", "pf", "max_dd", "avg_trade", "rr")
        self.tree_bt_mtf = ttk.Treeview(tab_mtf, columns=cols_mtf, show="headings", selectmode="browse")
        self.tree_bt_mtf.heading("timeframe", text="Timeframe")
        self.tree_bt_mtf.heading("trades", text="Total Trades")
        self.tree_bt_mtf.heading("win_rate", text="Win Rate %")
        self.tree_bt_mtf.heading("net_pnl", text="Net P&L (₹)")
        self.tree_bt_mtf.heading("net_roi", text="ROI %")
        self.tree_bt_mtf.heading("pf", text="Profit Factor")
        self.tree_bt_mtf.heading("max_dd", text="Max Drawdown (₹)")
        self.tree_bt_mtf.heading("avg_trade", text="Avg Trade (₹)")
        self.tree_bt_mtf.heading("rr", text="Reward:Risk")

        self.tree_bt_mtf.column("timeframe", width=110, anchor="center")
        self.tree_bt_mtf.column("trades", width=90, anchor="center")
        self.tree_bt_mtf.column("win_rate", width=100, anchor="center")
        self.tree_bt_mtf.column("net_pnl", width=120, anchor="e")
        self.tree_bt_mtf.column("net_roi", width=90, anchor="e")
        self.tree_bt_mtf.column("pf", width=100, anchor="center")
        self.tree_bt_mtf.column("max_dd", width=120, anchor="e")
        self.tree_bt_mtf.column("avg_trade", width=110, anchor="e")
        self.tree_bt_mtf.column("rr", width=95, anchor="center")

        self.tree_bt_mtf.tag_configure("win", foreground=C_PROFIT)
        self.tree_bt_mtf.tag_configure("loss", foreground=C_LOSS)
        self.tree_bt_mtf.tag_configure("best", foreground="#38bdf8")

        scroll_mtf = ttk.Scrollbar(tab_mtf, orient="vertical", command=self.tree_bt_mtf.yview)
        self.tree_bt_mtf.configure(yscrollcommand=scroll_mtf.set)
        self.tree_bt_mtf.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll_mtf.pack(side="right", fill="y", padx=(0, 10), pady=10)
        self.tree_bt_mtf.bind("<Double-1>", self._on_select_mtf_row)

        # Draw empty template plots
        self._draw_empty_backtest_charts()

    # Backtest Execution Methods
    def _on_bt_mode_change(self, val):
        if "Watchlist" in val or "Portfolio" in val:
            self.bt_combo_sym.configure(state="disabled")
            self.bt_sym_lbl.configure(text_color="#64748b")
            self.bt_combo_tf.configure(state="normal")
        elif "Multi-TF" in val:
            self.bt_combo_sym.configure(state="normal")
            self.bt_sym_lbl.configure(text_color=C_TEXT_SEC)
            self.bt_combo_tf.configure(state="disabled")
        else:
            self.bt_combo_sym.configure(state="normal")
            self.bt_sym_lbl.configure(text_color=C_TEXT_SEC)
            self.bt_combo_tf.configure(state="normal")

    def _apply_bt_preset(self, bk, v_lb, v_m, sl, tgt, tr):
        self.spin_bt_bk.set(str(bk))
        self.spin_bt_v_lb.set(str(v_lb))
        self.spin_bt_v_m.set(str(v_m))
        self.spin_bt_sl.set(str(sl))
        self.spin_bt_tgt.set(str(tgt))
        self.spin_bt_trail.set(str(tr))

    def _build_config_from_ui(self) -> Config:
        """Extract and validate the active backtest configuration from GUI controls."""
        raw_tf = self.bt_tf_var.get().strip().lower()
        if "1mo" in raw_tf or "monthly" in raw_tf:
            tf = "1mo"
        elif "1w" in raw_tf or "weekly" in raw_tf:
            tf = "1w"
        elif "1d" in raw_tf or "daily" in raw_tf:
            tf = "1d"
        elif "60m" in raw_tf or "hourly" in raw_tf or "1h" in raw_tf:
            tf = "60m"
        elif "30m" in raw_tf:
            tf = "30m"
        elif "15m" in raw_tf:
            tf = "15m"
        elif "5m" in raw_tf:
            tf = "5m"
        elif "3m" in raw_tf:
            tf = "3m"
        elif "1m" in raw_tf:
            tf = "1m"
        else:
            tf = "15m"

        htf_filter = self.bt_chk_mtf_var.get() if hasattr(self, "bt_chk_mtf_var") else False
        raw_htf = self.bt_combo_htf.get().strip().lower() if hasattr(self, "bt_combo_htf") else "1d"
        if "1w" in raw_htf or "weekly" in raw_htf:
            htf_tf = "1w"
        elif "60m" in raw_htf or "hourly" in raw_htf or "1h" in raw_htf:
            htf_tf = "60m"
        else:
            htf_tf = "1d"

        strat_mode = self.bt_combo_strat.get() if hasattr(self, "bt_combo_strat") else "ATR"
        strat_lower = strat_mode.lower()
        if "cross" in strat_lower or "golden" in strat_lower:
            strat_type = "ema_cross"
        elif "ema" in strat_lower and "trend" in strat_lower:
            strat_type = "rlh_ema"
        elif "classic" in strat_lower:
            strat_type = "rlh_classic"
        elif "breakout" in strat_lower and "combined" not in strat_lower:
            strat_type = "breakout"
        elif "combined" in strat_lower:
            strat_type = "combined"
        elif "support zone" in strat_lower or "3-touch" in strat_lower:
            strat_type = "rlh_support_zone"
        else:
            strat_type = "rlh_atr"

        side_choice = self.bt_combo_side.get() if hasattr(self, "bt_combo_side") else "Both"
        allow_short = "Long Only" not in side_choice
        atr_period_val = int(self.spin_bt_atr.get()) if hasattr(self, "spin_bt_atr") else 14
        fast_ema_val = int(self.spin_bt_ema_f.get()) if hasattr(self, "spin_bt_ema_f") else 20
        slow_ema_val = int(self.spin_bt_ema_s.get()) if hasattr(self, "spin_bt_ema_s") else 50

        cfg = Config(
            timeframe=tf,
            paper_mode=True,
            strategy_type=strat_type,
            allow_short=allow_short,
            atr_period=atr_period_val,
            ema_fast_period=fast_ema_val,
            ema_slow_period=slow_ema_val,
            initial_capital=float(self.spin_bt_cap.get()),
            risk_per_trade=float(self.spin_bt_risk.get()),
            max_position_value=float(self.spin_bt_max_v.get()),
            lookback_breakout=int(self.spin_bt_bk.get()),
            lookback_volume=int(self.spin_bt_v_lb.get()),
            volume_multiplier=float(self.spin_bt_v_m.get()),
            stop_loss_pct=float(self.spin_bt_sl.get()),
            target_pct=float(self.spin_bt_tgt.get()),
            trailing_stop_pct=float(self.spin_bt_trail.get()),
            htf_filter=htf_filter,
            htf_timeframe=htf_tf,
            htf_ema_period=fast_ema_val,
        )
        cfg.validate()
        return cfg

    def load_stock_chart(self, symbol: str):
        """Load and display the candlestick + volume chart and signals for a chosen stock."""
        symbol = str(symbol).strip()
        if not symbol:
            return

        if hasattr(self, "sig_stock_var") and self.sig_stock_var.get() != symbol:
            self.sig_stock_var.set(symbol)
        if hasattr(self, "combo_sig_stock"):
            self.combo_sig_stock.set(symbol)
        if hasattr(self, "bt_combo_sym") and self.bt_combo_sym.get() != symbol:
            self.bt_combo_sym.set(symbol)

        # 1. If symbol was already scanned in batch results, load immediately from memory!
        if hasattr(self, "last_batch_results") and symbol in self.last_batch_results:
            res = self.last_batch_results[symbol]
            if res.get("success"):
                self.last_bt_result = res
                self._update_bt_kpis(res["metrics"])
                self.raw_bt_trades = res["trades"]
                self._apply_bt_filter(self.bt_filter_var.get())
                self._plot_bt_equity(res["equity_curve"], self.cfg.initial_capital)
                self._plot_bt_signals(res["candles"], res["trades"], symbol)
                self.bt_tabview.set("🕯️ Price Action & Signals")
                return

        # 2. If not in memory yet, run backtest for this symbol in a background thread
        if self.bt_running:
            return

        try:
            cfg = self._build_config_from_ui()
        except Exception as exc:
            messagebox.showerror("Configuration Error", f"Invalid parameters: {exc}")
            return

        # Immediate feedback on canvas
        self.ax_bt_price.clear()
        self.ax_bt_vol.clear()
        self.ax_bt_price.set_title(f"⏳ Loading {symbol}... Fetching data & analyzing signals", color="#38bdf8", fontsize=11, fontweight="bold")
        self.ax_bt_price.text(0.5, 0.5, f"Fetching data for {symbol}...\nPlease wait a moment.", color=C_TEXT_SEC, fontsize=12, ha="center", va="center", transform=self.ax_bt_price.transAxes)
        self.canvas_bt_sig.draw()
        self.bt_tabview.set("🕯️ Price Action & Signals")

        self.bt_running = True
        self.btn_bt_run.configure(state="disabled", fg_color="#334155")
        self.btn_bt_stop.configure(state="normal", fg_color="#ef4444")

        def worker():
            try:
                res = run_symbol_backtest(symbol, cfg)
                def _done():
                    self._finish_backtest()
                    if res.get("success"):
                        self.last_bt_result = res
                        if not hasattr(self, "last_batch_results"):
                            self.last_batch_results = {}
                        self.last_batch_results[symbol] = res
                        self._update_bt_kpis(res["metrics"])
                        self.raw_bt_trades = res["trades"]
                        self._apply_bt_filter(self.bt_filter_var.get())
                        self._plot_bt_equity(res["equity_curve"], cfg.initial_capital)
                        self._plot_bt_signals(res["candles"], res["trades"], symbol)
                        self.bt_tabview.set("🕯️ Price Action & Signals")
                    else:
                        messagebox.showwarning("Backtest Result", f"Could not load {symbol}: {res.get('error')}")
                self.after(0, _done)
            except Exception as exc:
                self.after(0, self._finish_backtest)
                self.after(0, lambda: messagebox.showerror("Backtest Error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_sig_stock_change(self, choice: str):
        """Callback when user selects a stock from the chart toolbar dropdown."""
        self.load_stock_chart(choice)

    def _on_sidebar_sym_change(self, choice: str):
        """Callback when user changes symbol in the left sidebar combo."""
        if hasattr(self, "sig_stock_var"):
            self.sig_stock_var.set(choice)
        if hasattr(self, "combo_sig_stock"):
            self.combo_sig_stock.set(choice)

    def _on_select_matrix_symbol_row(self, event=None):
        """Callback when user double-clicks a stock row in the symbol matrix table."""
        sel = self.tree_bt_matrix.selection()
        if not sel:
            return
        vals = self.tree_bt_matrix.item(sel[0])["values"]
        sym = str(vals[0]).strip()
        self.load_stock_chart(sym)

    def _on_click_view_matrix_stock(self):
        """Button click to view selected stock from matrix in chart."""
        sel = self.tree_bt_matrix.selection()
        if not sel:
            messagebox.showinfo("Select Stock", "Please select a stock row from the matrix table first.")
            return
        vals = self.tree_bt_matrix.item(sel[0])["values"]
        sym = str(vals[0]).strip()
        self.load_stock_chart(sym)

    def start_backtest(self):
        if self.bt_running:
            return

        try:
            cfg = self._build_config_from_ui()
        except Exception as exc:
            messagebox.showerror("Configuration Error", f"Invalid parameters: {exc}")
            return

        self.bt_running = True
        self.bt_cancel_requested = False
        self.btn_bt_run.configure(state="disabled", fg_color="#334155")
        self.btn_bt_stop.configure(state="normal", fg_color="#ef4444")

        mode = self.bt_mode_var.get()
        is_batch = "Watchlist" in mode or "Portfolio" in mode
        is_multi_tf = "Multi-TF" in mode
        sym = self.bt_combo_sym.get().strip()

        def worker():
            try:
                if is_multi_tf:
                    res = run_multi_timeframe_comparison(
                        sym, cfg, timeframes=["1m", "3m", "5m", "15m", "30m", "1d", "1w", "1mo"],
                        cancel_check=lambda: self.bt_cancel_requested
                    )
                    self.after(0, lambda: self._on_bt_multi_tf_done(res, cfg))
                elif is_batch:
                    res = run_batch_backtest(self.symbols_list, cfg, cancel_check=lambda: self.bt_cancel_requested)
                    self.after(0, lambda: self._on_bt_batch_done(res, cfg))
                else:
                    res = run_symbol_backtest(sym, cfg)
                    self.after(0, lambda: self._on_bt_single_done(res, cfg))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Backtest Error", str(exc)))
                self.after(0, self._finish_backtest)

        self.bt_worker = threading.Thread(target=worker, daemon=True)
        self.bt_worker.start()

    def stop_backtest(self):
        self.bt_cancel_requested = True

    def _on_bt_multi_tf_done(self, res, cfg):
        self._finish_backtest()
        self.last_mtf_results = res.get("results_by_tf", {})
        df_comp = res.get("comparison_table", pd.DataFrame())
        best_tf = res.get("best_timeframe", "1d")

        self.lbl_mtf_best_badge.configure(
            text=f"🏆 Multi-TF Analysis Complete: Best Timeframe is {best_tf} (Highest Net P&L) — Double-click row to view charts"
        )

        for item in self.tree_bt_mtf.get_children():
            self.tree_bt_mtf.delete(item)

        for _, r in df_comp.iterrows():
            tf = r["timeframe"]
            pnl = float(r["net_pnl"])
            tag = "win" if pnl > 0 else ("loss" if pnl < 0 else "")
            if tf == best_tf:
                tag = "best"
            sign = "+" if pnl > 0 else ""
            self.tree_bt_mtf.insert(
                "", "end",
                values=(
                    f"⭐ {tf}" if tf == best_tf else tf,
                    int(r["trades"]),
                    f"{float(r['win_rate']):.1f}%",
                    f"{sign}₹ {pnl:.2f}",
                    f"{float(r['net_roi_pct']):.2f}%",
                    f"{float(r['profit_factor']):.2f}",
                    f"₹ {float(r['max_drawdown']):.2f}",
                    f"₹ {float(r['avg_trade_pnl']):.2f}",
                    f"{float(r['reward_risk']):.2f}",
                ),
                tags=(tag,),
            )

        self._plot_multi_tf_equity_overlay(self.last_mtf_results, cfg.initial_capital, res["symbol"])

        if best_tf and best_tf in self.last_mtf_results and self.last_mtf_results[best_tf]["success"]:
            best_res = self.last_mtf_results[best_tf]
            self._update_bt_kpis(best_res["metrics"])
            self.raw_bt_trades = best_res["trades"]
            self._apply_bt_filter(self.bt_filter_var.get())
            self._plot_bt_signals(best_res["candles"], best_res["trades"], res["symbol"])

        self.bt_tabview.set("📊 Multi-TF Compare")

    def _on_select_mtf_row(self, event):
        sel = self.tree_bt_mtf.selection()
        if not sel or not hasattr(self, "last_mtf_results"):
            return
        vals = self.tree_bt_mtf.item(sel[0])["values"]
        tf = str(vals[0]).replace("⭐ ", "").strip()
        if tf in self.last_mtf_results and self.last_mtf_results[tf]["success"]:
            res = self.last_mtf_results[tf]
            self._update_bt_kpis(res["metrics"])
            self.raw_bt_trades = res["trades"]
            self._apply_bt_filter(self.bt_filter_var.get())
            self._plot_bt_equity(res["equity_curve"], self.cfg.initial_capital)
            self._plot_bt_signals(res["candles"], res["trades"], res["symbol"])
            messagebox.showinfo("Timeframe Loaded", f"Loaded charts and trade journal for {tf} timeframe!")

    def _plot_multi_tf_equity_overlay(self, results_by_tf, initial_capital, symbol):
        self.ax_bt_eq.clear()
        self.ax_bt_dd.clear()
        for ax in [self.ax_bt_eq, self.ax_bt_dd]:
            ax.set_facecolor("#0e1320")
            ax.tick_params(colors=C_TEXT_SEC, labelsize=9)
            ax.grid(True, color="#1e293b", linestyle="--", linewidth=0.6, alpha=0.7)
            for s in ax.spines.values():
                s.set_color(C_BORDER)

        palette = {
            "1m": "#ec4899",
            "3m": "#f43f5e",
            "5m": "#f59e0b",
            "15m": "#00d2ff",
            "30m": "#38bdf8",
            "60m": "#a855f7",
            "1d": "#00e676",
            "1w": "#10b981",
            "1mo": "#8b5cf6",
        }

        self.ax_bt_eq.axhline(initial_capital, color="#64748b", linestyle=":", linewidth=1.0, label="Starting Capital")

        for tf, res in results_by_tf.items():
            if res.get("success"):
                eq_df = res.get("equity_curve")
                if eq_df is not None and not eq_df.empty:
                    c = palette.get(tf, "#94a3b8")
                    x = np.arange(len(eq_df))
                    equity = eq_df["equity"].values
                    pnl = res["metrics"]["net_pnl"]
                    sign = "+" if pnl > 0 else ""
                    self.ax_bt_eq.plot(x, equity, color=c, linewidth=1.8, label=f"{tf} ({sign}₹{pnl:.0f})")

                    dd = eq_df["drawdown"].values
                    self.ax_bt_dd.plot(x, dd, color=c, linewidth=1.2, label=tf)

        self.ax_bt_eq.set_title(f"{symbol} - Multi-Timeframe Equity Comparison", color=C_TEXT_PRI, fontsize=11, fontweight="bold")
        self.ax_bt_eq.set_ylabel("Equity (₹)", color=C_TEXT_SEC, fontsize=9)
        self.ax_bt_eq.legend(facecolor=C_CARD_BG, edgecolor=C_BORDER, labelcolor=C_TEXT_PRI, fontsize=8, loc="upper left")

        self.ax_bt_dd.set_title("Drawdown Depth Comparison (₹)", color=C_TEXT_PRI, fontsize=10)
        self.ax_bt_dd.set_ylabel("Underwater (₹)", color=C_TEXT_SEC, fontsize=9)
        self.ax_bt_dd.set_xlabel("Trade Sequence (#)", color=C_TEXT_SEC, fontsize=9)
        self.ax_bt_dd.legend(facecolor=C_CARD_BG, edgecolor=C_BORDER, labelcolor=C_TEXT_PRI, fontsize=8, loc="lower left")

        self.fig_bt_equity.tight_layout()
        self.canvas_bt_equity.draw()

    def _on_bt_single_done(self, res, cfg):
        self._finish_backtest()
        if not res["success"]:
            messagebox.showwarning("No Data", f"Could not backtest {res['symbol']}: {res.get('error')}")
            return

        self.last_bt_result = res
        self._update_bt_kpis(res["metrics"])
        self._plot_bt_equity(res["equity_curve"], cfg.initial_capital)
        self._plot_bt_signals(res["candles"], res["trades"], res["symbol"])
        self.raw_bt_trades = res["trades"]
        self._apply_bt_filter(self.bt_filter_var.get())

    def _on_bt_batch_done(self, res, cfg):
        self._finish_bt_batch(res, cfg)

    def _finish_bt_batch(self, res, cfg):
        self._finish_backtest()
        self.last_bt_result = res
        self.last_batch_results = res.get("results_by_symbol", {})
        self._update_bt_kpis(res["metrics"])
        self._plot_bt_equity(res["equity_curve"], cfg.initial_capital)
        self.raw_bt_trades = res["all_trades"]
        self._apply_bt_filter(self.bt_filter_var.get())
        self._populate_bt_matrix(res["symbol_summary"])

        # Update symbol selector dropdown with all successfully scanned symbols
        valid_symbols = [s for s, r in self.last_batch_results.items() if r.get("success")]
        if valid_symbols:
            if hasattr(self, "combo_sig_stock"):
                self.combo_sig_stock.configure(values=valid_symbols)
            # Find symbol with highest PnL to set as default
            best_sym = valid_symbols[0]
            if not res["symbol_summary"].empty:
                top_row = res["symbol_summary"].sort_values(by="net_pnl", ascending=False).iloc[0]
                best_sym = top_row["symbol"]
            self.sig_stock_var.set(best_sym)
            if hasattr(self, "combo_sig_stock"):
                self.combo_sig_stock.set(best_sym)
            if hasattr(self, "bt_combo_sym"):
                self.bt_combo_sym.set(best_sym)

            # Auto-plot best performing stock so the chart is ready immediately
            if best_sym in self.last_batch_results and self.last_batch_results[best_sym].get("success"):
                b_res = self.last_batch_results[best_sym]
                self._plot_bt_signals(b_res["candles"], b_res["trades"], best_sym)

        self.bt_tabview.set("🏢 Symbol Matrix")

    def _finish_backtest(self):
        self.bt_running = False
        self.btn_bt_run.configure(state="normal", fg_color="#0284c7")
        self.btn_bt_stop.configure(state="disabled", fg_color="#7f1d1d")

    def _update_bt_kpis(self, m):
        net_pnl = m.get("net_pnl", 0.0)
        pnl_col = C_PROFIT if net_pnl > 0 else (C_LOSS if net_pnl < 0 else C_TEXT_PRI)
        sign = "+" if net_pnl > 0 else ""
        self.bt_card_pnl["val"].configure(text=f"{sign}₹ {net_pnl:,.2f}", text_color=pnl_col)
        self.bt_card_pnl["sub"].configure(text=f"{sign}{m.get('net_roi_pct', 0.0):.2f}% ROI")

        wr = m.get("win_rate", 0.0)
        wr_col = C_PROFIT if wr >= 50 else (C_LOSS if wr < 40 and wr > 0 else C_TEXT_PRI)
        self.bt_card_wr["val"].configure(text=f"{wr:.1f}%", text_color=wr_col)
        self.bt_card_wr["sub"].configure(text=f"{m.get('wins', 0)} W / {m.get('losses', 0)} L")

        pf = m.get("profit_factor", 0.0)
        pf_col = C_PROFIT if pf >= 1.5 else (C_LOSS if pf < 1.0 and pf > 0 else C_AMBER)
        self.bt_card_pf["val"].configure(text=f"{pf:.2f}", text_color=pf_col)
        self.bt_card_pf["sub"].configure(text=f"Gross: +₹{m.get('gross_profit', 0.0):,.0f} | -₹{m.get('gross_loss', 0.0):,.0f}")

        self.bt_card_trades["val"].configure(text=str(m.get("total_trades", 0)))
        self.bt_card_trades["sub"].configure(text=f"Avg PnL: ₹ {m.get('avg_trade_pnl', 0.0):,.2f}")

        dd = m.get("max_drawdown", 0.0)
        dd_col = C_LOSS if dd < 0 else C_TEXT_PRI
        self.bt_card_dd["val"].configure(text=f"₹ {dd:,.2f}", text_color=dd_col)
        self.bt_card_dd["sub"].configure(text=f"{m.get('max_drawdown_pct', 0.0):.2f}% Peak DD")

        rr = m.get("reward_risk_ratio", 0.0)
        self.bt_card_rr["val"].configure(text=f"{rr:.2f}")
        self.bt_card_rr["sub"].configure(text=f"Avg W: ₹{m.get('avg_win', 0.0):.0f} | L: ₹{m.get('avg_loss', 0.0):.0f}")

    def _draw_empty_backtest_charts(self):
        for ax in [self.ax_bt_eq, self.ax_bt_dd]:
            ax.clear()
            ax.set_facecolor("#0e1320")
            ax.grid(True, color="#1e293b", linestyle="--", linewidth=0.6, alpha=0.7)
            for spine in ax.spines.values():
                spine.set_color(C_BORDER)
        self.ax_bt_eq.set_title("Portfolio Equity Progression (₹)", color=C_TEXT_PRI, fontsize=11, fontweight="bold")
        self.ax_bt_dd.set_title("Drawdown Depth (₹)", color=C_TEXT_PRI, fontsize=10)
        self.fig_bt_equity.tight_layout()
        self.canvas_bt_equity.draw()

        self.ax_bt_price.clear()
        self.ax_bt_vol.clear()
        self.ax_bt_price.set_zorder(2)
        self.ax_bt_price.patch.set_visible(False)
        self.ax_bt_vol.set_zorder(1)
        self.ax_bt_vol.patch.set_visible(True)
        self.ax_bt_vol.set_facecolor("#0e1320")
        self.ax_bt_price.tick_params(colors=C_TEXT_SEC, labelsize=8)
        self.ax_bt_price.grid(True, color="#1e293b", linestyle="--", linewidth=0.6, alpha=0.7)
        for spine in self.ax_bt_price.spines.values():
            spine.set_color(C_BORDER)
        self.ax_bt_vol.grid(False)
        self.ax_bt_vol.set_yticks([])
        for spine in self.ax_bt_vol.spines.values():
            spine.set_visible(False)
        self.ax_bt_price.set_title("Price Action & Execution Markers (Candles + Volume)", color=C_TEXT_PRI, fontsize=11, fontweight="bold")
        self.fig_bt_sig.tight_layout(pad=0.5)
        self.canvas_bt_sig.draw()

    def _plot_bt_equity(self, eq_df, initial_capital):
        self.ax_bt_eq.clear()
        self.ax_bt_dd.clear()
        for ax in [self.ax_bt_eq, self.ax_bt_dd]:
            ax.set_facecolor("#0e1320")
            ax.tick_params(colors=C_TEXT_SEC, labelsize=9)
            ax.grid(True, color="#1e293b", linestyle="--", linewidth=0.6, alpha=0.7)
            for s in ax.spines.values():
                s.set_color(C_BORDER)

        if eq_df.empty or len(eq_df) < 2:
            self._draw_empty_backtest_charts()
            return

        x = np.arange(len(eq_df))
        equity = eq_df["equity"].values
        peak = eq_df["peak"].values
        dd = eq_df["drawdown"].values

        self.ax_bt_eq.plot(x, equity, color=C_ACCENT, linewidth=2.0, label="Equity")
        self.ax_bt_eq.plot(x, peak, color=C_PROFIT, linestyle="--", linewidth=1.2, alpha=0.7, label="High Water Mark")
        self.ax_bt_eq.axhline(initial_capital, color="#64748b", linestyle=":", linewidth=1.0)
        self.ax_bt_eq.fill_between(x, initial_capital, equity, where=(equity >= initial_capital), color=C_PROFIT, alpha=0.15)
        self.ax_bt_eq.fill_between(x, initial_capital, equity, where=(equity < initial_capital), color=C_LOSS, alpha=0.15)
        self.ax_bt_eq.set_title("Portfolio Equity Progression (₹)", color=C_TEXT_PRI, fontsize=11, fontweight="bold")
        self.ax_bt_eq.set_ylabel("Account Balance (₹)", color=C_TEXT_SEC, fontsize=9)
        self.ax_bt_eq.legend(facecolor=C_CARD_BG, edgecolor=C_BORDER, labelcolor=C_TEXT_PRI, fontsize=8, loc="upper left")

        self.ax_bt_dd.plot(x, dd, color=C_LOSS, linewidth=1.5)
        self.ax_bt_dd.fill_between(x, 0, dd, color=C_LOSS, alpha=0.3)
        self.ax_bt_dd.set_title("Drawdown Depth (₹)", color=C_TEXT_PRI, fontsize=10)
        self.ax_bt_dd.set_ylabel("Underwater (₹)", color=C_TEXT_SEC, fontsize=9)
        self.ax_bt_dd.set_xlabel("Completed Trade Sequence (#)", color=C_TEXT_SEC, fontsize=9)

        self.fig_bt_equity.tight_layout()
        self.canvas_bt_equity.draw()

    def _on_sig_chart_filter_change(self, *_):
        """Re-render the candlestick chart whenever a chart filter control changes."""
        if not self._sig_candles_cache.empty:
            self._plot_bt_signals(
                self._sig_candles_cache,
                self._sig_trades_cache,
                self._sig_symbol_cache,
            )

    def _plot_bt_signals(self, candles: pd.DataFrame, trades: pd.DataFrame, symbol: str):
        """Render OHLC candlestick chart with filtered trade signal overlays."""
        # ---- Cache for filter re-renders -----------------------------------
        self._sig_candles_cache = candles.copy() if not candles.empty else pd.DataFrame()
        self._sig_trades_cache = trades.copy() if not trades.empty else pd.DataFrame()
        self._sig_symbol_cache = symbol

        self.ax_bt_price.clear()
        self.ax_bt_vol.clear()

        # Place price layer above volume layer so candles render over volume bars
        self.ax_bt_price.set_zorder(2)
        self.ax_bt_price.patch.set_visible(False)
        self.ax_bt_vol.set_zorder(1)
        self.ax_bt_vol.patch.set_visible(True)
        self.ax_bt_vol.set_facecolor("#0b1120")

        self.ax_bt_price.tick_params(colors=C_TEXT_SEC, labelsize=8)
        self.ax_bt_price.grid(True, color="#1a2540", linestyle="--", linewidth=0.5, alpha=0.6)
        for s in self.ax_bt_price.spines.values():
            s.set_color(C_BORDER)

        self.ax_bt_vol.grid(False)
        self.ax_bt_vol.set_yticks([])
        for s in self.ax_bt_vol.spines.values():
            s.set_visible(False)

        if candles.empty:
            self.canvas_bt_sig.draw()
            return

        # ---- Apply candle window filter ------------------------------------
        candle_window = self.sig_candle_count_var.get() if hasattr(self, "sig_candle_count_var") else "Last 200"
        disp_candles = candles.copy()
        window_map = {"Last 50": 50, "Last 100": 100, "Last 200": 200, "Last 500": 500}
        if candle_window in window_map:
            disp_candles = candles.iloc[-window_map[candle_window]:].copy()
            disp_candles = disp_candles.reset_index(drop=False)  # keep original index as col
        else:
            disp_candles = candles.copy().reset_index(drop=False)

        n = len(disp_candles)
        x_idx = np.arange(n)

        # ---- Draw OHLC Candlesticks ----------------------------------------
        W_BODY = 0.6   # body width as fraction of bar width
        W_WICK = 0.12  # wick width
        from matplotlib.patches import Rectangle
        from matplotlib.collections import PatchCollection, LineCollection

        bull_bodies, bear_bodies = [], []
        wick_segs = []
        bull_col = "#26a69a"   # teal-green for bullish
        bear_col = "#ef5350"   # red for bearish

        o = disp_candles["open"].values
        h = disp_candles["high"].values
        lo = disp_candles["low"].values
        c = disp_candles["close"].values

        for i in range(n):
            is_bull = c[i] >= o[i]
            body_bot = min(o[i], c[i])
            body_top = max(o[i], c[i])
            body_h = max(body_top - body_bot, 1e-6)  # avoid zero-height

            rect = Rectangle((i - W_BODY / 2, body_bot), W_BODY, body_h)
            if is_bull:
                bull_bodies.append(rect)
            else:
                bear_bodies.append(rect)

            # upper & lower wicks
            wick_segs.append([(i, lo[i]), (i, h[i])])

        # Wick lines
        lc = LineCollection(wick_segs, colors="#546e7a", linewidths=0.8, zorder=2)
        self.ax_bt_price.add_collection(lc)

        # Body patches
        if bull_bodies:
            pc_bull = PatchCollection(bull_bodies, facecolor=bull_col, edgecolor=bull_col, linewidth=0.3, zorder=3)
            self.ax_bt_price.add_collection(pc_bull)
        if bear_bodies:
            pc_bear = PatchCollection(bear_bodies, facecolor=bear_col, edgecolor=bear_col, linewidth=0.3, zorder=3)
            self.ax_bt_price.add_collection(pc_bear)

        self.ax_bt_price.set_xlim(-1, n)
        self.ax_bt_vol.set_xlim(-1, n)
        price_range = h.max() - lo.min() if n > 0 else 1
        self.ax_bt_price.set_ylim(lo.min() - price_range * 0.03, h.max() + price_range * 0.05)

        # ---- EMA Overlays --------------------------------------------------
        show_ema = self.chk_sig_ema_var.get() if hasattr(self, "chk_sig_ema_var") else True
        show_crosses = self.chk_sig_crosses_var.get() if hasattr(self, "chk_sig_crosses_var") else True

        if show_ema:
            if "ema_20" in disp_candles.columns and not disp_candles["ema_20"].isna().all():
                self.ax_bt_price.plot(x_idx, disp_candles["ema_20"].values, color="#00e676",
                                      linewidth=1.5, alpha=0.95, label="EMA 20", zorder=4)
            if "ema_50" in disp_candles.columns and not disp_candles["ema_50"].isna().all():
                self.ax_bt_price.plot(x_idx, disp_candles["ema_50"].values, color="#ff5252",
                                      linewidth=1.5, alpha=0.95, label="EMA 50", zorder=4)

        if show_crosses:
            if "ema_golden_cross" in disp_candles.columns:
                gc_mask = disp_candles["ema_golden_cross"].fillna(False).values
                gc_i = np.where(gc_mask)[0]
                if len(gc_i):
                    ema_vals = disp_candles["ema_20"].values
                    self.ax_bt_price.scatter(gc_i, ema_vals[gc_i], color="#eab308",
                                             marker="*", s=150, zorder=7, label="Golden Cross ☀")
            if "ema_death_cross" in disp_candles.columns:
                dc_mask = disp_candles["ema_death_cross"].fillna(False).values
                dc_i = np.where(dc_mask)[0]
                if len(dc_i):
                    ema_vals = disp_candles["ema_20"].values
                    self.ax_bt_price.scatter(dc_i, ema_vals[dc_i], color="#f43f5e",
                                             marker="X", s=100, zorder=7, label="Death Cross ✕")

        # ---- RLH Support Zone Bands ----------------------------------------
        if "rlh_sz_lower" in disp_candles.columns and "rlh_sz_upper" in disp_candles.columns:
            sz_low_col  = disp_candles["rlh_sz_lower"].values
            sz_high_col = disp_candles["rlh_sz_upper"].values
            touch_col   = disp_candles["rlh_sz_touch_count"].values if "rlh_sz_touch_count" in disp_candles.columns else np.zeros(n)
            bd_col      = disp_candles["rlh_sz_breakdown"].fillna(False).values if "rlh_sz_breakdown" in disp_candles.columns else np.zeros(n, dtype=bool)

            drawn_zones = set()
            for zi in range(n):
                zl = sz_low_col[zi]
                zu = sz_high_col[zi]
                if np.isnan(zl) or np.isnan(zu):
                    continue
                zone_key = (round(zl, 3), round(zu, 3))
                if zone_key in drawn_zones:
                    continue
                drawn_zones.add(zone_key)

                # Span: find extent of this zone in the display window
                zone_start = zi
                zone_end   = zi
                for zj in range(zi, n):
                    if not np.isnan(sz_low_col[zj]) and abs(sz_low_col[zj] - zl) < 0.01:
                        zone_end = zj

                xr = np.arange(zone_start, min(zone_end + 1, n))
                if len(xr) > 0:
                    self.ax_bt_price.fill_between(
                        xr, zl, zu,
                        color="#f59e0b", alpha=0.15, zorder=1, label="L-Candle Support Zone",
                    )
                self.ax_bt_price.plot(xr, [zl] * len(xr), color="#f59e0b",
                                      linestyle="--", linewidth=0.9, alpha=0.75, zorder=2)
                self.ax_bt_price.plot(xr, [zu] * len(xr), color="#fbbf24",
                                      linestyle=":", linewidth=0.9, alpha=0.75, zorder=2)

                # Touch count label
                max_touch = int(np.nanmax(touch_col[zone_start:zone_end + 1]))
                if max_touch > 0:
                    self.ax_bt_price.annotate(
                        f"T:{max_touch}",
                        xy=(zone_start + 1, (zl + zu) / 2),
                        fontsize=7, color="#f59e0b", fontweight="bold",
                        ha="left", va="center",
                        bbox=dict(boxstyle="round,pad=0.2", fc="#0e1a2e", ec="#f59e0b", alpha=0.85),
                        zorder=9,
                    )

            # Breakdown arrows
            bd_mask = bd_col.astype(bool)
            if bd_mask.any():
                bd_idx = np.where(bd_mask)[0]
                bd_prices = np.array([sz_low_col[j] if not np.isnan(sz_low_col[j]) else lo[j] for j in bd_idx])
                self.ax_bt_price.scatter(
                    bd_idx, bd_prices - price_range * 0.015,
                    color="#ff6f00", marker="v", s=150, zorder=10,
                    edgecolors="white", linewidths=0.6, label="⬇ SZ Breakdown",
                )

        # ---- Signal Markers ------------------------------------------------
        sig_filter = self.sig_chart_filter_var.get() if hasattr(self, "sig_chart_filter_var") else "All Signals"

        visible_count = 0
        if not trades.empty:
            # Build timestamp→display-index map
            orig_index = disp_candles.iloc[:, 0] if "index" in disp_candles.columns else disp_candles.index
            # If reset_index was called, original index is stored in first col or "index" col
            idx_col = disp_candles.columns[0] if disp_candles.columns[0] in ("index", "datetime", "timestamp") else None
            t_map = {}
            for pos, (_, row) in enumerate(disp_candles.iterrows()):
                raw_ts = row[idx_col] if idx_col else row.name
                t_map[raw_ts] = pos

            # Fallback: use full candles t_map for timestamp lookup
            full_t_map = {t: i for i, t in enumerate(candles.index)}
            # Offset if windowed
            offset = len(candles) - n

            for _, tr in trades.iterrows():
                side = str(tr.get("side", "LONG"))
                pnl = float(tr.get("pnl_inr", 0))
                is_win = pnl > 0

                # Apply signal filter
                if sig_filter == "Long Entries Only" and side != "LONG":
                    continue
                if sig_filter == "Short Entries Only" and side != "SHORT":
                    continue
                if sig_filter == "Winning Trades" and not is_win:
                    continue
                if sig_filter == "Losing Trades" and is_win:
                    continue

                # Map timestamps to display positions
                en_full = full_t_map.get(tr["entry_time"])
                ex_full = full_t_map.get(tr["exit_time"])

                en_i = en_full - offset if en_full is not None and en_full >= offset else None
                ex_i = ex_full - offset if ex_full is not None and ex_full >= offset else None

                if sig_filter == "Pattern Markers Only":
                    # Only show entries, skip exits
                    if en_i is not None and 0 <= en_i < n:
                        visible_count += 1
                        col = C_PROFIT if side == "LONG" else C_LOSS
                        mk = "^" if side == "LONG" else "v"
                        lbl = "▲ LONG" if side == "LONG" else "▼ SHORT"
                        self.ax_bt_price.scatter(
                            en_i, c[en_i] * 0.998 if side == "LONG" else c[en_i] * 1.002,
                            color=col, marker=mk, s=110, zorder=8,
                            edgecolors="white", linewidths=0.6, label=lbl
                        )
                    continue

                # Entry marker
                if en_i is not None and 0 <= en_i < n:
                    visible_count += 1
                    if side == "LONG":
                        self.ax_bt_price.scatter(
                            en_i, lo[en_i] - price_range * 0.012,
                            color="#00e676", marker="^", s=110, zorder=8,
                            edgecolors="white", linewidths=0.5, label="▲ LONG Entry"
                        )
                    else:
                        self.ax_bt_price.scatter(
                            en_i, h[en_i] + price_range * 0.012,
                            color="#ff5252", marker="v", s=110, zorder=8,
                            edgecolors="white", linewidths=0.5, label="▼ SHORT Entry"
                        )

                # Exit marker
                if ex_i is not None and 0 <= ex_i < n:
                    m_c = "#00e676" if is_win else "#ff5252"
                    m_s = "*" if "target" in str(tr.get("reason", "")) else "X"
                    lbl_exit = "★ Exit (Profit)" if is_win else "✕ Exit (Loss)"
                    self.ax_bt_price.scatter(
                        ex_i, h[ex_i] + price_range * 0.018 if side == "LONG" else lo[ex_i] - price_range * 0.018,
                        color=m_c, marker=m_s, s=120, zorder=8,
                        edgecolors="white", linewidths=0.5, label=lbl_exit
                    )

        # ---- Legend --------------------------------------------------------
        handles, labels = self.ax_bt_price.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        if by_label:
            self.ax_bt_price.legend(
                by_label.values(), by_label.keys(),
                facecolor="#0e1a2e", edgecolor=C_BORDER, labelcolor=C_TEXT_PRI,
                fontsize=8, loc="upper left", framealpha=0.85
            )

        # ---- Title ---------------------------------------------------------
        trend_tag = ""
        if "ema_trend" in candles.columns and len(candles) > 0:
            last_t = str(candles["ema_trend"].iloc[-1])
            t_color = "▲" if last_t == "BULLISH" else "▼"
            trend_tag = f"  |  Trend: {t_color} {last_t} (20/50 EMA)"

        window_tag = f" [{candle_window}]" if candle_window != "All" else ""
        self.ax_bt_price.set_title(
            f"{symbol}{window_tag} — Candlestick + Volume  [{sig_filter}]{trend_tag}",
            color=C_TEXT_PRI, fontsize=10, fontweight="bold", pad=6
        )
        self.ax_bt_price.set_ylabel("Price (₹)", color=C_TEXT_SEC, fontsize=9)

        # ---- Datetime X-axis ticks (on main unified chart) -----------------
        idx_col_name = disp_candles.columns[0]
        try:
            dt_values = pd.to_datetime(disp_candles[idx_col_name].values)
        except Exception:
            dt_values = None

        if dt_values is not None and len(dt_values) > 1:
            span_days = (dt_values[-1] - dt_values[0]).days
            if span_days <= 3:
                dt_fmt = "%d %b\n%H:%M"
            elif span_days <= 180:
                dt_fmt = "%d %b\n%Y"
            else:
                dt_fmt = "%b\n%Y"

            num_ticks = min(10, n)
            tick_step = max(1, n // num_ticks)
            tick_positions = list(range(0, n, tick_step))
            if tick_positions[-1] != n - 1:
                tick_positions.append(n - 1)
            tick_positions = np.array(tick_positions)
            tick_labels = [dt_values[i].strftime(dt_fmt) for i in tick_positions]

            self.ax_bt_price.set_xticks(tick_positions)
            self.ax_bt_price.set_xticklabels(
                tick_labels, fontsize=8, color=C_TEXT_SEC, rotation=0, ha="center"
            )
        else:
            self.ax_bt_price.set_xlabel("Bar Index", color=C_TEXT_SEC, fontsize=9)

        # ---- Volume Bars (Overlay on Same Chart, Bottom ~20%) --------------
        show_vol = self.chk_sig_vol_var.get() if hasattr(self, "chk_sig_vol_var") else True
        if show_vol and "volume" in disp_candles.columns:
            vol = disp_candles["volume"].values
            max_v = float(np.nanmax(vol)) if len(vol) > 0 else 0.0
            if max_v > 0:
                bull_vol_mask = c >= o
                bear_vol_mask = ~bull_vol_mask
                self.ax_bt_vol.bar(x_idx[bull_vol_mask], vol[bull_vol_mask], color=bull_col, alpha=0.35, width=0.7, zorder=1)
                self.ax_bt_vol.bar(x_idx[bear_vol_mask], vol[bear_vol_mask], color=bear_col, alpha=0.35, width=0.7, zorder=1)
                self.ax_bt_vol.set_ylim(0, max_v * 4.5)  # Constrain volume bars to bottom ~22%
            else:
                self.ax_bt_vol.set_ylim(0, 1.0)
        else:
            self.ax_bt_vol.set_ylim(0, 1.0)

        # ---- Signal count label -------------------------------------------
        if hasattr(self, "lbl_sig_trade_count"):
            total = len(trades) if not trades.empty else 0
            self.lbl_sig_trade_count.configure(
                text=f"{visible_count} of {total} signals shown"
                if sig_filter != "All Signals" else f"{total} signals"
            )

        self.fig_bt_sig.tight_layout(pad=0.5)
        self.canvas_bt_sig.draw()

    def _apply_bt_filter(self, choice):
        for item in self.tree_bt_trades.get_children():
            self.tree_bt_trades.delete(item)

        if not hasattr(self, "raw_bt_trades") or self.raw_bt_trades.empty:
            self.lbl_bt_count.configure(text="0 trades")
            return

        df = self.raw_bt_trades.copy()
        if choice == "Winning Trades Only":
            df = df[df["pnl_inr"] > 0]
        elif choice == "Losing Trades Only":
            df = df[df["pnl_inr"] < 0]
        elif choice == "LONG Only":
            df = df[df.get("side", "LONG") == "LONG"]
        elif choice == "SHORT Only":
            df = df[df.get("side", "LONG") == "SHORT"]
        elif choice == "Color Flip Exits":
            df = df[df["reason"] == "color_flip_target"]
        elif choice == "Stop Loss Exits":
            df = df[df["reason"].str.contains("stop", case=False, na=False)]

        self.lbl_bt_count.configure(text=f"{len(df)} of {len(self.raw_bt_trades)} trades")

        for i, (_, r) in enumerate(df.iterrows(), start=1):
            pnl = float(r["pnl_inr"])
            tag = "win" if pnl > 0 else ("loss" if pnl < 0 else "")
            sign = "+" if pnl > 0 else ""
            ret_pct = float(r.get("return_pct", 0.0))
            side = str(r.get("side", "LONG"))

            self.tree_bt_trades.insert(
                "", "end",
                values=(
                    i,
                    r["symbol"],
                    side,
                    str(r["entry_time"]).split("+")[0],
                    str(r["exit_time"]).split("+")[0],
                    f"₹ {float(r['entry']):.2f}",
                    f"₹ {float(r['exit']):.2f}",
                    int(r["qty"]),
                    f"{sign}₹ {pnl:.2f}",
                    f"{sign}{ret_pct:.2f}%",
                    r["reason"],
                ),
                tags=(tag,),
            )

    def _populate_bt_matrix(self, summary_df):
        for item in self.tree_bt_matrix.get_children():
            self.tree_bt_matrix.delete(item)

        if summary_df.empty:
            return

        for _, r in summary_df.iterrows():
            pnl = float(r["net_pnl"])
            tag = "win" if pnl > 0 else ("loss" if pnl < 0 else "")
            sign = "+" if pnl > 0 else ""
            self.tree_bt_matrix.insert(
                "", "end",
                values=(
                    r["symbol"],
                    int(r["trades"]),
                    f"{float(r['win_rate']):.1f}%",
                    f"{sign}₹ {pnl:.2f}",
                    f"{float(r['profit_factor']):.2f}",
                    f"₹ {float(r['max_drawdown']):.2f}",
                    r["status"],
                ),
                tags=(tag,),
            )

    def export_backtest_csv(self):
        if not hasattr(self, "raw_bt_trades") or self.raw_bt_trades.empty:
            messagebox.showinfo("Export CSV", "No trades to export.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"backtest_trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if file_path:
            try:
                self.raw_bt_trades.to_csv(file_path, index=False)
                messagebox.showinfo("Export Successful", f"Saved to {file_path}")
            except Exception as exc:
                messagebox.showerror("Export Failed", str(exc))

    # =========================================================================
    # MODULE 3: Watchlist & Strategy Configuration Editor (Option 4)
    # =========================================================================
    def _build_config_editor_view(self, parent):
        two_col = ctk.CTkFrame(parent, fg_color="transparent")
        two_col.pack(fill="both", expand=True)

        # Left Column: Strategy & Risk Parameters Form (.env Editor)
        self.cfg_sidebar = ctk.CTkScrollableFrame(two_col, width=540, fg_color=C_CARD_BG, corner_radius=10, border_width=1, border_color=C_BORDER)
        self.cfg_sidebar.pack(side="left", fill="both", expand=True, padx=(0, 10))
        form_scroll = self.cfg_sidebar

        cfg_side_hdr = ctk.CTkFrame(form_scroll, fg_color="transparent")
        cfg_side_hdr.pack(fill="x", padx=15, pady=(15, 6))

        head_cfg = ctk.CTkLabel(cfg_side_hdr, text="⚙️ SYSTEM CONFIGURATION & RISK SETTINGS (.env)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#38bdf8")
        head_cfg.pack(side="left")

        self.btn_cfg_side_hide = ctk.CTkButton(
            cfg_side_hdr,
            text="◀ Hide",
            width=54,
            height=24,
            fg_color="#1e293b",
            hover_color="#334155",
            border_width=1,
            border_color=C_BORDER,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=C_TEXT_SEC,
            command=self.toggle_sidebar,
        )
        self.btn_cfg_side_hide.pack(side="right")

        sub_cfg = ctk.CTkLabel(form_scroll, text="Modify core breakout strategy rules, risk sizing, and polling intervals.", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        sub_cfg.pack(anchor="w", padx=15, pady=(0, 12))

        # Timeframe & Safety
        self._add_section_title(form_scroll, "1. Core Execution Mode")
        self.cfg_var_tf = self._create_form_row(form_scroll, "TIMEFRAME (1m, 3m, 5m, 15m, 30m, 1d, 1w, 1mo):", self.cfg.timeframe)
        self.cfg_var_paper = self._create_form_row(form_scroll, "PAPER_MODE (Strictly paper-only):", "true", readonly=True)

        # Strategy Lookbacks
        self._add_section_title(form_scroll, "2. Strategy & Volatility Parameters")
        self.cfg_var_strat = self._create_form_row(form_scroll, "STRATEGY_TYPE (rlh_atr, rlh_ema, ema_cross, rlh_classic, breakout, combined, rlh_support_zone):", self.cfg.strategy_type)
        self.cfg_var_atr = self._create_form_row(form_scroll, "ATR_PERIOD (True Range lookback bars):", str(self.cfg.atr_period))
        self.cfg_var_short = self._create_form_row(form_scroll, "ALLOW_SHORT (true / false):", "true" if self.cfg.allow_short else "false")
        self.cfg_var_bk = self._create_form_row(form_scroll, "LOOKBACK_BREAKOUT (bars):", str(self.cfg.lookback_breakout))
        self.cfg_var_v_lb = self._create_form_row(form_scroll, "LOOKBACK_VOLUME (bars):", str(self.cfg.lookback_volume))
        self.cfg_var_v_m = self._create_form_row(form_scroll, "VOLUME_MULTIPLIER (x):", str(self.cfg.volume_multiplier))
        self.cfg_var_poll = self._create_form_row(form_scroll, "POLL_SECONDS (Scanner interval):", str(self.cfg.poll_seconds))
        self.cfg_var_buf = self._create_form_row(form_scroll, "CANDLE_CLOSE_BUFFER_SECONDS:", str(self.cfg.close_buffer_seconds))

        # MTF Confluence Settings
        self._add_section_title(form_scroll, "3. Multi-Timeframe (MTF) 20/50 EMA Trend Confluence")
        self.cfg_var_htf_on = self._create_form_row(form_scroll, "HTF_FILTER (true / false):", "true" if self.cfg.htf_filter else "false")
        self.cfg_var_htf_tf = self._create_form_row(form_scroll, "HTF_TIMEFRAME (1d, 1w, 60m):", self.cfg.htf_timeframe)
        self.cfg_var_ema_fast = self._create_form_row(form_scroll, "EMA_FAST_PERIOD (Fast trend EMA bars):", str(self.cfg.ema_fast_period))
        self.cfg_var_ema_slow = self._create_form_row(form_scroll, "EMA_SLOW_PERIOD (Slow trend EMA bars):", str(self.cfg.ema_slow_period))

        # Capital & Risk
        self._add_section_title(form_scroll, "4. Capital & Risk Allocation")
        self.cfg_var_cap = self._create_form_row(form_scroll, "INITIAL_CAPITAL_INR (₹):", str(int(self.cfg.initial_capital)))
        self.cfg_var_risk = self._create_form_row(form_scroll, "RISK_PER_TRADE_INR (₹):", str(int(self.cfg.risk_per_trade)))
        self.cfg_var_max_v = self._create_form_row(form_scroll, "MAX_POSITION_VALUE_INR (₹):", str(int(self.cfg.max_position_value)))
        self.cfg_var_max_pos = self._create_form_row(form_scroll, "MAX_OPEN_POSITIONS:", str(self.cfg.max_open_positions))
        self.cfg_var_max_sh = self._create_form_row(form_scroll, "MAX_SHARES_PER_STOCK:", str(self.cfg.max_shares_per_stock))

        # Exits
        self._add_section_title(form_scroll, "4. Exit Disciplines")
        self.cfg_var_sl = self._create_form_row(form_scroll, "STOP_LOSS_PCT (%):", str(self.cfg.stop_loss_pct))
        self.cfg_var_tgt = self._create_form_row(form_scroll, "TARGET_PCT (%):", str(self.cfg.target_pct))
        self.cfg_var_trail = self._create_form_row(form_scroll, "TRAILING_STOP_PCT (%):", str(self.cfg.trailing_stop_pct))

        # Action Buttons
        self._add_divider(form_scroll)
        btn_box = ctk.CTkFrame(form_scroll, fg_color="transparent")
        btn_box.pack(fill="x", padx=15, pady=(10, 20))

        btn_save_env = ctk.CTkButton(
            btn_box, text="💾 Save to .env File", font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#059669", hover_color="#047857", height=36, command=self._save_env_configuration
        )
        btn_save_env.pack(side="left", expand=True, fill="x", padx=4)

        btn_reload_env = ctk.CTkButton(
            btn_box, text="↺ Reload from .env", font=ctk.CTkFont(size=12),
            fg_color="#1e293b", hover_color="#334155", height=36, command=self._reload_config_form_values
        )
        btn_reload_env.pack(side="left", expand=True, fill="x", padx=4)

        btn_defaults = ctk.CTkButton(
            btn_box, text="⚡ Defaults", font=ctk.CTkFont(size=12),
            fg_color="#334155", hover_color="#475569", height=36, command=self._restore_default_config_form
        )
        btn_defaults.pack(side="left", expand=True, fill="x", padx=4)

        # Right Column: Watchlist Manager (watchlist.txt)
        self.cfg_workspace = ctk.CTkFrame(two_col, fg_color=C_CARD_BG, corner_radius=10, border_width=1, border_color=C_BORDER)
        self.cfg_workspace.pack(side="right", fill="both", expand=True)
        wl_col = self.cfg_workspace

        self.cfg_show_bar = ctk.CTkFrame(wl_col, fg_color=C_CARD_BG, corner_radius=8, height=36, border_width=1, border_color=C_BORDER)
        btn_show_cfg = ctk.CTkButton(
            self.cfg_show_bar,
            text="▶ Show Configuration Form (Ctrl+B)",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=26,
            command=self.toggle_sidebar,
        )
        btn_show_cfg.pack(side="left", padx=10, pady=5)

        lbl_cfg_expand_hint = ctk.CTkLabel(
            self.cfg_show_bar,
            text="Form collapsed — Watchlist manager expanded to full width",
            font=ctk.CTkFont(size=11),
            text_color=C_TEXT_SEC,
        )
        lbl_cfg_expand_hint.pack(side="left", padx=10)

        self.cfg_head_wl = ctk.CTkLabel(wl_col, text="📋 NIFTY 50 WATCHLIST MANAGER (watchlist.txt)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#38bdf8")
        self.cfg_head_wl.pack(anchor="w", padx=15, pady=(15, 6))
        head_wl = self.cfg_head_wl

        sub_wl = ctk.CTkLabel(wl_col, text="Manage equities scanned by the paper trader and backtester.", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        sub_wl.pack(anchor="w", padx=15, pady=(0, 10))

        # Add Ticker Controls
        add_row = ctk.CTkFrame(wl_col, fg_color="transparent")
        add_row.pack(fill="x", padx=15, pady=(0, 10))

        self.cfg_entry_sym = ctk.CTkEntry(add_row, placeholder_text="e.g. WIPRO.NS", width=160, fg_color=C_INPUT_BG, border_color=C_BORDER)
        self.cfg_entry_sym.pack(side="left", padx=(0, 8))

        ctk.CTkButton(add_row, text="+ Add Ticker", width=100, fg_color="#0284c7", command=self._add_ticker_to_watchlist).pack(side="left", padx=(0, 8))
        ctk.CTkButton(add_row, text="- Remove Ticker", width=110, fg_color="#7f1d1d", command=self._remove_ticker_from_watchlist).pack(side="left", padx=(0, 8))
        ctk.CTkButton(add_row, text="💾 Save watchlist.txt", width=140, fg_color="#059669", command=self._save_watchlist_file).pack(side="right")

        # Search Bar
        search_row = ctk.CTkFrame(wl_col, fg_color="transparent")
        search_row.pack(fill="x", padx=15, pady=(0, 8))
        ctk.CTkLabel(search_row, text="Search:", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC).pack(side="left", padx=(0, 6))
        self.cfg_search_var = ctk.StringVar()
        self.cfg_search_var.trace_add("write", lambda *_: self._filter_watchlist_listbox())
        ctk.CTkEntry(search_row, textvariable=self.cfg_search_var, placeholder_text="Type symbol...", width=180, fg_color=C_INPUT_BG, border_color=C_BORDER).pack(side="left")

        self.lbl_wl_count = ctk.CTkLabel(search_row, text=f"{len(self.symbols_list)} tickers", font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        self.lbl_wl_count.pack(side="right")

        # Listbox for Watchlist Tickers
        list_container = ctk.CTkFrame(wl_col, fg_color=C_CARD_INNER, corner_radius=8, border_width=1, border_color=C_BORDER)
        list_container.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        self.cfg_listbox = tk.Listbox(
            list_container,
            bg=C_CARD_INNER,
            fg=C_TEXT_PRI,
            selectbackground="#0284c7",
            selectforeground="#ffffff",
            font=("Segoe UI", 11),
            borderwidth=0,
            highlightthickness=0,
        )
        scroll_wl = ttk.Scrollbar(list_container, orient="vertical", command=self.cfg_listbox.yview)
        self.cfg_listbox.configure(yscrollcommand=scroll_wl.set)

        self.cfg_listbox.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scroll_wl.pack(side="right", fill="y", padx=(0, 10), pady=10)

    def _add_section_title(self, parent, title):
        lbl = ctk.CTkLabel(parent, text=title, font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8")
        lbl.pack(anchor="w", padx=15, pady=(12, 4))

    def _create_form_row(self, parent, label, default_val, readonly=False):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=3)

        lbl = ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC)
        lbl.pack(side="left")

        val_var = ctk.StringVar(value=default_val)
        entry = ctk.CTkEntry(
            row, textvariable=val_var, width=120, height=26,
            fg_color=C_INPUT_BG, border_color=C_BORDER, font=ctk.CTkFont(size=11),
            state="disabled" if readonly else "normal"
        )
        entry.pack(side="right")
        return val_var

    def _save_env_configuration(self):
        try:
            htf_bool = "true" if "true" in self.cfg_var_htf_on.get().lower() else "false"
            env_content = (
                "# Yahoo Finance Nifty 50 Paper Trader Configuration\n"
                "# Generated via Application Settings Editor\n\n"
                f"PAPER_MODE=true\n"
                f"TIMEFRAME={self.cfg_var_tf.get().strip()}\n"
                f"STRATEGY_TYPE={self.cfg_var_strat.get().strip().lower()}\n"
                f"ATR_PERIOD={int(self.cfg_var_atr.get())}\n"
                f"ALLOW_SHORT={'true' if 'true' in self.cfg_var_short.get().lower() else 'false'}\n"
                f"LOOKBACK_BREAKOUT={int(self.cfg_var_bk.get())}\n"
                f"LOOKBACK_VOLUME={int(self.cfg_var_v_lb.get())}\n"
                f"VOLUME_MULTIPLIER={float(self.cfg_var_v_m.get())}\n\n"
                f"HTF_FILTER={htf_bool}\n"
                f"HTF_TIMEFRAME={self.cfg_var_htf_tf.get().strip()}\n"
                f"EMA_FAST_PERIOD={int(self.cfg_var_ema_fast.get())}\n"
                f"EMA_SLOW_PERIOD={int(self.cfg_var_ema_slow.get())}\n\n"
                f"INITIAL_CAPITAL_INR={float(self.cfg_var_cap.get())}\n"
                f"RISK_PER_TRADE_INR={float(self.cfg_var_risk.get())}\n"
                f"MAX_POSITION_VALUE_INR={float(self.cfg_var_max_v.get())}\n"
                f"MAX_OPEN_POSITIONS={int(self.cfg_var_max_pos.get())}\n"
                f"MAX_SHARES_PER_STOCK={int(self.cfg_var_max_sh.get())}\n\n"
                f"STOP_LOSS_PCT={float(self.cfg_var_sl.get())}\n"
                f"TARGET_PCT={float(self.cfg_var_tgt.get())}\n"
                f"TRAILING_STOP_PCT={float(self.cfg_var_trail.get())}\n\n"
                f"CANDLE_CLOSE_BUFFER_SECONDS={int(self.cfg_var_buf.get())}\n"
                f"POLL_SECONDS={int(self.cfg_var_poll.get())}\n"
                "LOG_LEVEL=INFO\n"
            )

            Path(".env").write_text(env_content, encoding="utf-8")

            # Reload runtime config
            self.cfg = Config()
            self.cfg.validate()
            self.paper_service.update_config(self.cfg)

            messagebox.showinfo("Saved", "Configuration successfully saved to .env and active runtime updated!")
        except Exception as exc:
            messagebox.showerror("Save Failed", f"Could not save .env: {exc}")

    def _reload_config_form_values(self):
        try:
            self.cfg = Config()
            self.cfg_var_tf.set(self.cfg.timeframe)
            if hasattr(self, "cfg_var_strat"):
                self.cfg_var_strat.set(self.cfg.strategy_type)
            if hasattr(self, "cfg_var_atr"):
                self.cfg_var_atr.set(str(self.cfg.atr_period))
            if hasattr(self, "cfg_var_short"):
                self.cfg_var_short.set("true" if self.cfg.allow_short else "false")
            self.cfg_var_bk.set(str(self.cfg.lookback_breakout))
            self.cfg_var_v_lb.set(str(self.cfg.lookback_volume))
            self.cfg_var_v_m.set(str(self.cfg.volume_multiplier))
            self.cfg_var_htf_on.set("true" if self.cfg.htf_filter else "false")
            self.cfg_var_htf_tf.set(self.cfg.htf_timeframe)
            if hasattr(self, "cfg_var_ema_fast"):
                self.cfg_var_ema_fast.set(str(self.cfg.ema_fast_period))
            if hasattr(self, "cfg_var_ema_slow"):
                self.cfg_var_ema_slow.set(str(self.cfg.ema_slow_period))
            self.cfg_var_cap.set(str(int(self.cfg.initial_capital)))
            self.cfg_var_risk.set(str(int(self.cfg.risk_per_trade)))
            self.cfg_var_max_v.set(str(int(self.cfg.max_position_value)))
            self.cfg_var_max_pos.set(str(self.cfg.max_open_positions))
            self.cfg_var_max_sh.set(str(self.cfg.max_shares_per_stock))
            self.cfg_var_sl.set(str(self.cfg.stop_loss_pct))
            self.cfg_var_tgt.set(str(self.cfg.target_pct))
            self.cfg_var_trail.set(str(self.cfg.trailing_stop_pct))
            self.cfg_var_poll.set(str(self.cfg.poll_seconds))
            self.cfg_var_buf.set(str(self.cfg.close_buffer_seconds))
        except Exception as exc:
            log.warning("Reload error: %s", exc)

    def _restore_default_config_form(self):
        self.cfg_var_tf.set("15m")
        if hasattr(self, "cfg_var_strat"):
            self.cfg_var_strat.set("rlh_atr")
        if hasattr(self, "cfg_var_atr"):
            self.cfg_var_atr.set("14")
        if hasattr(self, "cfg_var_short"):
            self.cfg_var_short.set("true")
        if hasattr(self, "cfg_var_ema_fast"):
            self.cfg_var_ema_fast.set("20")
        if hasattr(self, "cfg_var_ema_slow"):
            self.cfg_var_ema_slow.set("50")
        self.cfg_var_bk.set("12")
        self.cfg_var_v_lb.set("20")
        self.cfg_var_v_m.set("1.2")
        self.cfg_var_cap.set("100000")
        self.cfg_var_risk.set("100")
        self.cfg_var_max_v.set("10000")
        self.cfg_var_max_pos.set("3")
        self.cfg_var_max_sh.set("500")
        self.cfg_var_sl.set("1.0")
        self.cfg_var_tgt.set("2.0")
        self.cfg_var_trail.set("0.75")
        self.cfg_var_poll.set("90")
        self.cfg_var_buf.set("60")

    def _reload_config_watchlist_listbox(self):
        self.cfg_listbox.delete(0, tk.END)
        for s in self.symbols_list:
            self.cfg_listbox.insert(tk.END, s)
        self.lbl_wl_count.configure(text=f"{len(self.symbols_list)} tickers")

    def _filter_watchlist_listbox(self):
        query = self.cfg_search_var.get().strip().upper()
        self.cfg_listbox.delete(0, tk.END)
        for s in self.symbols_list:
            if not query or query in s:
                self.cfg_listbox.insert(tk.END, s)

    def _add_ticker_to_watchlist(self):
        val = self.cfg_entry_sym.get().strip().upper()
        if not val:
            return
        if not val.endswith(".NS"):
            val += ".NS"
        if val in self.symbols_list:
            messagebox.showinfo("Duplicate", f"{val} is already in the watchlist.")
            return

        self.symbols_list.append(val)
        self._reload_config_watchlist_listbox()
        self._sync_all_symbol_combos()
        self.cfg_entry_sym.delete(0, "end")

    def _remove_ticker_from_watchlist(self):
        sel = self.cfg_listbox.curselection()
        if not sel:
            messagebox.showinfo("Select", "Select a symbol in the list to remove.")
            return
        sym = self.cfg_listbox.get(sel[0])
        if sym in self.symbols_list:
            self.symbols_list.remove(sym)
            self._reload_config_watchlist_listbox()
            self._sync_all_symbol_combos()

    def _save_watchlist_file(self):
        try:
            with open("watchlist.txt", "w", encoding="utf-8") as f:
                f.write("# Yahoo Finance symbols for NSE-listed shares.\n")
                for s in self.symbols_list:
                    f.write(f"{s}\n")
            messagebox.showinfo("Saved", "watchlist.txt saved successfully!")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to save watchlist: {exc}")

    def _sync_all_symbol_combos(self):
        self.combo_manual_sym.configure(values=self.symbols_list)
        self.bt_combo_sym.configure(values=self.symbols_list)

    # -------------------------------------------------------------------------
    # Shared UI Utilities
    # -------------------------------------------------------------------------
    def _create_card(self, parent, col, title, val, sub):
        card = ctk.CTkFrame(parent, fg_color=C_CARD_BG, corner_radius=8, border_width=1, border_color=C_BORDER)
        card.grid(row=0, column=col, padx=4, pady=0, sticky="nsew")

        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=10, weight="bold"), text_color=C_TEXT_SEC).pack(anchor="w", padx=10, pady=(6, 0))
        val_lbl = ctk.CTkLabel(card, text=val, font=ctk.CTkFont(size=15, weight="bold"), text_color=C_TEXT_PRI)
        val_lbl.pack(anchor="w", padx=10, pady=(0, 0))
        sub_lbl = ctk.CTkLabel(card, text=sub, font=ctk.CTkFont(size=10), text_color=C_TEXT_SEC)
        sub_lbl.pack(anchor="w", padx=10, pady=(0, 6))

        return {"val": val_lbl, "sub": sub_lbl}

    def _create_spin_row(self, parent, label_text, default_val):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(row, text=label_text, font=ctk.CTkFont(size=11), text_color=C_TEXT_SEC).pack(side="left")

        val_var = ctk.StringVar(value=str(default_val))
        entry = ctk.CTkEntry(row, textvariable=val_var, width=70, height=26, fg_color=C_INPUT_BG, border_color=C_BORDER, justify="right", font=ctk.CTkFont(size=11))
        entry.pack(side="right")
        return val_var

    def _add_divider(self, parent):
        sep = ctk.CTkFrame(parent, height=1, fg_color=C_BORDER)
        sep.pack(fill="x", padx=10, pady=8)

    def _start_periodic_refresh(self):
        def _loop():
            now = datetime.now(IST)
            self.clock_lbl.configure(text=now.strftime("%H:%M:%S IST"))

            m_open = is_market_open()
            if m_open:
                self.market_badge.configure(text="● NSE MARKET OPEN", fg_color="#064e3b", text_color=C_PROFIT)
            else:
                self.market_badge.configure(text="● NSE CLOSED", fg_color="#334155", text_color=C_TEXT_SEC)

            # Every 5 seconds refresh portfolio summary if on live tab
            if self.nav_var.get() == "🔴 Live Paper Trading Monitor":
                self._refresh_live_portfolio_ui()

            self.after(1000, _loop)

        self.after(1000, _loop)


def main():
    app = NiftyPaperTraderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
