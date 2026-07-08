"""재시작 시 놓친 거래일을 확정 일봉으로 재생(갭 리플레이).

데몬이 꺼져 있던 동안의 거래일을 KIS 확정 일봉으로 on_open→on_close 재생하여
현재 상태까지 따라잡는다. 공백 기간의 5분 손익절 정밀도는 OHLC 근사로 대체된다
(리플레이와 동일 방식, 불가피). 라이브 ≡ "실시간으로 이어지는 리플레이"."""
from __future__ import annotations
from datetime import date, timedelta

from simcore.live import calendar as cal


def catch_up(orch, repo, market: str, today: date, universe: list[str],
             holidays: set[date]) -> list[date]:
    """last_close_date 다음 거래일부터 today 전 거래일까지 재생. 처리한 날짜 리스트 반환.

    오늘(today)은 라이브 트리거가 처리하므로 제외한다. run_state 가 비어있으면(콜드스타트)
    복구할 과거가 없으므로 빈 리스트."""
    rs = repo.get_run_state(market)
    if rs.last_close_date is None:
        return []
    start = rs.last_close_date + timedelta(days=1)
    end = today - timedelta(days=1)
    if start > end:
        return []
    days = cal.trading_days_between(start, end, market, holidays)
    for d in days:
        orch.on_open(d, market, universe)
        orch.on_close(d, market, universe)
        print(f"[recovery] {market} {d} 갭 리플레이 처리 (5분 정밀도는 OHLC 근사)")
    return days
