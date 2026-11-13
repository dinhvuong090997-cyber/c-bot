from datetime import datetime, time, timezone
from itertools import groupby
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from study import MS, SCENARIOS, equity_curve, simulate


def utc_ms(day, hour):
    return int(datetime.combine(day, time(hour), timezone.utc).timestamp() * MS)


def evaluate(frame, day):
    ts = frame.timestamp.to_numpy(dtype="datetime64[ms]").astype("int64")
    bid, ask = frame.bid_price.to_numpy(), frame.ask_price.to_numpy()
    mid, spread = (bid + ask) / 2, ask - bid
    midnight, opened, cutoff = [utc_ms(day, hour) for hour in (0, 8, 10)]
    prior_end = np.searchsorted(ts, opened)
    if prior_end < 100 or ts[0] - midnight > 60 * MS or opened - ts[prior_end-1] > 5 * MS:
        return
    prior_spread = spread[:prior_end][ts[:prior_end] >= opened - 300 * MS]
    direction = np.sign(mid[prior_end-1] - mid[0])
    if not direction or len(prior_spread) < 30:
        return
    candidates = np.flatnonzero(
        (ts >= opened) & (ts <= opened + 60 * MS)
        & (spread <= 1.5 * np.median(prior_spread) + 1e-9)
    )
    if not len(candidates):
        return
    signal = candidates[0]
    distance = max(2.0, 0.5 * np.ptp(mid[:prior_end]))
    for scenario, (delay, slip) in SCENARIOS.items():
        for rule, side in (("momentum", direction), ("reversal", -direction),
                           ("always_long", 1), ("always_short", -1)):
            fill = simulate(ts, bid, ask, signal, side, distance, cutoff, delay, slip,
                            target_multiple=None)
            if fill is not None:
                entry, net, reason = fill
                yield dict(date=day, scenario=scenario, rule=rule, side=int(side), entry=entry,
                           signal_price=float(ask[signal] if side == 1 else bid[signal]),
                           risk_distance=distance, net_usd_oz=net, reason=reason)


def main():
    rows = []
    files = sorted(Path("/ticks").glob("XAUUSD-*.parquet"))
    for month, paths in groupby(files, key=lambda path: path.name[7:14]):
        if month >= "2026-05":
            break
        frame = ds.dataset(list(paths), format="parquet").to_table(
            columns=["timestamp", "bid_price", "ask_price"]
        ).to_pandas()
        utc = frame.timestamp
        frame = frame.loc[(utc.dt.hour <= 10) & (utc.dt.dayofweek < 5)
                          & np.isfinite(frame.bid_price) & np.isfinite(frame.ask_price)
                          & (frame.bid_price > 0) & (frame.ask_price >= frame.bid_price)]
        frame = frame.sort_values("timestamp", kind="stable")
        for day, sample in frame.groupby(frame.timestamp.dt.date, sort=True):
            rows.extend(evaluate(sample, day))
        print(month, len(rows), flush=True)
    trades = pd.DataFrame(rows)
    trades["period"] = trades.date.map(lambda day: (
        "2022–23" if day.year <= 2023 else "2024–25" if day.year <= 2025 else "2026 Jan–Apr"
    ))
    trades.to_csv("session-trades.csv", index=False)
    results = []
    for (scenario, rule), group in trades.groupby(["scenario", "rule"]):
        for period, sample in [("all", group), *group.groupby("period", sort=False)]:
            for start in (50000, 100000):
                results.append(dict(period=period, scenario=scenario, rule=rule,
                                    **equity_curve(sample, start, 0.05)))
    results = pd.DataFrame(results)
    results.to_csv("session-capital.csv", index=False)
    print(results.query("starting_usd == 100000 and scenario != 'quoted'").round(3).to_string(index=False))


if __name__ == "__main__":
    main()
