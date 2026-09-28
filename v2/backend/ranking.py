"""계정별 일간 수익률 랭킹 (전 회원 공개).

## 왜 마감 스냅샷이 필요한가
`equity_snapshots` 는 **거래할 때만** 쌓인다. 그러면 오늘 거래하지 않은 계정은 오늘의
기준점이 없어 "일간 수익률"이 정의되지 않는다. 보유 종목이 올랐어도 0% 로 보이는 셈이다.
그래서 시장 마감마다 전 계정의 평가액을 한 줄씩 남긴다(`snapshot_all`).

## 통화가 다른데 순위를 매겨도 되나
국내는 원화, 해외는 달러라 **금액은 비교할 수 없다**. 하지만 수익률은 비율이라 비교된다.
랭킹 지표를 금액이 아니라 %로 두는 이유이고, 화면에도 금액은 통화와 함께만 보여준다.
"""
from __future__ import annotations

import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from v2.backend import trading
from v2.backend.models import Account, EquitySnapshot, Position, User
from v2.backend.money import to_major, to_minor


def _baseline_minor(session: Session, account: Account, today: date) -> int:
    """오늘의 시작 자산. 어제까지의 마지막 스냅샷, 없으면 최초 투입액(seed).

    seed 로 떨어지는 건 가입 첫날뿐이다 — 그날은 일간 = 누적이라 자연스럽다.
    """
    row = session.execute(
        select(EquitySnapshot.equity_minor)
        .where(EquitySnapshot.account_id == account.id,
               EquitySnapshot.ts < datetime.combine(today, datetime.min.time()))
        .order_by(EquitySnapshot.ts.desc())
        .limit(1)).scalar()
    return int(row) if row is not None else int(account.seed_minor)


def _current_minor(session: Session, account: Account,
                   prices_minor: dict[str, int]) -> tuple[int, bool]:
    """현재 평가액과 stale 여부. 시세를 못 얻은 종목은 평단으로 친다."""
    stale = False
    total = int(account.cash_minor)
    for pos in session.query(Position).filter_by(account_id=account.id):
        px = prices_minor.get(pos.symbol)
        if px is None:
            px, stale = int(pos.avg_price_minor), True
        total += int(px) * pos.quantity
    return total, stale


def _quote_map(session: Session, market_mod, accounts: list[Account]) -> dict[str, int]:
    """보유 종목 현재가를 **종목당 1회**만, 그리고 **병렬로** 조회한다.

    순차로 돌면 장 마감처럼 실시간 시세가 안 나오는 시간대에 종목마다 타임아웃을 물어
    랭킹 한 번에 10초가 넘는다(실측 11.7초). 여러 사람이 자주 보는 화면이라 그건 못 쓴다.
    """
    wanted: dict[str, str] = {}          # symbol -> kind
    for acct in accounts:
        for pos in session.query(Position).filter_by(account_id=acct.id):
            wanted.setdefault(pos.symbol, acct.kind)
    if not wanted:
        return {}

    def fetch(item: tuple[str, str]) -> tuple[str, int] | None:
        symbol, kind = item
        try:
            price, _ = market_mod.current_price(kind, symbol)
            return symbol, to_minor(price, "KRW" if kind == "KR" else "USD")
        except Exception:
            return None                  # 평단 폴백은 _current_minor 가 처리

    workers = min(_QUOTE_WORKERS, len(wanted))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(fetch, wanted.items()))
    return {sym: px for r in results if r for sym, px in [r]}


