#!/usr/bin/env python3
"""Standalone Paper Trading TUI viewer."""

from __future__ import annotations

import curses
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[1]
SERVICE_SRC = REPO_ROOT / "services" / "signal-service" / "src"
sys.path.insert(0, str(SERVICE_SRC))

from paper_trading import PaperTradingOrchestrator


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    
    orchestrator = PaperTradingOrchestrator()
    
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        
        stats = orchestrator.get_stats()
        positions = orchestrator.get_positions()
        
        header = " Paper Trading Dashboard "
        stdscr.attron(curses.A_BOLD | curses.A_REVERSE)
        stdscr.addnstr(0, max(0, (w - len(header)) // 2), header, w - 1)
        stdscr.attroff(curses.A_BOLD | curses.A_REVERSE)
        
        y = 2
        if w > 60:
            left_w = w // 2
        else:
            left_w = w - 2
        
        stdscr.attron(curses.A_BOLD)
        stdscr.addnstr(y, 1, " Account Summary ", left_w - 1)
        stdscr.attroff(curses.A_BOLD)
        y += 1
        
        lines = [
            f"Initial Equity:  ${stats['initial_equity']:,.2f}",
            f"Current Equity:  ${stats['current_equity']:,.2f}",
            f"Total Return:    {stats['return_pct']:+.2f}%",
            f"Total Trades:    {stats['total_trades']}",
            f"Open Positions:  {stats['open_positions']}",
        ]
        for line in lines:
            if y < h - 2:
                stdscr.addnstr(y, 2, line, left_w - 2)
                y += 1
        
        if w > 60:
            right_w = w - left_w - 1
            ry = 2
            stdscr.attron(curses.A_BOLD)
            stdscr.addnstr(ry, left_w + 2, " Current Positions ", right_w - 2)
            stdscr.attroff(curses.A_BOLD)
            ry += 1
            if positions:
                for pos in positions[:h - 5]:
                    side = pos['side']
                    txt = f"{pos['symbol']} {side} {pos['qty']:.2f} @ ${pos['entry_price']:,.2f}"
                    stdscr.addnstr(ry, left_w + 2, txt, right_w - 3)
                    ry += 1
            else:
                stdscr.addnstr(ry, left_w + 2, "No open positions", right_w - 2)
        
        stdscr.attron(curses.A_DIM)
        stdscr.addnstr(h - 2, 1, " [q] quit  [r] refresh ", w - 2)
        stdscr.attroff(curses.A_DIM)
        
        stdscr.refresh()
        
        key = stdscr.getch()
        if key == ord('q') or key == ord('Q'):
            break
        time.sleep(0.5)


if __name__ == "__main__":
    curses.wrapper(main)
