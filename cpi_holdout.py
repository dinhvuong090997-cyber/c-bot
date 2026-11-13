from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

# Historical CPI research requires the sibling xauusd-news project.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'xauusd-news'))
from study import evaluate, matched_sessions

# These are actual publication dates, taken from the BLS archive.
dates = ["2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12"]
events = pd.Series("CPI", index=[date.fromisoformat(day) for day in dates])
sessions, results = [], []
for day, event, control, pair_day in matched_sessions(events):
    files = sorted(Path("/ticks").glob(f"XAUUSD-{day:%Y-%m}-*.parquet"))
    session, fills = evaluate(ds.dataset(files, format="parquet"), day, event, control, pair_day)
    sessions.append(session)
    results.extend(row for row in fills if row["hold_min"] == 15 and row["rule"] == "fade")
pd.DataFrame(sessions).to_csv("cpi-holdout-sessions.csv", index=False)
trades = pd.DataFrame(results)
trades.to_csv("cpi-holdout-trades.csv", index=False)
print(trades.groupby(["control", "delay_s"]).net_usd_oz.agg(["count", "mean", "median"]))
