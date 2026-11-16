#!/usr/bin/env python3
import json
from datetime import datetime
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else 'audit/pa-trailing')
def utc(s): return datetime.fromisoformat(s.replace('Z', '+00:00'))
count = 0
for period in ('early', 'later', 'recent'):
    report = json.loads((root/period/'results.json').read_text())
    rows = report['results']
    assert report['researchOnly'] and len(rows) == 38
    static = {r['name']:r for r in rows if not r['trailSwings']}
    if period != 'recent':
        old = json.loads((root.parent/'pa-toolkit-backtest'/period/'results.json').read_text())
        assert [(x['date'],x['sha256']) for x in report['files']] == [(x['date'],x['sha256']) for x in old['files']]
        same_warmup = report['warmupFiles'] == old['warmupFiles']
        if not same_warmup:
            assert period == 'early' and old['warmupFiles'] == []
            assert [x['date'] for x in report['warmupFiles']] == ['2025-12-28','2025-12-29','2025-12-30','2025-12-31']
            print('Legacy early baseline has newly downloaded Dec28–31 warmup; compare PA static cases exactly and trailing pairs on identical current inputs.')
        for previous in old['results']:
            if not same_warmup and previous['rangeSize'] == 0:
                continue
            current = static[previous['name']]
            for key in ('trades','wins','equityNet','maxEquityDDPct','profitFactor','openPositions','commission','swap'):
                assert current[key] == previous[key], (period, key)
    for row in (r for r in rows if r['trailSwings']):
        previous = static[row['name'].removesuffix('-trail-swings')]
        for key in ('minimumEntryRR','paToolkit','rangeSize','slippageUsdOz'): assert row[key] == previous[key]
        changes = json.loads((root/period/(row['name']+'-trailing.json')).read_text())
        assert len(changes) == row['trailUpdates']
        held = {}
        used_pivots = set()
        targets = {}
        for move in changes:
            if move['entryUtc'] in targets: assert targets[move['entryUtc']] == move['target']
            targets[move['entryUtc']] = move['target']
            pivot = move['pivot']
            key = (move['entryUtc'], pivot['Index'])
            assert key not in used_pivots
            used_pivots.add(key)
            entry,known,applied = map(utc,(move['entryUtc'],pivot['KnownUtc'],move['utc']))
            assert entry < utc(pivot['PivotUtc']) <= known < applied
            assert pivot['High'] != move['buy']
            old_stop, new_stop = move['oldStop'],move['newStop']
            assert old_stop < new_stop < move['Bid'] < move['target'] if move['buy'] else old_stop > new_stop > move['Ask'] > move['target']
            if move['entryUtc'] in held: assert old_stop == held[move['entryUtc']]
            held[move['entryUtc']] = new_stop
            count += 1
        details = json.loads((root/period/(row['name']+'-range-details.json')).read_text())
        for trade in details:
            assert abs(trade['Target']-trade['paDecision']['Target']) <= .00500001
            expected = abs(trade['Target']-trade['Entry'])/abs(trade['Entry']-trade['initialStop'])
            assert abs(trade['initialRR']-expected)<1e-8
            assert expected+1e-8 >= row['minimumEntryRR']
        if row['openPositions'] == 0: assert sum(t['trailingUpdates'] for t in details) == len(changes)
print(f'Trailing audit PASS:114paired/control runs, {count}causal monotone adjustments, frozen targets/initialRR and unchanged old PA static/input-matched controls.')
