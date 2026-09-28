"""라우터 공용 의존성과 오류 규약(SPEC §7).

소유권 검증(`require_account`/`require_position`)이 여기 있는 이유: 매매·매도벽 등
모든 계정 귀속 엔드포인트가 같은 검사를 통과해야 수평 권한 상승을 막을 수 있다.
각 라우터가 제 나름대로 검사하면 언젠가 한 곳이 빠진다.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from v2.backend.db import make_engine, make_session_factory
from v2.backend.models import Account, Position, User
from v2.backend.settings import V2Settings, load_settings

# 세션 쿠키 이름. v1(/stock-v1/)과 경로가 달라 섞이지 않지만 이름도 따로 둔다.
SESSION_COOKIE = "v2_session"

# 해외 캐릭터 초기 환전에 쓸 폴백 환율. 실시간 환율 소스가 붙기 전까지의 기본값이며,
# 가입 시점에 1회만 쓰이고 저장되지 않는다(SPEC §2.1).
DEFAULT_FX_RATE = 1372.6


class ApiError(Exception):
    """SPEC §7 오류 규약을 그대로 담는 예외.

    라우터는 이것만 던지고, 직렬화는 `install_error_handler` 가 한 곳에서 처리한다.
    """

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def install_error_handler(app) -> None:
    """앱에 SPEC §7 형식의 오류 핸들러를 등록한다. app.py 조립 시 1회 호출."""

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content=error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, _exc: RequestValidationError):
        # 필드별 상세는 내려보내지 않는다 — 초보 사용자에게 의미 없고 내부 구조가 드러난다.
        return JSONResponse(status_code=400,
                            content=error_body("INVALID_INPUT", "입력값이 올바르지 않습니다."))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND",
                429: "RATE_LIMITED"}.get(exc.status_code, "ERROR")
        default = {401: "로그인이 필요합니다.", 403: "권한이 없습니다.",
                   404: "요청하신 정보를 찾을 수 없습니다."}.get(exc.status_code,
                                                                "요청을 처리하지 못했습니다.")
        detail = exc.detail if isinstance(exc.detail, str) and exc.detail else default
        return JSONResponse(status_code=exc.status_code, content=error_body(code, detail))


# ── 설정·세션 ───────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_settings() -> V2Settings:
    """설정은 프로세스 수명 동안 고정. 테스트는 dependency_overrides 로 갈아끼운다."""
    return load_settings()


@lru_cache(maxsize=4)
def _session_factory(url: str) -> sessionmaker[Session]:
    # 엔진(=커넥션 풀)은 URL 당 하나만 만든다. 요청마다 만들면 커넥션이 샌다.
    return make_session_factory(make_engine(url))


def get_sf(settings: V2Settings = Depends(get_settings)) -> sessionmaker[Session]:
    return _session_factory(settings.database_url)


def get_fx_rate() -> float:
    """가입 시 해외 캐릭터 환전에 쓸 환율. 실시간 소스가 생기면 여기만 교체한다."""
    return DEFAULT_FX_RATE


# ── 인증·소유권 ─────────────────────────────────────────────────────────────

def current_user(request: Request,
                 settings: V2Settings = Depends(get_settings),
                 sf: sessionmaker[Session] = Depends(get_sf)) -> User:
    """쿠키의 JWT 를 검증해 User 를 돌려준다. 실패는 전부 401 UNAUTHORIZED."""
    # auth 가 deps 의 ApiError 를 쓰므로 모듈 레벨 import 는 순환이 된다.
    from v2.backend.auth import decode_token

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise ApiError("UNAUTHORIZED", "로그인이 필요합니다.", 401)
    user_id = decode_token(token, settings)
    with sf() as session:
        user = session.get(User, user_id)
    if user is None:
        # 토큰은 유효하나 사용자가 지워진 경우 — 재로그인시켜 정리한다.
        raise ApiError("UNAUTHORIZED", "로그인이 필요합니다. 다시 로그인해 주세요.", 401)
    return user


def load_account(session: Session, account_id: int, user: User) -> Account:
    """세션을 직접 들고 있는 호출자(트랜잭션 내부)를 위한 소유권 검사."""
    account = session.get(Account, account_id)
    if account is None:
        raise ApiError("NOT_FOUND", "요청하신 계좌를 찾을 수 없습니다.", 404)
    if account.user_id != user.id:
        raise ApiError("FORBIDDEN", "다른 사용자의 계좌에는 접근할 수 없습니다.", 403)
    return account


def load_position(session: Session, position_id: int, user: User) -> Position:
    position = session.get(Position, position_id)
    if position is None:
        raise ApiError("NOT_FOUND", "요청하신 보유 종목을 찾을 수 없습니다.", 404)
    # 포지션의 주인은 계좌를 통해서만 확인된다.
    account = session.get(Account, position.account_id)
    if account is None or account.user_id != user.id:
        raise ApiError("FORBIDDEN", "다른 사용자의 보유 종목에는 접근할 수 없습니다.", 403)
    return position


def require_account(account_id: int,
                    user: User = Depends(current_user),
                    sf: sessionmaker[Session] = Depends(get_sf)) -> Account:
    """경로 파라미터 `{account_id}` 의 계좌를 소유권 검증 후 반환(없으면 404/남의 것 403).

    라우트는 반드시 파라미터 이름을 `account_id` 로 선언해야 경로에서 값이 채워진다.
    """
    with sf() as session:
        return load_account(session, account_id, user)


def require_position(position_id: int,
                     user: User = Depends(current_user),
                     sf: sessionmaker[Session] = Depends(get_sf)) -> Position:
    """경로 파라미터 `{position_id}` 의 포지션을 소유권 검증 후 반환."""
    with sf() as session:
        return load_position(session, position_id, user)
