"""인증 도메인 로직 — 비밀번호 해시·JWT·가입·로그인 (SPEC §3).

HTTP 계층(routers/auth.py)과 분리해 둔 이유: 가입 트랜잭션과 레이트 리밋은
요청 없이도(테스트·배치·콘솔) 그대로 호출해 검증할 수 있어야 한다.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from v2.backend import money
from v2.backend.deps import ApiError
from v2.backend.models import Account, EventLog, LoginAttempt, User
from v2.backend.settings import V2Settings

# 캐릭터 초기 자금 — 국내는 이 금액 그대로, 해외는 생성 시점 환율로 1회 환전(SPEC §2.1).
SEED_KRW = 100_000_000

PASSWORD_MIN_LEN = 10
# email-validator 의존성을 새로 들이지 않기 위한 최소 형식 검증. 로그인 ID 로 쓸 수 있는지만 본다.
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")
EMAIL_MAX_LEN = 320

# 레이트 리밋: 같은 key(계정 또는 IP)로 5분 내 5회를 넘겨 실패하면 차단(SPEC §3).
RATE_WINDOW = timedelta(minutes=5)
RATE_MAX_FAILS = 5

# argon2id 기본 파라미터(m=64MiB, t=3, p=4). 해시 문자열에 파라미터가 박히므로
# 나중에 강도를 올려도 기존 해시 검증은 계속 동작한다.
_hasher = PasswordHasher()


# ── 비밀번호 ────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (Argon2Error, InvalidHashError):
        # 불일치·손상된 해시 모두 '로그인 실패' 하나로 수렴시킨다(계정 존재 여부 노출 방지).
        return False


# ── 입력 정규화·검증 ─────────────────────────────────────────────────────────

def normalize_email(email: str) -> str:
    """대소문자만 다른 중복 가입을 막기 위해 소문자로 정규화해 저장·조회한다."""
    return (email or "").strip().lower()


def validate_email(email: str) -> str:
    normalized = normalize_email(email)
    if len(normalized) > EMAIL_MAX_LEN or not EMAIL_RE.match(normalized):
        raise ApiError("INVALID_INPUT", "이메일 주소 형식이 올바르지 않습니다.", 400)
    return normalized


def validate_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LEN:
        raise ApiError("INVALID_INPUT",
                       f"비밀번호는 최소 {PASSWORD_MIN_LEN}자 이상이어야 합니다.", 400)
    return password


def validate_nickname(nickname: str) -> str:
    name = (nickname or "").strip()
    if not name or len(name) > 40:
        raise ApiError("INVALID_INPUT", "닉네임은 1~40자로 입력해 주세요.", 400)
    return name


# ── 세션 토큰 ───────────────────────────────────────────────────────────────

def issue_token(user_id: int, settings: V2Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.session_days)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str, settings: V2Settings) -> int:
    """토큰 → user_id. 만료·위조·형식 오류는 전부 UNAUTHORIZED 로 수렴시킨다."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise ApiError("UNAUTHORIZED", "로그인이 필요합니다. 다시 로그인해 주세요.", 401)


# ── 가입 ────────────────────────────────────────────────────────────────────

def _new_accounts(user_id: int, fx_rate: float) -> list[Account]:
    """국내(KRW)·해외(USD) 캐릭터. seed 는 수익률 분모라 최초 현금과 같아야 한다."""
    usd_cents = money.krw_to_usd_cents(SEED_KRW, fx_rate)
    return [
        Account(user_id=user_id, kind="KR", currency="KRW",
                cash_minor=SEED_KRW, seed_minor=SEED_KRW),
        Account(user_id=user_id, kind="US", currency="USD",
                cash_minor=usd_cents, seed_minor=usd_cents),
    ]


def signup(session: Session, email: str, password: str, nickname: str,
           fx_rate: float) -> User:
    """users 1행 + accounts 2행을 트랜잭션 1건으로 만든다(SPEC §3).

    중간에 무엇이 실패하든 전부 롤백한다 — 캐릭터 없는 사용자가 남으면 그 계정은
    로그인해도 아무것도 못 하는 고아 상태가 된다.
    """
    email = validate_email(email)
    validate_password(password)
    nickname = validate_nickname(nickname)
    if not fx_rate or fx_rate <= 0:
        raise ApiError("INVALID_INPUT", "환율 정보를 가져오지 못해 가입을 완료할 수 없습니다.", 400)

    # 사전 확인 — UNIQUE 위반보다 먼저 잡아 사용자에게 명확한 문구를 준다.
    # 경합으로 빠져나간 경우는 아래 IntegrityError 가 받는다.
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise ApiError("EMAIL_TAKEN", "이미 가입된 이메일입니다. 로그인해 주세요.", 409)

    try:
        user = User(email=email, password_hash=hash_password(password), nickname=nickname)
        session.add(user)
        session.flush()                      # user.id 확보 — 계좌 FK 에 필요
        session.add_all(_new_accounts(user.id, fx_rate))
        session.add(EventLog(user_id=user.id, kind="SIGNUP",
                             detail_json={"email": email, "fx_rate": float(fx_rate)}))
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ApiError("EMAIL_TAKEN", "이미 가입된 이메일입니다. 로그인해 주세요.", 409)
    except Exception:
        session.rollback()
        raise
    return user


# ── 로그인 ──────────────────────────────────────────────────────────────────

def _rate_keys(email: str, ip: str | None) -> list[str]:
    keys = [f"email:{email}"]
    if ip:
        keys.append(f"ip:{ip}")
    return keys


def _check_rate_limit(session: Session, keys: list[str]) -> None:
    since = datetime.now() - RATE_WINDOW
    rows = session.execute(
        select(LoginAttempt.key, func.count())
        .where(LoginAttempt.key.in_(keys), LoginAttempt.ts >= since)
        .group_by(LoginAttempt.key)
    ).all()
    if any(count >= RATE_MAX_FAILS for _key, count in rows):
        raise ApiError("RATE_LIMITED",
                       "로그인 시도가 너무 많습니다. 5분 뒤에 다시 시도해 주세요.", 429)


def _record_failure(session: Session, keys: list[str]) -> None:
    session.add_all([LoginAttempt(key=k) for k in keys])
    session.commit()


def login(session: Session, email: str, password: str, ip: str | None = None) -> User:
    """성공 시 User, 실패 시 ApiError. 실패는 계정·IP 두 축으로 기록한다.

    계정 축만 세면 IP 하나로 여러 계정을 훑는 공격을 못 막고, IP 축만 세면
    공유 IP 뒤의 한 계정에 대한 무차별 대입을 못 막는다.
    """
    email = normalize_email(email)
    keys = _rate_keys(email, ip)
    _check_rate_limit(session, keys)

    user = session.scalar(select(User).where(User.email == email))
    # 존재하지 않는 계정도 같은 메시지로 응답한다(가입 여부 탐색 차단).
    if user is None or not verify_password(user.password_hash, password):
        _record_failure(session, keys)
        raise ApiError("UNAUTHORIZED", "이메일 또는 비밀번호가 올바르지 않습니다.", 401)

    # 성공했으면 그 계정의 실패 기록은 지운다 — 오타 몇 번 뒤 로그인한 사용자가
    # 남은 카운트 때문에 5분간 잠기는 일을 막는다.
    session.execute(delete(LoginAttempt).where(LoginAttempt.key == f"email:{email}"))
    user.last_login_at = datetime.now()
    session.add(EventLog(user_id=user.id, kind="LOGIN", detail_json={"ip": ip or ""}))
    session.commit()
    return user
