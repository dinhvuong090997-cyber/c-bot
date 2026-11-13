"""CPI fade, quoted tick execution and account sizing sensitivity."""
from math import floor
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

sys.path.insert(0, "/prior")
from study import COMMISSION, SECOND, event_time, session_quotes

RISK = 0.0025
DRAWDOWN_LIMIT = 0.05
SCENARIOS = {"quoted": (0, 0), "base": (1, 0.10), "stress": (3, 0.25)}


def signals(day):
    release = event_time(day)
    files = sorted(Path("/prior/ticks").glob(f"XAUUSD-{day:%Y-%m}-*.parquet"))
    if not files:
        raise FileNotFoundError(f"No tick partition for {day:%Y-%m}")
    ts, bid, ask = session_quotes(ds.dataset(files, format="parquet"), release)
    spread = ask - bid
    before = (ts >= release - 300 * SECOND) & (ts < release)
    if before.sum() < 30:
        return
    pre = np.searchsorted(ts, release) - 1
    minute = release + 60 * SECOND
    post = np.searchsorted(ts, minute, side="right") - 1
    if release - ts[pre] > 5 * SECOND or minute - ts[post] > 5 * SECOND:
        return
    mid = (bid + ask) / 2
    move = mid[post] - mid[pre]
    if move == 0:
        return
    window_end = release + 300 * SECOND
    eligible = np.flatnonzero(
        (ts >= minute) & (ts <= window_end)
        & (spread <= 1.5 * np.median(spread[before]) + 1e-9)
    )
    if not len(eligible):
        return

    signal = eligible[0]
    side = -1 if move > 0 else 1
    entry_quotes, exit_quotes = (ask, bid) if side == 1 else (bid, ask)
    # Size against the first-minute shock, with a $2/oz minimum distance.
    stop_distance = max(2, abs(move))
    for scenario, (delay, slip) in SCENARIOS.items():
        entry = np.searchsorted(ts, ts[signal] + delay * SECOND, side="right" if delay == 0 else "left")
        if entry >= len(ts) or ts[entry] > window_end or ts[entry] - ts[signal] > (delay + 5) * SECOND:
            continue
        fill = entry_quotes[entry] + side * slip
        exit_due = ts[entry] + 900 * SECOND
        deadline = np.searchsorted(ts, exit_due)
        if deadline >= len(ts) or ts[deadline] - exit_due > 5 * SECOND:
            continue
        trigger = np.flatnonzero(side * (exit_quotes[entry:deadline] - fill) <= -stop_distance)
        if len(trigger):
            exit_due = ts[entry + trigger[0]]
        # Timed and stop exits both incur market-order latency and slippage.
        end = np.searchsorted(ts, exit_due + delay * SECOND)
        if end >= len(ts) or ts[end] - exit_due > (delay + 5) * SECOND:
            continue
        marked = side * (exit_quotes[entry:end + 1] - fill) - slip - COMMISSION
        yield dict(date=day, scenario=scenario, side=side, first_minute_move=move,
                   signal_ms=int(ts[signal]), entry_ms=int(ts[entry]), exit_ms=int(ts[end]),
                   signal_price=float(entry_quotes[signal]), fill_price=float(fill),
                   stop_distance=float(stop_distance), planned_loss_per_oz=stop_distance+slip+COMMISSION,
                   net_per_oz=float(marked[-1]), mae_per_oz=min(0, float(marked.min())),
                   reason="stop" if len(trigger) else "time")


def size_orders(trades, start):
    cash = peak = float(start)
    for order in trades.itertuples(index=False):
        # Estimate quantity when the signal is generated. Reserve 1% price
        # headroom for the notional cap rather than using the later fill quote.
        qty = floor(min(cash * RISK / order.planned_loss_per_oz,
                        cash / (1.01 * order.signal_price)))
        if qty < 1:
            continue
        budget = cash * RISK
        notional_pct = 100 * qty * order.fill_price / cash
        intratrade_drawdown = 100 * (peak - cash - qty * order.mae_per_oz) / peak
        pnl = qty * order.net_per_oz
        cash += pnl
        peak = max(peak, cash)
        closed_drawdown = 100 * (peak - cash) / peak
        yield dict(**order._asdict(), start_usd=start, qty_oz=qty, planned_budget_usd=budget,
                   notional_pct=notional_pct, net_usd=pnl, equity_usd=cash,
                   closed_drawdown_pct=closed_drawdown, intratrade_drawdown_pct=intratrade_drawdown,
                   loss_exceeded_budget=pnl < -budget)
        if closed_drawdown >= DRAWDOWN_LIMIT * 100:
            break


def main():
    history = pd.read_csv("cpi-history.csv").date
    prior = pd.read_csv("/prior/events.csv").query("event == 'CPI'").date
    fresh = pd.read_csv("cpi-holdout-sessions.csv").query("control == False").date
    days = sorted(set(history) | set(prior) | set(fresh))
    assert len(days) == 52
    rows = [trade for day in days for trade in signals(pd.Timestamp(day).date())]
    trades = pd.DataFrame(rows)
    trades["period"] = trades.date.map(lambda day: (
        "2022–23 retrospective" if day.year <= 2023 else str(day.year)
    ))
    trades.to_csv("cpi-sized-fills.csv", index=False)
    orders = []
    for scenario, group in trades.groupby("scenario", sort=False):
        for period, sample in [("all", group), *group.groupby("period", sort=False)]:
            for start in (50000, 100000):
                orders.extend(dict(row, run_period=period) for row in size_orders(sample, start))
    orders = pd.DataFrame(orders)
    orders.to_csv("cpi-sized-orders.csv", index=False)
    metrics = orders.groupby(["run_period", "scenario", "start_usd"]).agg(
        trades=("net_usd", "size"), net_usd=("net_usd", "sum"),
        drawdown_pct=("closed_drawdown_pct", "max"),
        intratrade_drawdown_pct=("intratrade_drawdown_pct", "max"),
        max_qty_oz=("qty_oz", "max"), max_notional_pct=("notional_pct", "max"),
        loss_breaches=("loss_exceeded_budget", "sum"),
    )
    metrics.to_csv("cpi-capital.csv")
    print(f"Found {trades.date.nunique()} of {len(days)} events with at least one scenario.")
    print(metrics.round(3).to_string())


if __name__ == "__main__":
    main()
