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


def test_intraday_sell_full_on_high_red_score():
    # 참고: 이 테스트는 "고득점 적신호 → 전량매도" 단일 케이스만 검증한다(캡 로직은
    # test_intraday_forced_sell_bypasses_cap / test_intraday_rule_full_sell_blocked_when_cap_reached
    # 에서 별도로 검증). 과거 이름(..._and_caps)이 캡까지 검증하는 것처럼 보여 혼동을 줄 수 있어 개명.
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


def test_intraday_forced_sell_bypasses_cap():
    eng = _fresh()
    name = "국내형"
    st = eng.states[name]
    now = datetime(2026, 7, 20, 10, 0, 0)
    buy = {"005930": _buy_snap("005930", eng.config.rules.buy_score_min + 5)}
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, buy, {"005930": None},
                          1300.0, now, {name: 1e8}, {name: 1e8})
    assert "005930" in st.portfolio.positions
    # 일일 매도 캡(3) 소진 상태를 강제로 세팅
    st.intraday_sells["005930"] = eng.config.rules.intraday_max_sells_per_symbol
    # R18(지지선 붕괴) 강제매도 트리거 스냅
    forced_snap = SymbolSnapshot("005930", Market.KR, green=(), red=("R18",),
                                 close=9000.0, change_pct=-0.1, volume=2000.0,
                                 green_score=0, red_score=0, buy_gate=False)
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, {"005930": forced_snap},
                          {"005930": None}, 1300.0,
                          now + timedelta(minutes=10), {name: 1e8}, {name: 1e8})
    # 강제매도는 _intraday_can_sell 캡 검사를 우회하고 즉시 체결된다
    assert "005930" not in st.portfolio.positions
    assert (st.intraday_sells.get("005930")
            == eng.config.rules.intraday_max_sells_per_symbol + 1)  # 캡을 넘어서도 기록됨(설계상)
    assert st.portfolio.trades[-1].decision_type == DecisionType.INTRADAY_SELL
    assert st.portfolio.trades[-1].trigger_rule == "R18"


def test_intraday_rule_full_sell_blocked_when_cap_reached():
    eng = _fresh()
    name = "국내형"
    st = eng.states[name]
    now = datetime(2026, 7, 20, 10, 0, 0)
    buy = {"005930": _buy_snap("005930", eng.config.rules.buy_score_min + 5)}
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, buy, {"005930": None},
                          1300.0, now, {name: 1e8}, {name: 1e8})
    assert "005930" in st.portfolio.positions
    # 일일 매도 캡(3) 소진 상태를 강제로 세팅
    st.intraday_sells["005930"] = eng.config.rules.intraday_max_sells_per_symbol
    # red_score >= sell_full_min 이지만 강제매도 패턴(R18, {R5,R23})이 아님
    sell_snap = SymbolSnapshot("005930", Market.KR, green=(), red=("R2", "R3"),
                               close=9000.0, change_pct=-0.1, volume=2000.0,
                               green_score=0, red_score=eng.config.rules.sell_full_min,
                               buy_gate=False)
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, {"005930": sell_snap},
                          {"005930": None}, 1300.0,
                          now + timedelta(minutes=10), {name: 1e8}, {name: 1e8})
    # 규칙기반 매도는 _intraday_can_sell 게이트를 지켜 캡에 막힌다
    assert "005930" in st.portfolio.positions
    assert (st.intraday_sells.get("005930")
            == eng.config.rules.intraday_max_sells_per_symbol)


def test_intraday_partial_sell_reduces_quantity_without_reentry_cooldown():
    eng = _fresh()
    name = "국내형"
    st = eng.states[name]
    now = datetime(2026, 7, 20, 10, 0, 0)
    buy = {"005930": _buy_snap("005930", eng.config.rules.buy_score_min + 5)}
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, buy, {"005930": None},
                          1300.0, now, {name: 1e8}, {name: 1e8})
    assert "005930" in st.portfolio.positions
    original_qty = st.portfolio.positions["005930"].quantity
    assert original_qty >= 2  # 부분매도 후에도 잔량이 남아야 케이스가 성립

    r = eng.config.rules
    partial_red_score = (r.sell_partial_min + r.sell_full_min) // 2
    assert r.sell_partial_min <= partial_red_score < r.sell_full_min

    partial_snap = SymbolSnapshot("005930", Market.KR, green=(), red=("R2", "R3"),
                                  close=9500.0, change_pct=-0.05, volume=1500.0,
                                  green_score=0, red_score=partial_red_score,
                                  buy_gate=False)
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, {"005930": partial_snap},
                          {"005930": None}, 1300.0,
                          now + timedelta(minutes=10), {name: 1e8}, {name: 1e8})

    assert "005930" in st.portfolio.positions  # 부분매도: 포지션은 유지된다
    expected_sold_qty = max(1, int(original_qty * r.partial_sell_fraction))
    assert st.portfolio.positions["005930"].quantity == original_qty - expected_sold_qty
    assert st.intraday_sells.get("005930") == 1
    assert "005930" not in st.intraday_last_sell_ts  # 부분매도는 재진입 쿨다운을 걸지 않는다
    last_trade = st.portfolio.trades[-1]
    assert last_trade.decision_type == DecisionType.INTRADAY_SELL
    assert last_trade.quantity == expected_sold_qty


def test_intraday_slot_contention_picks_top_n_by_priority():
    eng = _fresh()
    name = "국내형"
    st = eng.states[name]
    now = datetime(2026, 7, 20, 10, 0, 0)
    min_score = eng.config.rules.buy_score_min
    syms = [f"S{i}" for i in range(7)]
    # 서로 다른 green_score로 순위를 명확히 함 (green_score desc 로 정렬됨)
    scores = {sym: min_score + i * 3 for i, sym in enumerate(syms)}
    snaps = {sym: _buy_snap(sym, scores[sym]) for sym in syms}
    strengths = {sym: None for sym in syms}

    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, snaps, strengths,
                          1300.0, now, {name: 1e8}, {name: 1e8})

    max_positions = eng.config.rules.max_positions
    assert len(st.portfolio.positions) == max_positions
    expected_top = set(sorted(syms, key=lambda s: -scores[s])[:max_positions])
    assert set(st.portfolio.positions) == expected_top
    # 하위 점수 종목들은 슬롯 부족으로 매수되지 않아야 한다
    excluded = set(syms) - expected_top
    assert excluded.isdisjoint(st.portfolio.positions)
