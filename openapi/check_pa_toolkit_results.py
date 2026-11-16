#!/usr/bin/env python3
"""Audit offline PA ledgers; never connects to broker or activates execution."""
import json
import math
from pathlib import Path
import sys
from datetime import datetime

def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

root = Path(sys.argv[1] if len(sys.argv) > 1 else 'audit/pa-toolkit-backtest')
checked = 0
for period in ('early', 'later', 'new-day'):
    folder = root / period
    report = json.loads((folder / 'results.json').read_text())
    assert report['researchOnly'] is True
    assert len(report['results']) == 20
    for run in report['results']:
        if not run['paToolkit']:
            continue
        attempts = json.loads((folder / (run['name'] + '-pa-attempts.json')).read_text())
        opens = [a for a in attempts if a['reason'] == 'opened']
        assert len(opens) == run['trades'] + run['openPositions']
        for attempt in attempts:
            decision = attempt['decision']
            assert utc(decision['ConfirmedUtc']) <= utc(attempt['utc'])
            if decision['TargetKnownUtc'] is not None:
                assert utc(decision['TargetKnownUtc']) <= utc(decision['ConfirmedUtc'])
            if attempt['reason'] != 'opened':
                continue
            entry, stop, target = attempt['entry'], attempt['stop'], attempt['target']
            assert (stop < entry < target) if attempt['buy'] else (target < entry < stop)
            assert abs(entry - stop) >= 3 - 1e-8
            assert math.isclose(target, decision['Target'], abs_tol=.00500001)
            rr = abs(target - entry) / abs(entry - stop)
            assert rr >= run['minimumEntryRR'] - 1e-8
            if run['paToolkit'] == 'regime':
                assert decision['Regime'] == ('Uptrend' if attempt['buy'] else 'Downtrend')
            checked += 1
    if period in ('early', 'later'):
        previous = json.loads((root.parent / 'range-pa' / ('min3r-' + period) / 'results.json').read_text())
        for control in [r for r in report['results'] if r['rangeSize'] == 0]:
            old = next(r for r in previous['results'] if r['rangeSize'] == 0 and r['slippageUsdOz'] == control['slippageUsdOz'])
            for key in ('trades', 'wins', 'equityNet', 'maxEquityDDPct', 'profitFactor', 'openPositions', 'commission', 'swap'):
                assert old[key] == control[key], (period, key, old[key], control[key])
print(f'PA result audit PASS:60runs, {checked}opened entries, frozen causal targets, correct side/minSL/RR/regime and unchanged legacy baselines.')
