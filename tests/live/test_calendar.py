from datetime import date
from simcore.live import calendar as cal


def test_weekend_not_trading():
    assert not cal.is_trading_day(date(2026, 7, 4), "KR", set())   # 토
    assert not cal.is_trading_day(date(2026, 7, 5), "KR", set())   # 일
    assert cal.is_trading_day(date(2026, 7, 6), "KR", set())       # 월


def test_holiday_excluded():
    h = {date(2026, 7, 6)}
    assert not cal.is_trading_day(date(2026, 7, 6), "KR", h)


def test_us_dst_offset_changes():
    # 여름(DST): ET는 UTC-4 → 09:30 ET = 13:30 UTC
    summer = cal.session_open(date(2026, 7, 6), "US")
    assert summer.utcoffset().total_seconds() == -4 * 3600
    # 겨울(표준시): ET는 UTC-5
    winter = cal.session_open(date(2026, 1, 6), "US")
    assert winter.utcoffset().total_seconds() == -5 * 3600


def test_kr_session_times():
    o = cal.session_open(date(2026, 7, 6), "KR")
    c = cal.session_close(date(2026, 7, 6), "KR")
    assert (o.hour, o.minute) == (9, 0)
    assert (c.hour, c.minute) == (15, 30)
