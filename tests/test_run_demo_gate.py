"""Tests cho DemoRunner._act_on_signal — thứ tự gate sau khi có tín hiệu:
LLM veto (nếu bật) -> risk rules -> TradeManager.submit.
"""
import json

import pandas as pd
import pytest

from live.run_demo import DemoRunner
from live.signal import Signal
from llm.veto import VetoDecision
from risk.rules import RiskConfig, RiskManager

T0 = 1_700_000_000_000


class StubTM:
    state = "IDLE"

    def __init__(self):
        self.submitted = []

    def submit(self, sig):
        self.submitted.append(sig)
        return True


class StubVeto:
    def __init__(self, approve, reason="r", source="llm"):
        self.decision = VetoDecision(approve, reason, source)
        self.calls = []

    def review(self, bars, feat, sig):
        self.calls.append(sig)
        return self.decision


def make_sig(side="Buy"):
    return Signal(side=side, conf=0.5, entry_ref=100.0, tp_price=101.0,
                  sl_price=99.0, horizon_bars=80, t_close=T0)


def make_runner(tmp_path, veto=None):
    tm = StubTM()
    rm = RiskManager(RiskConfig())
    runner = DemoRunner(engine=None, tm=tm, rm=rm, journal_dir=tmp_path,
                        symbol="BTCUSDT", dry_ex=None, veto=veto)
    runner.bars = pd.DataFrame({"t_close": [T0], "close": [100.0]})
    return runner, tm, rm


def read_journal(tmp_path):
    lines = (tmp_path / "journal.jsonl").read_text().strip().splitlines()
    return [json.loads(x) for x in lines]


def test_no_veto_submits(tmp_path):
    runner, tm, _ = make_runner(tmp_path)
    runner._act_on_signal(make_sig(), feat=None, bar={"t_close": T0})
    assert len(tm.submitted) == 1


def test_veto_approve_submits_and_journals(tmp_path):
    veto = StubVeto(approve=True)
    runner, tm, _ = make_runner(tmp_path, veto=veto)
    runner._act_on_signal(make_sig(), feat=None, bar={"t_close": T0})
    assert len(tm.submitted) == 1
    assert len(veto.calls) == 1
    kinds = [r["kind"] for r in read_journal(tmp_path)]
    assert "veto" in kinds


def test_veto_blocks_submit(tmp_path):
    veto = StubVeto(approve=False, reason="funding spike")
    runner, tm, rm = make_runner(tmp_path, veto=veto)
    runner._act_on_signal(make_sig(), feat=None, bar={"t_close": T0})
    assert tm.submitted == []
    # veto không được ăn slot risk (trade bị chặn trước rm.on_entry)
    assert rm.allow_entry(T0)[0]
    recs = [r for r in read_journal(tmp_path) if r["kind"] == "veto"]
    assert recs[0]["approve"] is False
    assert recs[0]["reason"] == "funding spike"


def test_risk_gate_still_blocks_after_approve(tmp_path):
    runner, tm, rm = make_runner(tmp_path, veto=StubVeto(approve=True))
    rm.killed = True
    runner._act_on_signal(make_sig(), feat=None, bar={"t_close": T0})
    assert tm.submitted == []
