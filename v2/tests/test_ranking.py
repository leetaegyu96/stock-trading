"""일간 수익률 랭킹 (ranking.build / snapshot_all)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from v2.backend import ranking
from v2.backend.models import Account, EquitySnapshot, Position, User
from v2.tests.factories import needs_db          # noqa: F401 (픽스처 로딩)

TODAY = date(2026, 9, 28)
YESTERDAY = datetime(2026, 9, 27, 15, 40)


class FakeMarket:
    """시세 소스. 조회 횟수를 세어 '종목당 1회' 계약을 검증한다."""

    def __init__(self, prices: dict[str, float], fail: set[str] | None = None):
        self.prices = prices
        self.fail = fail or set()
        self.calls: list[str] = []

    def current_price(self, kind: str, symbol: str) -> tuple[float, bool]:
        self.calls.append(symbol)
        if symbol in self.fail:
            raise RuntimeError("시세 없음")
        return self.prices[symbol], False


def _user(db, nickname: str) -> User:
    u = User(email=f"{nickname}@example.com", password_hash="x", nickname=nickname,
             created_at=datetime(2026, 1, 1))
    db.add(u)
    db.flush()
    return u


def _account(db, user: User, kind="KR", cash=100_000_000, seed=100_000_000) -> Account:
    a = Account(user_id=user.id, kind=kind, currency="KRW" if kind == "KR" else "USD",
                cash_minor=cash, seed_minor=seed, created_at=datetime(2026, 1, 1))
    db.add(a)
    db.flush()
    return a


def _position(db, acct: Account, symbol: str, qty: int, avg: int) -> Position:
    p = Position(account_id=acct.id, symbol=symbol, quantity=qty,
                 avg_price_minor=avg, opened_at=datetime(2026, 1, 2))
    db.add(p)
    db.flush()
    return p


@needs_db
def test_어제_스냅샷이_일간_기준선이_된다(db):
    u = _user(db, "기준")
    a = _account(db, u, cash=50_000_000)
    _position(db, a, "005930", 500, 100_000)          # 취득원가 5,000만
    db.add(EquitySnapshot(account_id=a.id, ts=YESTERDAY, equity_minor=100_000_000))
    db.flush()

    # 현재가 110,000 → 평가액 5,500만 + 현금 5,000만 = 1억 500만 (어제 대비 +5%)
    rows = ranking.build(db, FakeMarket({"005930": 110_000}), today=TODAY)
    assert rows[0]["daily_return_pct"] == pytest.approx(5.0, abs=0.01)


@needs_db
def test_첫날은_기준선이_seed라_일간이_누적과_같다(db):
    """스냅샷이 하나도 없는 가입 첫날. 0% 로 뭉개지 않고 누적과 같게 둔다."""
    u = _user(db, "첫날")
    a = _account(db, u, cash=50_000_000)
    _position(db, a, "005930", 500, 100_000)
    db.flush()

    rows = ranking.build(db, FakeMarket({"005930": 120_000}), today=TODAY)
    r = rows[0]
    assert r["daily_return_pct"] == pytest.approx(r["total_return_pct"], abs=0.001)
    assert r["daily_return_pct"] == pytest.approx(10.0, abs=0.01)


@needs_db
def test_오늘_찍힌_스냅샷은_기준선이_아니다(db):
    """오늘 매매로 생긴 스냅샷을 기준으로 삼으면 '오늘 산 순간' 이후만 재는 셈이 된다."""
    u = _user(db, "오늘")
    a = _account(db, u, cash=50_000_000)
    _position(db, a, "005930", 500, 100_000)
    db.add(EquitySnapshot(account_id=a.id, ts=YESTERDAY, equity_minor=100_000_000))
    db.add(EquitySnapshot(account_id=a.id,
                          ts=datetime(2026, 9, 28, 10, 0), equity_minor=104_000_000))
    db.flush()

    rows = ranking.build(db, FakeMarket({"005930": 110_000}), today=TODAY)
    assert rows[0]["daily_return_pct"] == pytest.approx(5.0, abs=0.01), "어제 종가 기준이어야 한다"


@needs_db
def test_일간_수익률_내림차순_정렬(db):
    for nick, cash in (("꼴찌", 90_000_000), ("일등", 120_000_000), ("중간", 100_000_000)):
        _account(db, _user(db, nick), cash=cash)
    db.flush()
    rows = ranking.build(db, FakeMarket({}), today=TODAY)
    assert [r["nickname"] for r in rows] == ["일등", "중간", "꼴찌"]
    assert [r["rank"] for r in rows] == [1, 2, 3]


@needs_db
def test_동률은_누적_수익률로_가른다(db):
    """같은 등수가 줄줄이 붙으면 순위표가 의미를 잃는다."""
    a1 = _account(db, _user(db, "적게번"), cash=100_000_000, seed=100_000_000)
    a2 = _account(db, _user(db, "많이번"), cash=100_000_000, seed=50_000_000)
    for a in (a1, a2):
        db.add(EquitySnapshot(account_id=a.id, ts=YESTERDAY, equity_minor=100_000_000))
    db.flush()
    rows = ranking.build(db, FakeMarket({}), today=TODAY)
    assert rows[0]["nickname"] == "많이번"       # 일간 동률 → 누적이 높은 쪽


@needs_db
def test_같은_종목은_한_번만_조회한다(db):
    """계정이 늘어도 시세 호출은 종목 수만큼이어야 한다."""
    for nick in ("갑", "을", "병"):
        a = _account(db, _user(db, nick))
        _position(db, a, "005930", 10, 100_000)
    db.flush()
    mk = FakeMarket({"005930": 100_000})
    ranking.build(db, mk, today=TODAY)
    assert mk.calls.count("005930") == 1, f"중복 조회: {mk.calls}"


@needs_db
def test_시세_실패는_평단으로_평가하고_stale로_알린다(db):
    u = _user(db, "지연")
    a = _account(db, u, cash=0)
    _position(db, a, "005930", 10, 100_000)
    db.flush()
    rows = ranking.build(db, FakeMarket({}, fail={"005930"}), today=TODAY)
    assert rows[0]["stale"] is True
    assert rows[0]["total_asset"] == 1_000_000      # 평단 × 수량


@needs_db
def test_내_계정만_is_me가_참(db):
    me = _user(db, "나")
    other = _user(db, "남")
    _account(db, me)
    _account(db, other)
    db.flush()
    rows = ranking.build(db, FakeMarket({}), me_user_id=me.id, today=TODAY)
    assert [r["nickname"] for r in rows if r["is_me"]] == ["나"]


@needs_db
def test_이메일은_절대_나가지_않는다(db):
    """랭킹은 전 회원에게 공개된다 — 식별 정보는 닉네임까지다."""
    _account(db, _user(db, "비공개"))
    db.flush()
    rows = ranking.build(db, FakeMarket({}), today=TODAY)
    blob = str(rows)
    assert "@" not in blob and "email" not in blob


@needs_db
def test_시장_필터(db):
    u = _user(db, "둘다")
    _account(db, u, kind="KR")
    _account(db, u, kind="US", cash=7_278_158, seed=7_278_158)
    db.flush()
    assert len(ranking.build(db, FakeMarket({}), kind="KR", today=TODAY)) == 1
    assert len(ranking.build(db, FakeMarket({}), kind="US", today=TODAY)) == 1
    assert len(ranking.build(db, FakeMarket({}), today=TODAY)) == 2


@needs_db
def test_참가자가_없으면_빈_목록(db):
    assert ranking.build(db, FakeMarket({}), today=TODAY) == []


@needs_db
def test_snapshot_all_이_전_계정_기준선을_남긴다(db, sf):
    """이게 없으면 그날 거래하지 않은 계정은 일간 수익률 기준점이 없다."""
    u = _user(db, "스냅")
    a = _account(db, u, cash=50_000_000)
    _position(db, a, "005930", 500, 100_000)
    db.commit()

    stats = ranking.snapshot_all(sf, FakeMarket({"005930": 110_000}),
                                 now=datetime(2026, 9, 28, 15, 40))
    assert stats["accounts"] >= 1 and stats["errors"] == 0
    saved = db.query(EquitySnapshot).filter_by(account_id=a.id).all()
    assert saved and saved[-1].equity_minor == 50_000_000 + 500 * 110_000


# ── 성능·캐시 ────────────────────────────────────────────────────────────
@needs_db
def test_캐시가_반복_계산을_막는다(db):
    """순위표는 초 단위로 정확할 필요가 없다. 여러 사람이 동시에 열면 같은 계산이 반복된다."""
    ranking.clear_cache()
    a = _account(db, _user(db, "캐시"))
    _position(db, a, "005930", 10, 100_000)
    db.flush()
    mk = FakeMarket({"005930": 110_000})

    ranking.build(db, mk, today=TODAY, use_cache=True)
    first = len(mk.calls)
    ranking.build(db, mk, today=TODAY, use_cache=True)
    assert len(mk.calls) == first, "캐시가 있는데 다시 조회했다"

    ranking.clear_cache()
    ranking.build(db, mk, today=TODAY, use_cache=True)
    assert len(mk.calls) > first, "캐시를 비웠는데 재조회하지 않았다"


@needs_db
def test_캐시된_순위표도_내_계정은_사람마다_다르게_표시된다(db):
    """사용자별로 캐시를 나누지 않으므로, is_me 만 조회 시점에 다시 입혀야 한다."""
    ranking.clear_cache()
    u1, u2 = _user(db, "갑돌"), _user(db, "을순")
    _account(db, u1)
    _account(db, u2)
    db.flush()
    mk = FakeMarket({})

    r1 = ranking.build(db, mk, me_user_id=u1.id, today=TODAY, use_cache=True)
    assert [r["nickname"] for r in r1 if r["is_me"]] == ["갑돌"]
    r2 = ranking.build(db, mk, me_user_id=u2.id, today=TODAY, use_cache=True)   # 캐시 히트
    assert [r["nickname"] for r in r2 if r["is_me"]] == ["을순"], "캐시가 남의 '나' 표시를 물고 왔다"


@needs_db
def test_캐시는_시장별로_분리된다(db):
    ranking.clear_cache()
    u = _user(db, "분리")
    _account(db, u, kind="KR")
    _account(db, u, kind="US", cash=7_278_158, seed=7_278_158)
    db.flush()
    mk = FakeMarket({})
    assert len(ranking.build(db, mk, kind="KR", today=TODAY, use_cache=True)) == 1
    assert len(ranking.build(db, mk, kind="US", today=TODAY, use_cache=True)) == 1
    assert len(ranking.build(db, mk, today=TODAY, use_cache=True)) == 2
