"""매도벽 감시 잡 배선 (SPEC §6.3).

스케줄러는 '언제'만 담당한다 — '무엇을'은 `sellwall.scan_once` 가 한다.
장중(KR 09:00~15:30 KST, US 09:30~16:00 ET, 주말·휴장일 제외)에만 돌리는 이유는,
장 밖의 마지막 체결가로 자동매도를 발동시키면 사용자가 보지도 못한 가격에 팔리기
때문이다.
"""
from __future__ import annotations

from datetime import date, datetime, time as _time
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from simcore.live import calendar as cal
from v2.backend import ranking, sellwall
from v2.backend.settings import V2Settings

MARKETS = ("KR", "US")
_SESSION = {"KR": (_time(9, 0), _time(15, 30)), "US": (_time(9, 30), _time(16, 0))}
# 마감 자산 스냅샷 시각. 종가가 확정될 여유를 두고 장 마감 10분 뒤에 찍는다.
_SNAPSHOT_AT = {"KR": _time(15, 40), "US": _time(16, 10)}


def market_now(market: str) -> datetime:
    return datetime.now(cal._TZ[market])


def in_session(market: str, now: datetime | None = None,
               holidays: set[date] | None = None) -> bool:
    """그 시장이 지금 열려 있는가. 휴장일 목록은 주입 가능(테스트 결정론)."""
    now = now or market_now(market)
    if now.tzinfo is not None:
        now = now.astimezone(cal._TZ[market])
    if not cal.is_trading_day(now.date(), market, holidays or set()):
        return False
    open_t, close_t = _SESSION[market]
    return open_t <= now.time() <= close_t


def build_scheduler(sf, market_mod, settings: V2Settings, *,
                    holidays_provider: Callable[[str], set[date]] | None = None,
                    scan=sellwall.scan_once,
                    snapshot=ranking.snapshot_all) -> BackgroundScheduler:
    """장중 N분 간격 감시 잡을 실은 스케줄러. 시작은 호출자(app.py)가 한다.

    `sellwall_enabled=False` 면 잡을 아예 등록하지 않는다 — 문제가 생겼을 때 코드 수정
    없이 env 하나로 자동매도를 멈출 수 있어야 한다.
    """
    sched = BackgroundScheduler(timezone="UTC")
    holidays_provider = holidays_provider or (lambda market: set())

    # 마감 자산 스냅샷 — 일간 수익률의 '오늘 시작값'이 된다. 이게 없으면 그날 거래하지
    # 않은 계정은 기준점이 없어 보유 종목이 올라도 0% 로 보인다.
    # 자동매도(sellwall_enabled)와 무관하게 항상 등록한다 — 기록은 매매 기능이 아니다.
    def _make_snapshot_job(market: str):
        def _job() -> None:
            if not cal.is_trading_day(market_now(market).date(), market,
                                      holidays_provider(market)):
                return
            snapshot(sf, market_mod, market_now(market).replace(tzinfo=None),
                     kind=market)
        _job.__name__ = f"equity_snapshot_{market}"
        return _job

    for market in MARKETS:
        at = _SNAPSHOT_AT[market]
        sched.add_job(_make_snapshot_job(market),
                      CronTrigger(hour=at.hour, minute=at.minute, timezone=cal._TZ[market]),
                      id=f"snapshot_{market}", max_instances=1, coalesce=True)

    if not settings.sellwall_enabled:
        return sched
    minutes = max(1, int(settings.sellwall_scan_minutes))

    def _make_job(market: str):
        def _job() -> None:
            # 시장별로 나눠 도는 이유: KR 장중에 US 종목까지 조회하면 장 밖 가격으로
            # 판정하게 된다.
            if not in_session(market, holidays=holidays_provider(market)):
                return
            scan(sf, market_mod, market_now(market).replace(tzinfo=None),
                 markets={market})
        _job.__name__ = f"sellwall_scan_{market}"
        return _job

    for market in MARKETS:
        sched.add_job(_make_job(market), IntervalTrigger(minutes=minutes),
                      id=f"sellwall_{market}", max_instances=1, coalesce=True)
    return sched
