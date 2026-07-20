from dataclasses import replace
from datetime import date, datetime
from simcore.config import Config
from simcore.live.scheduler import LiveScheduler


class Spy:
    def __init__(self):
        self.calls = []
    def on_open(self, d, m, u):
        self.calls.append(("open", m, d))
    def on_close(self, d, m, u):
        self.calls.append(("close", m, d))
    def on_tick(self, d, m):
        self.calls.append(("tick", m, d))
    def on_intraday(self, now, d, m, u):
        self.calls.append(("intraday", m, d, now))


def _sched(spy, cfg=None):
    return LiveScheduler(spy, repo=None,
                         holidays_provider=lambda m: {date(2026, 7, 6)},
                         universe_provider=lambda m: ["005930"],
                         cfg=cfg)


def _intraday_cfg(enabled: bool) -> Config:
    base = Config()
    return replace(base, rules=replace(base.rules, intraday_enabled=enabled))


def test_guard_skips_holiday(monkeypatch):
    import simcore.live.scheduler as sc
    spy = Spy()
    sched = _sched(spy)
    monkeypatch.setattr(sc, "_today", lambda market: date(2026, 7, 6))   # 휴장일(주입)
    sched._guarded_close("KR")
    assert spy.calls == []                                    # 휴장일 → 호출 안 됨
    monkeypatch.setattr(sc, "_today", lambda market: date(2026, 7, 7))   # 거래일(화)
    sched._guarded_close("KR")
    assert spy.calls == [("close", "KR", date(2026, 7, 7))]


def test_guard_skips_weekend(monkeypatch):
    import simcore.live.scheduler as sc
    spy = Spy()
    sched = _sched(spy)
    monkeypatch.setattr(sc, "_today", lambda market: date(2026, 7, 4))   # 토요일
    sched._guarded_open("KR")
    sched._guarded_tick("KR")
    assert spy.calls == []


def test_build_registers_all_jobs():
    sched = _sched(Spy()).build()                             # start() 하지 않음
    ids = {j.id for j in sched.get_jobs()}
    assert ids == {"open_KR", "close_KR", "tick_KR",
                   "open_US", "close_US", "tick_US"}


def test_intraday_job_registered_only_when_enabled():
    on = _sched(Spy(), cfg=_intraday_cfg(True)).build()      # start() 하지 않음(다른 build 테스트와 동일 패턴)
    off = _sched(Spy(), cfg=_intraday_cfg(False)).build()
    assert any(j.id.startswith("intraday_") for j in on.get_jobs())
    assert not any(j.id.startswith("intraday_") for j in off.get_jobs())


def test_default_cfg_keeps_intraday_off():
    sched = _sched(Spy()).build()                              # cfg=None → Config() 기본
    assert not any(j.id.startswith("intraday_") for j in sched.get_jobs())


def test_in_session_boundaries(monkeypatch):
    import simcore.live.scheduler as sc

    class _FakeDT(sc.datetime):
        @classmethod
        def now(cls, tz=None):
            return sc.datetime(2026, 7, 7, 10, 0, tzinfo=tz)   # 09:00~16:10 KST 내부

    sched = _sched(Spy())
    monkeypatch.setattr(sc, "datetime", _FakeDT)
    assert sched._in_session("KR") is True

    class _FakeDTBefore(sc.datetime):
        @classmethod
        def now(cls, tz=None):
            return sc.datetime(2026, 7, 7, 8, 0, tzinfo=tz)    # 개장 전

    monkeypatch.setattr(sc, "datetime", _FakeDTBefore)
    assert sched._in_session("KR") is False


def test_guarded_intraday_calls_orch_only_in_session_and_trading_day(monkeypatch):
    import simcore.live.scheduler as sc
    spy = Spy()
    sched = _sched(spy)
    monkeypatch.setattr(sc, "_today", lambda market: date(2026, 7, 7))     # 거래일(화)

    class _FakeDTOpen(sc.datetime):
        @classmethod
        def now(cls, tz=None):
            return sc.datetime(2026, 7, 7, 10, 0, tzinfo=tz)

    monkeypatch.setattr(sc, "datetime", _FakeDTOpen)
    sched._guarded_intraday("KR")
    assert len(spy.calls) == 1
    assert spy.calls[0][0] == "intraday"
    assert spy.calls[0][1] == "KR"

    class _FakeDTClosed(sc.datetime):
        @classmethod
        def now(cls, tz=None):
            return sc.datetime(2026, 7, 7, 20, 0, tzinfo=tz)               # 마감 후

    monkeypatch.setattr(sc, "datetime", _FakeDTClosed)
    sched._guarded_intraday("KR")
    assert len(spy.calls) == 1                                            # 장 시간 외 → 추가 호출 없음

    monkeypatch.setattr(sc, "_today", lambda market: date(2026, 7, 6))     # 휴장일
    monkeypatch.setattr(sc, "datetime", _FakeDTOpen)
    sched._guarded_intraday("KR")
    assert len(spy.calls) == 1                                            # 휴장일 → 호출 없음
