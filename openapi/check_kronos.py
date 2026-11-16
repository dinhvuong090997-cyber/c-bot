import datetime as dt
import unittest
from kronos_probe import windows, stamp, score

class CausalityChecks(unittest.TestCase):
    def setUp(self):
        t = dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc)
        self.bars = [{'time': (t+dt.timedelta(hours=i)).isoformat(), 'end': (t+dt.timedelta(hours=i+1)).isoformat(), 'open': 100+i, 'high': 102+i, 'low': 99+i, 'close': 101+i} for i in range(150)]
        self.cutoff = t+dt.timedelta(hours=128)
        self.session = {'cutoffUtc': self.cutoff.isoformat(), 'untilUtc': (self.cutoff+dt.timedelta(hours=8)).isoformat(), 'horizon': 8, 'bias': 1, 'session': 'Asia'}
    def test_no_future_or_incomplete_hour_in_context(self):
        w = windows({'bars': self.bars, 'sessions': [self.session]})[0]
        self.assertEqual(len(w['context']), 128)
        self.assertTrue(all(stamp(b['end']) <= self.cutoff for b in w['context']))
        changed = [dict(b) for b in self.bars]
        for b in changed[128:]:
            b.update(open=9999, high=9999, low=9999, close=9999)
        self.assertEqual(w['context'], windows({'bars': changed, 'sessions': [self.session]})[0]['context'])
    def test_missing_last_closed_bar_is_not_forward_filled(self):
        self.assertEqual(windows({'bars': self.bars[:127], 'sessions': [self.session]}), [])
    def test_duplicate_and_invalid_geometry_rejected(self):
        with self.assertRaises(ValueError): windows({'bars': self.bars+[self.bars[0]], 'sessions': [self.session]})
        self.bars[0]['high'] = 1
        with self.assertRaises(ValueError): windows({'bars': self.bars, 'sessions': [self.session]})
    def test_no_truth_is_not_scored(self):
        self.assertEqual(score([{'actualClose': None}]), {'evaluated': 0})

if __name__ == '__main__': unittest.main()
