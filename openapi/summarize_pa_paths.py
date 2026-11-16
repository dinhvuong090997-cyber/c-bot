#!/usr/bin/env python3
"""Validate and describe PA outcomes; does not fit thresholds or claim trading P&L."""
import collections
from datetime import datetime
import json
from pathlib import Path
import statistics
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else 'audit/pa-paths')
def utc(value): return datetime.fromisoformat(value.replace('Z', '+00:00'))
def describe(rows):
    outcomes = collections.Counter(r['threeROutcome'] for r in rows)
    complete = [r for r in rows if r['completeHorizon']]
    resolved = sum(outcomes[k] for k in ('3r', 'sl', 'time'))
    entered = [r for r in rows if r['entryUtc']]
    intervals = [(utc(r['entryUtc']), utc(r['horizonUtc'] if r['completeHorizon'] else r['lastQuoteUtc'])) for r in entered if r['lastQuoteUtc']]
    overlap = sum(any(j != i and a < d and c < b for j, (c, d) in enumerate(intervals)) for i, (a, b) in enumerate(intervals))
    return dict(events=len(rows), outcomes=dict(outcomes), resolved=resolved,
                threeRPercent=100*outcomes['3r']/resolved if resolved else None,
                completeHorizons=len(complete), medianMfeR=statistics.median(r['mfeR'] for r in complete) if complete else None,
                medianMaeR=statistics.median(r['maeR'] for r in complete) if complete else None,
                dates=len({r['signalUtc'][:10] for r in rows}), overlappingWindows=overlap,
                overlapDenominator=len(intervals))

summary = {}
total_signals = 0
total_paths = 0
for period in ('early', 'later', 'fresh'):
    rows = json.loads((root/period/'paths.json').read_text())
    manifest = json.loads((root/period/'manifest.json').read_text())
    assert len(rows) == 2*manifest['signals']
    total_signals += manifest['signals']
    total_paths += len(rows)
    pairs = collections.defaultdict(dict)
    for r in rows:
        pairs[r['range'], r['signalUtc']][r['horizonMinutes']] = r
        decision = r['decision']
        assert utc(decision['confirmedUtc']) == utc(r['signalUtc'])
        if decision['targetKnownUtc']: assert utc(decision['targetKnownUtc']) <= utc(r['signalUtc'])
        if not r['entryUtc']:
            assert r['censorReason'] in ('entry-unavailable', 'end-of-data')
            assert r['threeROutcome'] == 'censored'
            continue
        delay = (utc(r['entryUtc'])-utc(r['signalUtc'])).total_seconds()
        assert 1 <= delay <= 6
        assert r['risk'] >= 3-1e-8
        assert abs(abs(r['hypothetical3RTarget']-r['entry']) / r['risk'] - 3) < 1e-7
        assert r['stop'] < r['entry'] < r['hypothetical3RTarget'] if r['buy'] else r['hypothetical3RTarget'] < r['entry'] < r['stop']
        if r['threeRTouchUtc']: assert utc(r['entryUtc']) <= utc(r['threeRTouchUtc']) <= utc(r['horizonUtc'])
        if r['lastQuoteUtc']: assert utc(r['lastQuoteUtc']) <= utc(r['horizonUtc'])
        assert r['mfeR'] >= 0 and r['maeR'] >= 0
        assert r['completeHorizon'] == (r['censorReason'] is None)
    for pair in pairs.values():
        a, b = pair[5], pair[30]
        assert a['entryUtc'] == b['entryUtc'] and a['stop'] == b['stop']
        if a['threeROutcome'] in ('3r', 'sl'): assert a['threeROutcome'] == b['threeROutcome'] and a['threeRTouchUtc'] == b['threeRTouchUtc']
        if b['completeHorizon']: assert b['maeR']+1e-9 >= a['maeR'] and b['mfeR']+1e-9 >= a['mfeR']
    summary[period] = []
    for horizon in (5, 30):
        for size in (2, 3, 5):
            base = [r for r in rows if r['range'] == size and r['horizonMinutes'] == horizon]
            eligible = [r for r in base if r['spreadAllowed'] and r['rangeSignalValidAtEntry'] and r['signalSession'] != 'Closed']
            aligned = [r for r in eligible if r['decision']['regime'] == ('Uptrend' if r['buy'] else 'Downtrend')]
            groups = {'all':base, 'basic':eligible, 'aligned':aligned}
            for regime in sorted({r['decision']['regime'] for r in eligible}): groups['regime:'+regime] = [r for r in eligible if r['decision']['regime'] == regime]
            for session in sorted({r['signalSession'] for r in eligible}): groups['session:'+session] = [r for r in eligible if r['signalSession'] == session]
            for group, items in groups.items(): summary[period].append(dict(horizon=horizon, range=size, group=group, **describe(items)))
    if period != 'fresh':
        previous = json.loads((root.parent/'pa-toolkit-backtest'/period/'results.json').read_text())
        for size in (2, 3, 5):
            old = next(r for r in previous['results'] if r['rangeSize'] == size and r['paToolkit'] == 'regime' and r['slippageUsdOz'] == .1)
            assert sum(r['range'] == size and r['horizonMinutes'] == 5 for r in rows) == old['paSignals']
(root/'summary.json').write_text(json.dumps(summary, indent=2))
print(f'PA path audit PASS:{total_signals}signal events/{total_paths}horizon paths, frozen decisions, no future fills, gap censoring, first-touch consistency and unchanged prior signal inventory.')
for period, groups in summary.items():
    primary = next(g for g in groups if g['range'] == 3 and g['horizon'] == 30 and g['group'] == 'basic')
    print(period, json.dumps(primary))
