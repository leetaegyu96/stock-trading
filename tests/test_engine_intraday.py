from datetime import date, datetime, timedelta
from simcore.config import Config
from simcore.engine import Engine


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