def build(session: Session, market_mod, *, kind: str | None = None,
          me_user_id: int | None = None, today: date | None = None,
          use_cache: bool = False) -> list[dict]:
    """일간 수익률 내림차순 랭킹. `kind` 로 국내/해외만 볼 수 있다.

    `use_cache` 는 라우터에서만 켠다 — 순위표는 초 단위로 정확할 필요가 없고,
    여러 사람이 같은 화면을 동시에 열면 같은 계산을 반복하게 된다. `is_me` 는
    캐시된 결과에 사용자별로 다시 입힌다(사용자마다 캐시를 나누지 않기 위해).
    """
    today = today or date.today()
    if use_cache:
        cached = _cache_get(kind)
        if cached is not None:
            return _with_me(cached, session, me_user_id)
    q = session.query(Account)
    if kind in ("KR", "US"):
        q = q.filter(Account.kind == kind)
    accounts = q.all()
    if not accounts:
        return []

    prices = _quote_map(session, market_mod, accounts)
    nicknames = {u.id: u.nickname for u in session.query(User).all()}

    rows: list[dict] = []
    for acct in accounts:
        base = _baseline_minor(session, acct, today)
        cur, stale = _current_minor(session, acct, prices)
        seed = int(acct.seed_minor)
        rows.append({
            "account_id": acct.id,
            "nickname": nicknames.get(acct.user_id, "알 수 없음"),
            "kind": acct.kind,
            "currency": acct.currency,
            "daily_return_pct": round((cur / base - 1) * 100, 3) if base else 0.0,
            "daily_pnl": _money(cur - base, acct.currency),
            "total_return_pct": round((cur / seed - 1) * 100, 3) if seed else 0.0,
            "total_asset": _money(cur, acct.currency),
            "position_count": session.query(Position)
                                     .filter_by(account_id=acct.id).count(),
            "is_me": me_user_id is not None and acct.user_id == me_user_id,
            "stale": stale,
        })

    # 동률이면 누적 수익률로 가른다 — 같은 등수가 줄줄이 붙으면 순위표가 의미를 잃는다.
    rows.sort(key=lambda r: (-r["daily_return_pct"], -r["total_return_pct"]))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    if use_cache:
        _cache_put(kind, rows)
    return rows


# ---- 짧은 결과 캐시 -------------------------------------------------------
_QUOTE_WORKERS = 8
_CACHE_TTL = 20.0
_cache: dict[str | None, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def _cache_get(kind: str | None) -> list[dict] | None:
    with _cache_lock:
        hit = _cache.get(kind)
    if hit and _time.monotonic() - hit[0] < _CACHE_TTL:
        return [dict(r) for r in hit[1]]
    return None


def _cache_put(kind: str | None, rows: list[dict]) -> None:
    with _cache_lock:
        _cache[kind] = (_time.monotonic(), [dict(r) for r in rows])


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _with_me(rows: list[dict], session: Session, me_user_id: int | None) -> list[dict]:
    """캐시된 순위표에 '내 계정' 표시만 다시 입힌다."""
    if me_user_id is None:
        for r in rows:
            r["is_me"] = False
        return rows
    mine = {a.id for a in session.query(Account).filter_by(user_id=me_user_id)}
    for r in rows:
        r["is_me"] = r["account_id"] in mine
    return rows


def _money(minor: int, currency: str) -> float | int:
    v = to_major(int(minor), currency)
    return int(v) if currency == "KRW" else float(round(v, 2))


def snapshot_all(sf, market_mod, now: datetime | None = None,
                 kind: str | None = None) -> dict[str, int]:
    """전 계정 평가액을 한 줄씩 남긴다(마감 잡). 일간 수익률의 기준선이 된다.

    한 계정에서 실패해도 나머지는 계속 남긴다 — 기준선이 빠진 계정만 다음 날
    일간 수익률이 어긋나고, 전체가 멈추는 것보다 낫다.
    """
    now = now or datetime.now()
    stats = {"accounts": 0, "errors": 0}
    with sf() as session:                # type: Session
        q = session.query(Account)
        if kind in ("KR", "US"):
            q = q.filter(Account.kind == kind)
        accounts = q.all()
        prices = _quote_map(session, market_mod, accounts)
        for acct in accounts:
            try:
                trading.record_equity(session, acct, prices, now)
                stats["accounts"] += 1
            except Exception:
                stats["errors"] += 1
        session.commit()
    return stats
