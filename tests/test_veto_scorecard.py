"""Tests cho tools/veto_scorecard.py — counterfactual cho quyết định veto.

Thay cho trust-loop mờ của pa-model: c-bot biết CHÍNH XÁC lệnh bị veto sẽ
ra sao (replay OHLC qua backtest/fills.py với barrier đã ghi trong journal)
-> đo được veto tiết kiệm hay đốt bao nhiêu bps.
"""
import json

import numpy as np
import pytest

from tools.veto_scorecard import load_bars, load_decisions, replay, summarize

T0 = 1_700_000_000_000
MS = 60_000


def write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def make_bar(i, o, h, l, c):
    # giá trị string như bars.jsonl thật (json.dumps default=str với numpy)
    return {"t_close": str(T0 + i * MS), "open": str(o), "high": str(h),
            "low": str(l), "close": str(c), "vol_dollar": "1e7",
            "ofi": "0.1", "n_trades": "100"}


def make_signal(i, side="Buy", tp=102.0, sl=98.0, horizon=5):
    return {"kind": "signal", "wall_ms": T0 + i * MS, "side": side,
            "conf": 0.5, "entry_ref": 100.0, "tp_price": tp, "sl_price": sl,
            "horizon_bars": horizon, "t_close": T0 + i * MS,
            "prob": [0.2, 0.3, 0.5]}


def make_veto(i, approve, source="llm", reason="r"):
    return {"kind": "veto", "wall_ms": T0 + i * MS + 1, "approve": approve,
            "reason": reason, "source": source, "side": "Buy", "stats": {}}


@pytest.fixture
def journal_dir(tmp_path):
    # bar 0-1 phẳng; signal ở bar 2 (close 100); bar 3 low=99.5 -> fill;
    # bar 5 high=103 vượt TP 102 -> exit tp
    bars = [make_bar(0, 100, 100.5, 99.5, 100),
            make_bar(1, 100, 100.5, 99.5, 100),
            make_bar(2, 100, 100.5, 99.5, 100.0),
            make_bar(3, 100, 100.5, 99.5, 100),
            make_bar(4, 100, 101, 99.8, 100.8),
            make_bar(5, 101, 103.0, 100.5, 102.5),
            make_bar(6, 102, 103, 101.5, 102),
            make_bar(7, 102, 103, 101.5, 102),
            make_bar(8, 102, 103, 101.5, 102),
            make_bar(9, 102, 103, 101.5, 102)]
    write_jsonl(tmp_path / "bars.jsonl", bars)
    write_jsonl(tmp_path / "journal.jsonl", [
        make_signal(2),
        make_veto(2, approve=False, source="llm", reason="OI shock"),
    ])
    return tmp_path


class TestLoaders:
    def test_load_bars_coerces_strings(self, journal_dir):
        bars = load_bars(journal_dir / "bars.jsonl")
        assert bars["close"].dtype == np.float64
        assert bars["t_close"].iloc[0] == T0

    def test_load_decisions_pairs_signal_with_veto(self, journal_dir):
        d = load_decisions(journal_dir / "journal.jsonl")
        assert len(d) == 1
        row = d.iloc[0]
        assert row["side"] == "Buy"
        assert row["approve"] == False  # noqa: E712
        assert row["source"] == "llm"
        assert row["tp_price"] == pytest.approx(102.0)

    def test_signal_without_veto_skipped(self, tmp_path):
        write_jsonl(tmp_path / "journal.jsonl", [make_signal(2)])
        assert len(load_decisions(tmp_path / "journal.jsonl")) == 0


class TestReplay:
    def test_vetoed_buy_that_would_win(self, journal_dir):
        bars = load_bars(journal_dir / "bars.jsonl")
        d = load_decisions(journal_dir / "journal.jsonl")
        r = replay(bars, d)
        row = r.iloc[0]
        assert row["filled"]
        assert row["exit_type"] == "tp"
        assert row["net_ret"] > 0  # veto này ĐỐT tiền

    def test_vetoed_sell_that_would_lose(self, journal_dir):
        # Sell cùng cửa sổ giá tăng: SL 102 (trên entry) sẽ dính -> net âm
        write_jsonl(journal_dir / "journal.jsonl", [
            make_signal(2, side="Sell", tp=98.0, sl=102.0),
            make_veto(2, approve=False),
        ])
        bars = load_bars(journal_dir / "bars.jsonl")
        r = replay(bars, load_decisions(journal_dir / "journal.jsonl"))
        assert r.iloc[0]["net_ret"] < 0  # veto này TIẾT KIỆM tiền

    def test_summarize_groups_by_source(self, journal_dir):
        bars = load_bars(journal_dir / "bars.jsonl")
        d = load_decisions(journal_dir / "journal.jsonl")
        s = summarize(replay(bars, d))
        row = s[(s["source"] == "llm") & (s["approve"] == False)]  # noqa: E712
        assert row.iloc[0]["n"] == 1
        # veto_value = -net_ret của nhóm bị chặn (dương = tiết kiệm)
        assert row.iloc[0]["veto_value_bps"] < 0
