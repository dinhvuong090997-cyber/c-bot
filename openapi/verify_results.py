#!/usr/bin/env python3
"""Independent accounting and execution-rule checks on completed replay reports."""
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

folder = Path(sys.argv[1])
root = json.loads((folder / 'results.json').read_text())
assert root['dataVersion'] == 2
ny = ZoneInfo('America/New_York')
checked = 0
for row in root['results']:
    trades = json.loads((folder / (row['name'] + '-trades.json')).read_text())
    daily = json.loads((folder / (row['name'] + '-daily.json')).read_text())
    assert len(trades) == row['trades'] == row['wins'] + row['losses']
    previous_exit = None
    for trade in trades:
        entry = datetime.fromisoformat(trade['entryUtc'].replace('Z', '+00:00'))
        exit_ = datetime.fromisoformat(trade['exitUtc'].replace('Z', '+00:00'))
        assert entry <= exit_
        assert previous_exit is None or entry >= previous_exit, 'Overlapping positions'
        previous_exit = exit_
        assert entry.weekday() < 5
        assert trade['reason'] in ('SL', 'TP')
        assert trade['volumeOz'] >= 1 and trade['volumeOz'].is_integer()
        if trade['session'] == 'Asia':
            assert 0 <= entry.hour < 8
        else:
            assert trade['session'] == 'NewYork' and 8 <= entry.astimezone(ny).hour < 17
        assert math.isclose(trade['net'], trade['gross'] - trade['commission'] + trade['swap'], abs_tol=1e-7)
    if row['openPositions'] == 0:
        assert math.isclose(sum(t['net'] for t in trades), row['closedNet'], abs_tol=1e-5)
        assert math.isclose(sum(t['commission'] for t in trades), row['commission'], abs_tol=1e-5)
        assert math.isclose(sum(t['swap'] for t in trades), row['swap'], abs_tol=1e-5)
    assert all(a['date'] < b['date'] for a, b in zip(daily, daily[1:]))
    if daily:
        assert math.isclose(daily[-1]['equity'] - row['initial'], row['equityNet'], abs_tol=1e-5)
    if row['halted']:
        assert row['haltUtc'] is not None and row['maxClosedDDPct'] >= row.get('maxDrawdownPercent', 5)
    checked += 1
print(f'PASS: {checked} runs; accounting, no overlapping positions, entry sessions, exits, volume, daily equity, drawdown halt.')
