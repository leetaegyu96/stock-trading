"""공용 헬퍼 simcore.signal_status.holding_signal_row 단위 테스트 (#7).

replay.py / orchestrator.py 두 곳에서 중복 작성되던 '보유' signal_status 행
생성 로직을 공용 헬퍼로 통합했는지 검증한다. stop_px/trail_px 공식은 두 호출부의
기존 코드에서 그대로 가져온 것과 동일해야 한다."""
from datetime import date

import pytest

from simcore.models import Market, Position
from simcore.signal_status import holding_signal_row


def _pos(avg_price=100.0, peak_price=100.0, locked_stop_pct=-0.07):
    return Position(symbol="AAA", market=Market.KR, quantity=10,
                    avg_price=avg_price, opened=date(2026, 1, 2),
                    peak_price=peak_price, locked_stop_pct=locked_stop_pct)


def test_holding_signal_row_trail_px_none_when_peak_gain_below_trailing_top():
    pos = _pos(avg_price=100.0, peak_price=110.0)   # peak_gain=0.10 < trailing_top(0.40)
    row = holding_signal_row(date=date(2026, 1, 10), character="국내형", symbol="AAA",
                             market=Market.KR, pos=pos, red_score=3, close=111.0,
                             trail_pct=0.07, trailing_top=0.40)
    assert row["trail_px"] is None


def test_holding_signal_row_trail_px_computed_when_peak_gain_at_or_above_trailing_top():
    pos = _pos(avg_price=100.0, peak_price=145.0)   # peak_gain=0.45 >= trailing_top(0.40)
    row = holding_signal_row(date=date(2026, 1, 10), character="국내형", symbol="AAA",
                             market=Market.KR, pos=pos, red_score=3, close=140.0,
                             trail_pct=0.07, trailing_top=0.40)
    assert row["trail_px"] == pytest.approx(145.0 * (1 - 0.07))


def test_holding_signal_row_shape_and_fixed_fields():
    pos = _pos(avg_price=100.0, peak_price=100.0, locked_stop_pct=-0.07)
    row = holding_signal_row(date=date(2026, 1, 10), character="국내형", symbol="AAA",
                             market=Market.KR, pos=pos, red_score=5, close=99.0,
                             trail_pct=0.07, trailing_top=0.40)
    assert row == {
        "date": date(2026, 1, 10), "character": "국내형", "symbol": "AAA",
        "market": "KR", "kind": "보유",
        "green_score": 0, "red_score": 5,
        "buy_gate": False, "status": "", "block_reason": "",
        "stop_px": pytest.approx(93.0), "trail_px": None,
        "close": 99.0,
    }


def test_holding_signal_row_stop_px_uses_avg_price_and_locked_stop_pct():
    pos = _pos(avg_price=200.0, peak_price=200.0, locked_stop_pct=-0.10)
    row = holding_signal_row(date=date(2026, 1, 10), character="해외형", symbol="BBB",
                             market=Market.US, pos=pos, red_score=0, close=None,
                             trail_pct=0.07, trailing_top=0.40)
    assert row["stop_px"] == pytest.approx(200.0 * (1 - 0.10))
    assert row["market"] == "US"
    assert row["close"] is None
