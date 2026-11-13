#!/usr/bin/env python3
"""Verify exported historical bid ticks against independently requested FxPro M1 bars."""
from collections import Counter
import gzip
import json
from pathlib import Path

folder = Path(__file__).resolve().parent / 'data' / 'fxpro-v2'
bars = json.loads((folder / 'audit-bars.json').read_text())['trendbar']
series = {}
with gzip.open(folder / 'XAUUSD-2026-01-02.csv.gz', 'rt') as source:
    next(source)
    for line in source:
        stamp, side, price = map(int, line.split(','))
        if side != 1:
            continue
        minute = stamp // 60000
        if minute not in series:
            series[minute] = [price, price, Counter({(stamp, price): 1})]
        else:
            sample = series[minute]
            sample[0] = min(sample[0], price)
            sample[1] = max(sample[1], price)
            sample[2][(stamp, price)] += 1
rows = []
for bar in bars:
    minute = int(bar['utcTimestampInMinutes'])
    sample = series.get(minute)
    low = int(bar['low'])
    high = low + int(bar.get('deltaHigh', 0))
    rows.append({'minute': minute, 'lowMatches': sample is not None and sample[0] == low,
                 'highMatches': sample is not None and sample[1] == high,
                 'maxDifferenceUsd': max(abs(sample[0] - low), abs(sample[1] - high)) / 1e5 if sample else None})
direct = []
for check in json.loads((folder / 'audit-direct-minutes.json').read_text()):
    stamp = price = 0
    expected = Counter()
    for tick in check['response'].get('tickData', []):
        stamp += int(tick['timestamp']); price += int(tick['tick'])
        expected[(stamp, price)] += 1
    minute = next(iter(expected))[0] // 60000
    matched = series[minute][2] == expected
    direct.append({'minute': minute, 'exactTickMatch': matched})
    assert matched, 'Direct minute replay differs from cached ticks'
result = {'checkedBars': len(rows), 'lowMatches': sum(r['lowMatches'] for r in rows),
          'highMatches': sum(r['highMatches'] for r in rows), 'bars': rows, 'directMinuteChecks': direct,
          'maxBarDifferenceUsd': max(r['maxDifferenceUsd'] or 0 for r in rows)}
(folder / 'audit-result.json').write_text(json.dumps(result, indent=2))
print({key: value for key, value in result.items() if key not in ('bars', 'directMinuteChecks')})
assert result['checkedBars'] > 1000, 'Expected full trading day of M1 data'
# FxPro's independently stored bars contain three small extrema differences even
# when the direct tick endpoint exactly matches the export. Preserve this in the report.
assert result['maxBarDifferenceUsd'] <= 0.05, 'Unexpected price-scale or pagination discrepancy'
