from datetime import datetime, time, timedelta
from itertools import groupby
from math import floor
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

LONDON = ZoneInfo("Europe/London")
MS = 1000
COMMISSION = 0.07
SCENARIOS = {"quoted": (0, 0), "base": (1, 0.10), "stress": (3, 0.25)}


def london_ms(day, hour, minute=0):
    return int(datetime.combine(day, time(hour, minute), LONDON).timestamp() * MS)


def simulate(ts, bid, ask, signal, side, risk_distance, cutoff, delay, slip, target_multiple=1.5):
    entry = np.searchsorted(ts, ts[signal] + delay * MS, side="right" if delay == 0 else "left")
    if entry >= len(ts) or ts[entry] >= cutoff or ts[entry] - ts[signal] > (delay + 5) * MS:
        return None
    entry_price = (ask[entry] + slip) if side == 1 else (bid[entry] - slip)
    close_quotes = bid if side == 1 else ask
    deadline = np.searchsorted(ts, cutoff)
    if deadline >= len(ts) or ts[deadline] - cutoff > 5 * MS:
        return None
    marked = side * (close_quotes[entry:deadline] - entry_price)
    target = np.inf if target_multiple is None else target_multiple * risk_distance
    barriers = np.flatnonzero((marked <= -risk_distance) | (marked >= target))
    if len(barriers):
        offset = barriers[0]
        reason = "stop" if marked[offset] <= -risk_distance else "target"
        if reason == "stop":
            trigger = entry + offset
            exit_index = np.searchsorted(ts, ts[trigger] + delay * MS, side="left")
        else:
            # Limit target credited at its limit, without positive price improvement.
            return entry_price, target - COMMISSION, reason
    else:
        reason = "time"
        exit_index = np.searchsorted(ts, cutoff + delay * MS)
    if exit_index >= len(ts):
        return None
    return entry_price, side * (close_quotes[exit_index] - entry_price) - slip - COMMISSION, reason


def opportunities(frame, day):
    ts = frame.timestamp.to_numpy(dtype="datetime64[ms]").astype("int64")
    bid, ask = frame.bid_price.to_numpy(), frame.ask_price.to_numpy()
    midpoint, spread = (bid + ask) / 2, ask - bid
    start, opened = london_ms(day, 8), london_ms(day, 8, 15)
    end_entry, cutoff = london_ms(day, 9), london_ms(day, 10)
    initial = (ts >= start) & (ts < opened)
    if initial.sum() < 100 or not np.any(initial & (ts < start + 60 * MS)) or not np.any(initial & (ts >= opened - 60 * MS)):
        return
    low, high = midpoint[initial].min(), midpoint[initial].max()
    width = high - low
    if width <= 0:
        return
    outside = (midpoint >= high + 0.05 * width) | (midpoint <= low - 0.05 * width)
    candidates = np.flatnonzero(
        (ts >= opened) & (ts < end_entry) & outside & (spread <= 1.5 * np.median(spread[initial]) + 1e-9)
    )
    if not len(candidates):
        return
    signal = candidates[0]
    direction = 1 if midpoint[signal] > high else -1
    risk_distance = max(1, 0.5 * width)
    for scenario, (delay, slip) in SCENARIOS.items():
        for rule, side in (("breakout", direction), ("fade", -direction)):
            fill = simulate(ts, bid, ask, signal, side, risk_distance, cutoff, delay, slip)
            if fill is not None:
                entry, net, reason = fill
                yield dict(date=day, scenario=scenario, rule=rule, side=side, entry=entry, signal_price=float(ask[signal] if side == 1 else bid[signal]),
                           risk_distance=risk_distance, net_usd_oz=net, reason=reason)


def month_trades(paths):
    dataset = ds.dataset(paths, format="parquet")
    batch = dataset.to_table(columns=["timestamp", "bid_price", "ask_price"]).to_pandas()
    utc = batch.timestamp
    # London 08:00–10:00 is contained in this UTC window in both DST regimes.
    mask = (utc.dt.hour >= 7) & (utc.dt.hour <= 10) & (utc.dt.dayofweek < 5)
    batch = batch.loc[mask & np.isfinite(batch.bid_price) & np.isfinite(batch.ask_price)
                      & (batch.bid_price > 0) & (batch.ask_price >= batch.bid_price)]
    batch = batch.sort_values("timestamp", kind="stable")
    for day, frame in batch.groupby(batch.timestamp.dt.date, sort=True):
        yield from opportunities(frame, day)


def equity_curve(trades, starting, halt_limit):
    cash = peak = starting
    worst_drawdown = 0.0
    max_oz = 0
    returns = []
    stopped = False
    slip = SCENARIOS[trades.scenario.iloc[0]][1]
    for row in trades.itertuples():
        risk_per_oz = row.risk_distance + COMMISSION + slip
        oz = floor(min(cash * 0.0025 / risk_per_oz, cash / (1.01 * row.signal_price)))
        if oz < 1:
            continue
        pnl = oz * row.net_usd_oz
        returns.append(pnl)
        max_oz = max(max_oz, oz)
        cash += pnl
        peak = max(peak, cash)
        worst_drawdown = max(worst_drawdown, (peak - cash) / peak)
        if halt_limit is not None and worst_drawdown >= halt_limit:
            stopped = True
            break
    return dict(starting_usd=starting, halted=stopped, halt_enabled=halt_limit is not None,
                trades=len(returns), net_usd=cash-starting, return_pct=100*(cash/starting-1),
                drawdown_pct=100*worst_drawdown, max_oz=max_oz,
                wins=sum(pnl > 0 for pnl in returns))


def main():
    rows = []
    paths = sorted(path for year in (2024, 2025) for path in Path("/ticks").glob(f"XAUUSD-{year}-*.parquet"))
    for month, files in groupby(paths, key=lambda path: path.name[7:14]):
        rows.extend(month_trades(list(files)))
        print(month, len(rows), flush=True)
    trades = pd.DataFrame(rows)
    trades["year"] = trades.date.map(lambda day: day.year)
    trades.to_csv("trades.csv", index=False)
    stats = []
    for (year, scenario, rule), group in trades.groupby(["year", "scenario", "rule"]):
        for starting in (50000, 100000):
            for halt_limit in (None, 0.05):
                stats.append(dict(year=year, scenario=scenario, rule=rule,
                                  **equity_curve(group, starting, halt_limit)))
    report = pd.DataFrame(stats)
    report.to_csv("capital.csv", index=False)
    print(report.loc[report.halt_enabled & report.starting_usd.eq(100000)].to_string(index=False))


if __name__ == "__main__":
    main()
