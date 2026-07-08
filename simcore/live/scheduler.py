"""APScheduler 배선 — 시각 트리거만. 거래일 판정 후 orchestrator 호출.

스케줄러는 '언제'만 담당하고, '무엇을'은 orchestrator 가 한다. 각 트리거는 해당 시장의
오늘이 거래일일 때만 orchestrator 를 호출한다(휴장일 가드)."""
from __future__ import annotations
from datetime import date, datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from simcore.live import calendar as cal


def _today(market: str) -> date:
    return datetime.now(cal._TZ[market]).date()


# (개장시각, 마감처리시각) — 마감은 일봉 확정 여유를 두고 정규시각 이후로 정규화.
#   KR 09:00 / 16:10 KST,  US 09:30 / 16:10 ET
_SESSIONS = {
    "KR": (cal.KR_TZ, (9, 0), (16, 10)),
    "US": (cal.US_TZ, (9, 30), (16, 10)),
}


class LiveScheduler:
    def __init__(self, orch, repo, holidays_provider, universe_provider, tick_minutes=5):
        self.orch = orch
        self.repo = repo
        self.holidays = holidays_provider
        self.universe = universe_provider
        self.tick_minutes = tick_minutes

    def _is_trading_today(self, market: str) -> bool:
        return cal.is_trading_day(_today(market), market, self.holidays(market))

    def _guarded_open(self, market: str) -> None:
        if self._is_trading_today(market):
            self.orch.on_open(_today(market), market, self.universe(market))

    def _guarded_close(self, market: str) -> None:
        if self._is_trading_today(market):
            self.orch.on_close(_today(market), market, self.universe(market))

    def _guarded_tick(self, market: str) -> None:
        if self._is_trading_today(market):
            self.orch.on_tick(_today(market), market)

    def build(self) -> BackgroundScheduler:
        sched = BackgroundScheduler(timezone="UTC")
        for market, (tz, (oh, om), (ch, cm)) in _SESSIONS.items():
            sched.add_job(self._guarded_open, CronTrigger(hour=oh, minute=om, timezone=tz),
                          args=[market], id=f"open_{market}")
            sched.add_job(self._guarded_close, CronTrigger(hour=ch, minute=cm, timezone=tz),
                          args=[market], id=f"close_{market}")
            sched.add_job(self._guarded_tick, IntervalTrigger(minutes=self.tick_minutes),
                          args=[market], id=f"tick_{market}")
        return sched
