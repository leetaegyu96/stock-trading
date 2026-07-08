from datetime import date, datetime, timedelta

import pytest

from simcore.live import db
from simcore.models import Market

from tests.dashboard.conftest import needs_db
from dashboard.backend import summary


def _seed(s, name="테스트형"):
    s.merge(db.CharacterRow(name=name, base_currency="KRW"))

    # 자본 흐름: 첫 건은 초기자금(TWR/PNL 계산에서 제외), 둘째 건은 반영되어야 함
    s.add(db.CapitalFlowRow(date=date(2026, 1, 1), character=name,
                             amount_krw=10_000_000.0, fx_rate=1.0))
    s.add(db.CapitalFlowRow(date=date(2026, 1, 3), character=name,
                             amount_krw=2_000_000.0, fx_rate=1.0))

    # 자산곡선 (하루 1점, 장마감 시각)
    for d, eq in [
        (1, 10_000_000.0),
        (2, 10_500_000.0),
        (3, 12_700_000.0),
        (4, 12_900_000.0),
        (5, 12_800_000.0),
    ]:
        s.add(db.EquityPoint(ts=datetime(2026, 1, d, 15, 30), character=name, equity_krw=eq))

    # 보유 종목: 해외(US) 1종목 — fx 환산 검증용
    s.add(db.PositionRow(character=name, symbol="AAPL", market=Market.US.value,
                          quantity=5, avg_price=150.0, opened_date=date(2026, 1, 2)))

    # 현금 (KRW + USD)
    s.add(db.CashBalance(character=name, currency="KRW", amount=500_000.0))
    s.add(db.CashBalance(character=name, currency="USD", amount=1_000.0))

    # 매도 거래 5건 — 3승 2패 → win_rate 0.6
    pnls = [1000.0, -500.0, 2000.0, -300.0, 1500.0]
    for i, pnl in enumerate(pnls):
        s.add(db.TradeRow(
            ts=datetime(2026, 1, i + 1, 9, 30), date=date(2026, 1, i + 1),
            character=name, symbol=f"SYM{i}", market=Market.KR.value, side="SELL",
            quantity=1, price=1000.0, fee=0.0, tax=0.0, reason="SIGNAL_SELL",
            green_count=0, red_count=0, fired=[], realized_pnl=pnl,
        ))


@needs_db
def test_detail_metrics_matches_hand_computed(sf):
    with sf() as s:
        _seed(s)
        s.commit()

    m = summary.detail_metrics(sf, "테스트형")

    # twr: r2=1.05, r3=127/125, r4=129/127, r5=128/129 → (21/20)*(128/125) - 1 = 0.0752
    assert m.twr == pytest.approx(0.0752)
    # mdd: 최고점 12,900,000 대비 마지막 12,800,000 → -1/129
    assert m.mdd == pytest.approx(-1 / 129)
    # pnl = (12,800,000 - 10,000,000) - 2,000,000(추가입금) = 800,000
    assert m.pnl_krw == pytest.approx(800_000.0)
    assert m.n_trades == 5
    assert m.win_rate == pytest.approx(0.6)


@needs_db
def test_card_summary_matches_hand_computed(sf):
    with sf() as s:
        _seed(s)
        s.commit()

    c = summary.card_summary(sf, "테스트형", fx_rate=1300.0, last_prices={"AAPL": 160.0})

    assert c.twr == pytest.approx(0.0752)
    assert c.pnl_krw == pytest.approx(800_000.0)
    assert c.today_pnl_pct == pytest.approx(12_800_000.0 / 12_900_000.0 - 1.0)
    assert c.equity_spark == [
        10_000_000.0, 10_500_000.0, 12_700_000.0, 12_900_000.0, 12_800_000.0,
    ]
    assert c.n_positions == 1
    assert c.cash_krw == pytest.approx(500_000.0 + 1_000.0 * 1300.0)
    assert c.total_asset_krw == pytest.approx(c.cash_krw + 5 * 160.0 * 1300.0)


@needs_db
def test_card_summary_spark_limited_to_30_points(sf):
    name = "장기형"
    base = datetime(2026, 1, 1, 15, 30)
    with sf() as s:
        s.merge(db.CharacterRow(name=name, base_currency="KRW"))
        for i in range(40):
            s.add(db.EquityPoint(ts=base + timedelta(days=i),
                                  character=name, equity_krw=10_000_000.0 + i * 1000.0))
        s.commit()

    c = summary.card_summary(sf, name, fx_rate=1300.0, last_prices={})
    assert len(c.equity_spark) == 30
    assert c.equity_spark[-1] == pytest.approx(10_000_000.0 + 39 * 1000.0)


@needs_db
def test_card_summary_and_detail_metrics_defaults_when_no_history(sf):
    with sf() as s:
        s.merge(db.CharacterRow(name="빈형", base_currency="KRW"))
        s.commit()

    c = summary.card_summary(sf, "빈형", fx_rate=1300.0, last_prices={})
    assert c.twr == 0.0
    assert c.pnl_krw == 0.0
    assert c.today_pnl_pct == 0.0
    assert c.equity_spark == []
    assert c.n_positions == 0
    assert c.cash_krw == 0.0
    assert c.total_asset_krw == 0.0

    m = summary.detail_metrics(sf, "빈형")
    assert m.twr == 0.0
    assert m.mdd == 0.0
    assert m.n_trades == 0
    assert m.win_rate == 0.0
    assert m.pnl_krw == 0.0
