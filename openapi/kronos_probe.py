"""Offline Kronos OHLC-only pilot; no credentials, broker connection or trading commands."""
import argparse
import datetime as dt
import hashlib
import json
import math
import statistics
import time
from pathlib import Path


def stamp(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(dt.timezone.utc)


def windows(data, lookback=128):
    bars = sorted(data['bars'], key=lambda b: stamp(b['end']))
    if len({b['end'] for b in bars}) != len(bars):
        raise ValueError('Duplicate bar ends')
    for b in bars:
        if stamp(b['end']) - stamp(b['time']) != dt.timedelta(hours=1) or not all(math.isfinite(b[k]) and b[k] > 0 for k in ['open', 'high', 'low', 'close']):
            raise ValueError('Invalid H1 bar')
        if not b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high']:
            raise ValueError('Invalid OHLC geometry')
    by_end = {stamp(b['end']): b for b in bars}
    result = []
    for s in sorted(data['sessions'], key=lambda s: stamp(s['cutoffUtc'])):
        cutoff, until = stamp(s['cutoffUtc']), stamp(s['untilUtc'])
        context = [b for b in bars if stamp(b['end']) <= cutoff][-lookback:]
        if len(context) < lookback or stamp(context[-1]['end']) != cutoff:
            continue
        if s['horizon'] not in [8, 9] or until != cutoff + dt.timedelta(hours=s['horizon']) or s['bias'] not in [-1, 1]:
            raise ValueError('Invalid session')
        truth = by_end.get(until)
        result.append({**s, 'context': context, 'actualClose': None if truth is None else truth['close']})
    return result


def score(rows):
    labeled = [r for r in rows if r['actualClose'] is not None]
    if not labeled:
        return {'evaluated': 0}
    return {
        'evaluated': len(labeled),
        'directionAccuracy': statistics.mean((r['predictedClose'] > r['lastClose']) == (r['actualClose'] > r['lastClose']) for r in labeled),
        'asiaBiasAccuracy': statistics.mean(r['bias'] == (1 if r['actualClose'] > r['lastClose'] else -1) for r in labeled),
        'modelMAE': statistics.mean(abs(r['predictedClose'] - r['actualClose']) for r in labeled),
        'persistenceMAE': statistics.mean(abs(r['lastClose'] - r['actualClose']) for r in labeled),
        'momentumMAE': statistics.mean(abs(r['momentumClose'] - r['actualClose']) for r in labeled),
        'agreesWithAsia': statistics.mean(r['predictedDirection'] == r['bias'] for r in labeled),
    }


def infer(root):
    import numpy as np
    import pandas as pd
    import torch
    from model import Kronos, KronosTokenizer, KronosPredictor
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.manual_seed(20261114)
    np.random.seed(20261114)
    model = Kronos.from_pretrained(str(root / 'Kronos-small')).eval()
    tokenizer = KronosTokenizer.from_pretrained(str(root / 'Kronos-Tokenizer-base')).eval()
    predictor = KronosPredictor(model, tokenizer, device='cpu', max_context=512)
    dataset = json.loads((root / 'data.json').read_text())
    samples = windows(dataset)
    if not samples:
        raise ValueError('No complete causal windows')
    records = []
    timings = []
    for offset in range(0, len(samples), 8):
        batch = samples[offset:offset + 8]
        frames, xs, ys = [], [], []
        for w in batch:
            frames.append(pd.DataFrame([{k: b[k] for k in ['open', 'high', 'low', 'close']} for b in w['context']]))
            xs.append(pd.Series(pd.to_datetime([b['time'] for b in w['context']], utc=True)))
            ys.append(pd.Series(pd.date_range(stamp(w['cutoffUtc']), periods=9, freq='h')))
            assert max(stamp(b['end']) for b in w['context']) <= stamp(w['cutoffUtc'])
        begin = time.monotonic()
        with torch.inference_mode():
            preds = predictor.predict_batch(frames, xs, ys, pred_len=9, T=1.0, top_k=0, top_p=.9, sample_count=3, verbose=False)
        elapsed = time.monotonic() - begin
        timings.append(elapsed)
        for w, prediction in zip(batch, preds):
            predicted = float(prediction.iloc[w['horizon'] - 1]['close'])
            if not math.isfinite(predicted):
                raise ValueError('Nonfinite forecast')
            p0 = w['context'][-1]['close']
            # A fixed 60s entry embargo; report if actual batch runtime exceeds it.
            r = {k: v for k, v in w.items() if k != 'context'}
            r.update(lastClose=p0, predictedClose=predicted, predictedDirection=1 if predicted > p0 else -1 if predicted < p0 else 0,
                     availableUtc=(stamp(w['cutoffUtc']) + dt.timedelta(seconds=max(60, math.ceil(elapsed)))).isoformat(),
                     maxInputCloseUtc=w['context'][-1]['end'],
                     momentumClose=p0 + (p0 - w['context'][-9]['close']) * w['horizon'] / 8,
                     batchSeconds=elapsed)
            records.append(r)
        (root / 'forecasts.json').write_text(json.dumps(records, indent=2))
        print(f'Forecasts {len(records)}/{len(samples)}; batch {elapsed:.2f}s', flush=True)
    summary = {'model': 'NeoQuasar/Kronos-small', 'parameters': sum(p.numel() for p in model.parameters()),
               'lookbackH1': 128, 'pathsAveraged': 3, 'seed': 20261114, 'forecastRows': len(records),
               'maxBatchSeconds': max(timings), 'sourceSha256': hashlib.sha256((root / 'data.json').read_bytes()).hexdigest(),
               'all': score(records),
               'Asia': score([r for r in records if r['session'] == 'Asia']),
               'NewYork': score([r for r in records if r['session'] == 'NewYork']),
               'versions': {'torch': torch.__version__, 'numpy': np.__version__, 'pandas': pd.__version__},
               'sourcePin': json.loads((root / 'source.json').read_text()), 'modelPins': json.loads((root / 'models.json').read_text())}
    (root / 'forecast-summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary['all']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    infer(parser.parse_args().root.resolve())
