"""시세·매매 테스트용 픽스처와 가짜 객체.

conftest.py 는 인증 담당 에이전트의 것이므로 건드리지 않고, 여기에 독립적으로 둔다.
테스트는 **네트워크를 절대 타지 않는다** — KIS 는 전부 `FakeKis` 로 주입한다.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from v2.backend.db import create_all, make_engine, make_session_factory
from v2.backend.models import Account, Base, Position, User

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """테스트 DB 주소만 .env 에서 끌어온다(새 의존성 없이 직접 파싱).

    **`V2_` 로 시작하는 키만** 환경변수로 올린다. 예전에는 .env 전체를 올렸는데, 그러면
    임포트만으로 `KIS_ENV` 같은 공용 키가 프로세스 환경에 박혀 v1 테스트
    (`tests/live/test_settings.py`)의 기본값 검증이 깨졌다 — 한 모듈의 임포트가
    다른 모듈의 전제를 바꾸는 오염이다. v2 설정 자체는 pydantic 이 .env 를 직접 읽으므로
    여기서 전부 올릴 이유가 없다.
    """
    path = _REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("V2_"):
            os.environ.setdefault(key, value.strip())


_load_dotenv()
TEST_DB = os.environ.get("V2_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not TEST_DB, reason="V2_TEST_DATABASE_URL 미설정")


# ---------------------------------------------------------------- DB 픽스처

@pytest.fixture(scope="session")
def engine():
    if not TEST_DB:
        pytest.skip("V2_TEST_DATABASE_URL 미설정")
    eng = make_engine(TEST_DB)
    create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    """매 테스트 전 전 테이블 TRUNCATE — 테스트 간 상태가 새지 않게 한다."""
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    return make_session_factory(engine)


@pytest.fixture
def session(session_factory):
    s = session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


# ---------------------------------------------------------------- 도메인 헬퍼

_SEQ = {"n": 0}


def new_user(session, email: str | None = None, nickname: str = "테스터") -> User:
    _SEQ["n"] += 1
    u = User(email=email or f"user{_SEQ['n']}@example.com",
             password_hash="argon2-dummy", nickname=nickname,
             created_at=datetime.now())
    session.add(u)
    session.flush()
    return u


def new_account(session, user: User, kind: str = "KR",
                cash_minor: int = 100_000_000) -> Account:
    a = Account(user_id=user.id, kind=kind,
                currency="KRW" if kind == "KR" else "USD",
                cash_minor=cash_minor, seed_minor=cash_minor,
                created_at=datetime.now())
    session.add(a)
    session.flush()
    return a


def new_position(session, account: Account, symbol: str, quantity: int,
                 avg_price_minor: int) -> Position:
    p = Position(account_id=account.id, symbol=symbol, quantity=quantity,
                 avg_price_minor=avg_price_minor, opened_at=datetime.now())
    session.add(p)
    session.flush()
    return p


def account_with_position(session, kind: str = "KR", symbol: str = "005930",
                          quantity: int = 10, avg_price_minor: int = 10_000,
                          cash_minor: int = 100_000_000):
    """(계정, 포지션) — 매도·매도벽 테스트의 기본 출발점."""
    user = new_user(session)
    acct = new_account(session, user, kind, cash_minor)
    pos = new_position(session, acct, symbol, quantity, avg_price_minor)
    session.commit()
    return acct, pos


# ---------------------------------------------------------------- 가짜 KIS

def make_bars(closes, *, end: date | None = None, volumes=None,
              highs=None, lows=None) -> pd.DataFrame:
    """종가 리스트로 일봉 DataFrame 생성. 인덱스는 `end` 로 끝나는 연속 영업일."""
    end = end or date.today()
    n = len(closes)
    idx, cur = [], end
    while len(idx) < n:
        if cur.weekday() < 5:
            idx.append(cur)
        cur -= timedelta(days=1)
    idx = sorted(idx)
    vols = list(volumes) if volumes is not None else [1000.0] * n
    his = list(highs) if highs is not None else [c * 1.01 for c in closes]
    los = list(lows) if lows is not None else [c * 0.99 for c in closes]
    return pd.DataFrame(
        {"open": list(closes), "high": his, "low": los,
         "close": list(closes), "volume": vols},
        index=pd.to_datetime(idx))


class FakeKis:
    """KisClient 의 테스트 대역. 실패는 `prices[symbol] = None` 으로 표현한다."""

    def __init__(self, prices=None, bars=None, ranking=None):
        self.prices = dict(prices or {})     # symbol -> float | None(실패)
        self.bars = dict(bars or {})         # symbol -> DataFrame | None(실패)
        self.ranking = list(ranking or [])
        self.price_calls: list[tuple[str, str]] = []
        self.bar_calls: list[tuple[str, str]] = []
        self.rank_calls = 0

    def current_price(self, market: str, symbol: str) -> float:
        self.price_calls.append((market, symbol))
        value = self.prices.get(symbol)
        if value is None:
            raise RuntimeError(f"가짜 현재가 조회 실패: {symbol}")
        return float(value)

    def daily_bars(self, market: str, symbol: str, start, end) -> pd.DataFrame:
        self.bar_calls.append((market, symbol))
        df = self.bars.get(symbol)
        if df is None:
            raise RuntimeError(f"가짜 일봉 조회 실패: {symbol}")
        return df

    def market_cap_ranking(self, top_n: int) -> list[str]:
        self.rank_calls += 1
        return list(self.ranking)[:top_n]


class FakeMarket:
    """`sellwall.scan_once` 에 주입할 시세 모듈 대역. (가격, stale) 를 돌려준다."""

    def __init__(self, quotes=None):
        # symbol -> float | (float, stale) | None(조회 실패) | Exception
        self.quotes = dict(quotes or {})
        self.calls: list[tuple[str, str]] = []

    def set(self, symbol: str, price, stale: bool = False) -> None:
        self.quotes[symbol] = (price, stale)

    def current_price(self, kind: str, symbol: str) -> tuple[float, bool]:
        self.calls.append((kind, symbol))
        value = self.quotes.get(symbol)
        if value is None:
            raise RuntimeError(f"가짜 시세 실패: {symbol}")
        if isinstance(value, tuple):
            return float(value[0]), bool(value[1])
        return float(value), False


class FakeClock:
    """단조 시계 대역 — 캐시 TTL 테스트에서 시간을 직접 민다."""

    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds
