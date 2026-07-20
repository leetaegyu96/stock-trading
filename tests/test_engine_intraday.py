from datetime import date, datetime, timedelta
from simcore.config import Config
from simcore.engine import Engine
from simcore.models import Market, SymbolSnapshot, DecisionType


def _buy_snap(sym, gscore):
    # 게이트 통과 + 점수 충분한 매수 후보 스냅
    return SymbolSnapshot(sym, Market.KR, green=("G1",) * 3, red=(),
                          close=10000.0, change_pct=0.01, volume=1000.0,
                          green_score=gscore, red_score=0, buy_gate=True)


def _fresh():
    eng = Engine(Config())
    eng.start(date(2026, 7, 20), fx_rate=1300.0)
    return eng


def test_roll_day_resets_counts_and_sets_start_equity():
    eng = _fresh()
    st = next(iter(eng.states.values()))
    st.intraday_buys["AAPL"] = 3
    eng._intraday_roll_day(st, date(2026, 7, 21), day_equity=1_000.0)
    assert st.intraday_day == date(2026, 7, 21)
    assert st.intraday_buys == {}
    assert st.intraday_day_start_equity == 1_000.0


def test_can_buy_respects_daily_cap():
    eng = _fresh()
    st = next(iter(eng.states.values()))
    eng._intraday_roll_day(st, date(2026, 7, 20), day_equity=1_000.0)
    now = datetime(2026, 7, 20, 10, 0, 0)
    st.intraday_buys["AAPL"] = 3  # cap=3 소진
    assert eng._intraday_can_buy(st, "AAPL", now, cur_equity=1_000.0) is False
    st.intraday_buys["AAPL"] = 2
    assert eng._intraday_can_buy(st, "AAPL", now, cur_equity=1_000.0) is True


def test_can_buy_respects_reentry_cooldown():
    eng = _fresh()
    st = next(iter(eng.states.values()))
    eng._intraday_roll_day(st, date(2026, 7, 20), day_equity=1_000.0)
    sold_at = datetime(2026, 7, 20, 10, 0, 0)
    st.intraday_last_sell_ts["AAPL"] = sold_at
    # 쿨다운 30분: 20분 뒤 불가, 31분 뒤 가능
    assert eng._intraday_can_buy(st, "AAPL", sold_at + timedelta(minutes=20),
                                 cur_equity=1_000.0) is False
    assert eng._intraday_can_buy(st, "AAPL", sold_at + timedelta(minutes=31),
                                 cur_equity=1_000.0) is True


def test_can_buy_killswitch_blocks_when_daily_loss_exceeds():
    eng = _fresh()
    st = next(iter(eng.states.values()))
    eng._intraday_roll_day(st, date(2026, 7, 20), day_equity=1_000.0)
    now = datetime(2026, 7, 20, 13, 0, 0)
    # -5% 초과 손실(-6%): 매수 중단
    assert eng._intraday_can_buy(st, "AAPL", now, cur_equity=940.0) is False
    # -4% 손실: 매수 허용
    assert eng._intraday_can_buy(st, "AAPL", now, cur_equity=960.0) is True


def test_can_sell_respects_daily_cap():
    eng = _fresh()
    st = next(iter(eng.states.values()))
    eng._intraday_roll_day(st, date(2026, 7, 20), day_equity=1_000.0)
    st.intraday_sells["AAPL"] = 3
    assert eng._intraday_can_sell(st, "AAPL") is False
    st.intraday_sells["AAPL"] = 1
    assert eng._intraday_can_sell(st, "AAPL") is True


def test_intraday_buys_at_current_price_and_counts():
    eng = _fresh()
    name = "국내형"
    st = eng.states[name]
    now = datetime(2026, 7, 20, 10, 0, 0)
    snaps = {"005930": _buy_snap("005930", eng.config.rules.buy_score_min + 5)}
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, snaps,
                          strengths={"005930": 150.0}, fx_rate=1300.0, now=now,
                          day_equity={name: 1e8}, cur_equity={name: 1e8})
    assert "005930" in st.portfolio.positions          # 즉시 체결됨
    assert st.intraday_buys.get("005930") == 1
    # 체결 거래의 decision_type 태그 확인
    last_trade = st.portfolio.trades[-1]
    assert last_trade.decision_type == DecisionType.INTRADAY_BUY


def test_intraday_buy_blocked_when_strength_below_min():
    eng = _fresh()
    name = "국내형"
    now = datetime(2026, 7, 20, 10, 0, 0)
    snaps = {"005930": _buy_snap("005930", eng.config.rules.buy_score_min + 5)}
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, snaps,
                          strengths={"005930": 80.0}, fx_rate=1300.0, now=now,
                          day_equity={name: 1e8}, cur_equity={name: 1e8})
    assert "005930" not in eng.states[name].portfolio.positions  # 체결강도 미달 차단


def test_intraday_buy_allowed_when_strength_none():
    eng = _fresh()
    name = "국내형"
    now = datetime(2026, 7, 20, 10, 0, 0)
    snaps = {"005930": _buy_snap("005930", eng.config.rules.buy_score_min + 5)}
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, snaps,
                          strengths={"005930": None}, fx_rate=1300.0, now=now,
                          day_equity={name: 1e8}, cur_equity={name: 1e8})
    assert "005930" in eng.states[name].portfolio.positions  # None이면 조건 스킵 → 체결


def test_intraday_sell_full_on_high_red_and_caps():
    eng = _fresh()
    name = "국내형"
    st = eng.states[name]
    now = datetime(2026, 7, 20, 10, 0, 0)
    # 먼저 보유 만들기(매수)
    buy = {"005930": _buy_snap("005930", eng.config.rules.buy_score_min + 5)}
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, buy, {"005930": None},
                          1300.0, now, {name: 1e8}, {name: 1e8})
    assert "005930" in st.portfolio.positions
    # 적신호 급증 스냅으로 전량매도 유발
    sell_snap = SymbolSnapshot("005930", Market.KR, green=(), red=("R1",) * 12,
                               close=9000.0, change_pct=-0.1, volume=2000.0,
                               green_score=0, red_score=eng.config.rules.sell_full_min,
                               buy_gate=False)
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, {"005930": sell_snap},
                          {"005930": None}, 1300.0,
                          now + timedelta(minutes=10), {name: 1e8}, {name: 1e8})
    assert "005930" not in st.portfolio.positions
    assert st.intraday_sells.get("005930") == 1
    assert st.portfolio.trades[-1].decision_type == DecisionType.INTRADAY_SELL
