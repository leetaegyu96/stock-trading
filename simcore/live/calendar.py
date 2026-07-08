"""KR/US 거래일·세션시각 판정. 휴장일은 외부 주입(테스트 결정론)."""
from __future__ import annotations
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KR_TZ = ZoneInfo("Asia/Seoul")
US_TZ = ZoneInfo("America/New_York")
_TZ = {"KR": KR_TZ, "US": US_TZ}
_OPEN = {"KR": time(9, 0), "US": time(9, 30)}
_CLOSE = {"KR": time(15, 30), "US": time(16, 0)}


def is_trading_day(d: date, market: str, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def session_open(d: date, market: str) -> datetime:
    return datetime.combine(d, _OPEN[market], tzinfo=_TZ[market])


def session_close(d: date, market: str) -> datetime:
    return datetime.combine(d, _CLOSE[market], tzinfo=_TZ[market])


def previous_trading_day(d: date, market: str, holidays: set[date]) -> date:
    cur = d - timedelta(days=1)
    while not is_trading_day(cur, market, holidays):
        cur -= timedelta(days=1)
    return cur


def trading_days_between(start: date, end: date, market: str,
                         holidays: set[date]) -> list[date]:
    out, cur = [], start
    while cur <= end:
        if is_trading_day(cur, market, holidays):
            out.append(cur)
        cur += timedelta(days=1)
    return out
