"""서버 응답 키 ↔ 프론트 타입(types.ts) 대조 — 계약 드리프트 방지.

`StockDetail.bars` 를 프론트가 `bars30` 으로 기대하는 바람에 종목 상세 화면이
**빈 화면**이었다. 타입이 갈라져도 서버 테스트·프론트 테스트는 각자 초록이라
아무도 눈치채지 못한다. 그 틈을 여기서 막는다.

types.ts 를 파싱해 기대 키를 뽑고, 실제 직렬화 결과와 비교한다. 프론트가 기대하는데
서버가 안 주면 실패(화면이 깨진다). 서버만 더 주는 건 통과(프론트가 무시하면 그만).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from v2.backend import serializers as ser
from v2.backend.market import StockDetail, StockInfo
from v2.backend.models import Account, Position, SellRule, Trade

_TYPES_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "types.ts"


def _interface_fields(name: str) -> set[str]:
    """types.ts 의 인터페이스에서 필드명을 뽑는다(상속 포함)."""
    src = _TYPES_TS.read_text(encoding="utf-8")
    m = re.search(rf"export interface {name}([^{{]*)\{{(.*?)\n\}}", src, re.S)
    if m is None:
        pytest.skip(f"types.ts 에 {name} 인터페이스가 없다")
    fields = {f.group(1) for f in re.finditer(r"^\s{2}(\w+)\??:", m.group(2), re.M)}
    ext = re.search(r"extends\s+(\w+)", m.group(1))
    if ext:
        fields |= _interface_fields(ext.group(1))
    return fields


def _assert_contract(name: str, payload: dict) -> None:
    missing = _interface_fields(name) - set(payload)
    assert not missing, (
        f"{name}: 프론트가 기대하는 키를 서버가 주지 않는다 → {sorted(missing)}. "
        f"화면이 조용히 비거나 깨진다.")


def test_stock_contract():
    info = StockInfo(symbol="005930", name="삼성전자", price=70000.0, change_pct=1.2,
                     spark7=[1.0] * 7, week_change_pct=2.0, volume=100.0,
                     volume_vs_avg=1.1, high_52w=80000.0, low_52w=60000.0, stale=False)
    _assert_contract("Stock", info.to_dict())


def test_stock_detail_contract():
    """bars/bars30 사건의 회귀 가드."""
    info = StockInfo(symbol="005930", name="삼성전자", price=70000.0, change_pct=1.2,
                     spark7=[1.0] * 7, week_change_pct=2.0, volume=100.0,
                     volume_vs_avg=1.1, high_52w=80000.0, low_52w=60000.0, stale=False)
    payload = StockDetail(info=info, bars=[{"date": "2026-01-02", "open": 1.0, "high": 1.0,
                                            "low": 1.0, "close": 1.0, "volume": 1.0}]).to_dict()
    _assert_contract("StockDetail", payload)
    assert payload["bars30"], "차트가 읽는 키는 bars30 이다"


def _position(**kw) -> Position:
    p = Position(id=1, account_id=1, symbol="005930", quantity=10,
                 avg_price_minor=70_000, opened_at=datetime(2026, 1, 2))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_position_contract():
    _assert_contract("Position", ser.position_out(_position(), "KRW", 71_000, False, None))


def test_sell_rule_contract():
    pos = _position()
    rule = SellRule(id=1, position_id=1, stop_loss_pct=-5, take_profit_pct=15,
                    quantity=10, active=True,
                    created_at=datetime(2026, 1, 2), updated_at=datetime(2026, 1, 2))
    payload = ser.sell_rule_out(rule, pos, "KRW")
    _assert_contract("SellRule", payload)
    # 발동가는 서버가 계산해 내려준다 — 판정 주체와 표시 값이 갈리면 안 된다.
    assert payload["stop_price"] and payload["take_price"]


def test_trade_contract():
    t = Trade(id=1, account_id=1, symbol="005930", side="SELL", quantity=10,
              price_minor=71_000, fee_minor=10, tax_minor=100, gross_minor=710_000,
              net_minor=709_890, realized_pnl_minor=9_890, reason="AUTO_TAKE_PROFIT",
              sell_rule_id=1, trigger_price_minor=70_500, stale_price=False,
              executed_at=datetime(2026, 1, 2))
    payload = ser.trade_out(t, "KRW")
    _assert_contract("Trade", payload)
    assert payload["trigger_price"] == 70_500, "자동매도는 발동선을 함께 보여줘야 한다"


def test_account_summary_contract(db):
    from v2.backend.models import User

    user = User(email="c@example.com", password_hash="x", nickname="계약",
                created_at=datetime(2026, 1, 2))
    db.add(user)
    db.flush()
    acct = Account(user_id=user.id, kind="KR", currency="KRW",
                   cash_minor=100_000_000, seed_minor=100_000_000,
                   created_at=datetime(2026, 1, 2))
    db.add(acct)
    db.flush()
    _assert_contract("AccountSummary", ser.account_summary(db, acct))
