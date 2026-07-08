from datetime import date
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


def _sched(spy):
    return LiveScheduler(spy, repo=None,
                         holidays_provider=lambda m: {date(2026, 7, 6)},
                         universe_provider=lambda m: ["005930"])


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
