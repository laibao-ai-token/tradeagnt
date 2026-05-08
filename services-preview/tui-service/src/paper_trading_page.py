"""Paper Trading page for TUI."""

from __future__ import annotations

import curses
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3]
SERVICE_SRC = REPO_ROOT / "services" / "signal-service" / "src"
sys.path.insert(0, str(SERVICE_SRC))

from paper_trading import PaperTradingOrchestrator


def _draw_paper_trading_page(stdscr, colors: dict[str, int], w: int, h: int) -> None:
    """Render the Paper Trading dashboard."""
    stdscr.erase()
    try:
        orchestrator = PaperTradingOrchestrator()
        stats = orchestrator.get_stats()
        positions = orchestrator.get_positions()
    except Exception:
        stats = {"initial_equity": 10000.0, "current_equity": 10000.0, "total_trades": 0, "open_positions": 0, "return_pct": 0.0}
        positions = []

    header_attr = colors.get("header", curses.A_BOLD)
    stdscr.attron(header_attr)
    header = " Paper Trading "
    stdscr.addnstr(0, max(0, (w - len(header)) // 2), header, w - 1)
    stdscr.attroff(header_attr)

    y = 2
    if w > 60:
        left_w = w // 2
        right_w = w - left_w - 1
    else:
        left_w = w - 2
        right_w = 0

    # Left: Account Summary
    stdscr.attron(curses.A_BOLD)
    stdscr.addnstr(y, 1, " Account Summary ", left_w - 1)
    stdscr.attroff(curses.A_BOLD)
    y += 1
    stdscr.addnstr(y, 2, f"Initial Equity:  ${stats['initial_equity']:,.2f}", left_w - 2)
    y += 1
    stdscr.addnstr(y, 2, f"Current Equity:  ${stats['current_equity']:,.2f}", left_w - 2)
    y += 1
    ret = stats['return_pct']
    ret_str = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
    stdscr.addnstr(y, 2, f"Total Return:    {ret_str}", left_w - 2)
    y += 1
    stdscr.addnstr(y, 2, f"Total Trades:    {stats['total_trades']}", left_w - 2)
    y += 1
    stdscr.addnstr(y, 2, f"Open Positions:  {stats['open_positions']}", left_w - 2)

    # Right: Positions
    if right_w > 0:
        y_pos = 2
        stdscr.attron(curses.A_BOLD)
        stdscr.addnstr(y_pos, left_w + 2, " Current Positions ", right_w - 2)
        stdscr.attroff(curses.A_BOLD)
        y_pos += 1
        if positions:
            for pos in positions[:h - 5]:
                side = pos['side']
                color = curses.color_pair(2) if side == "LONG" else curses.color_pair(1)
                stdscr.attron(color)
                stdscr.addnstr(y_pos, left_w + 2, f"{pos['symbol']} {side} {pos['qty']:.2f} @ ${pos['entry_price']:,.2f}", right_w - 3)
                stdscr.attroff(color)
                y_pos += 1
        else:
            stdscr.addnstr(y_pos, left_w + 2, "No open positions", right_w - 2)

    # Footer
    footer_y = h - 2
    stdscr.attron(curses.A_DIM)
    stdscr.addnstr(footer_y, 1, " [p] positions  [s] stats  [r] reset  [q] back ", w - 2)
    stdscr.attroff(curses.A_DIM)

    stdscr.refresh()
