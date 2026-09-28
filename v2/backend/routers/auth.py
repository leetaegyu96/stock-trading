"""인증 엔드포인트 — SPEC §7 '인증' 4개.

토큰은 httpOnly 쿠키로만 오간다. 응답 본문에 토큰을 넣지 않는 이유는 프론트가
localStorage 에 보관할 여지를 아예 없애기 위해서다(XSS 로 탈취되는 경로 차단).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from v2.backend import auth
from v2.backend.deps import (SESSION_COOKIE, current_user, get_fx_rate, get_settings,
                             get_sf)
from v2.backend.models import User
from v2.backend.settings import V2Settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupIn(BaseModel):
    # 형식 검증은 auth 계층에서 한국어 메시지와 함께 하므로 여기서는 타입만 받는다.
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    nickname: str = Field(max_length=40)


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class UserOut(BaseModel):
    id: int
    email: str
    nickname: str


def _profile(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, nickname=user.nickname)


def _set_session_cookie(response: Response, user: User, settings: V2Settings) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=auth.issue_token(user.id, settings),
        max_age=settings.session_days * 24 * 3600,
        httponly=True,              # JS 에서 읽지 못하게 — XSS 로도 토큰이 새지 않는다
        samesite="lax",             # 외부 사이트發 POST 에 쿠키가 실리지 않게
        secure=settings.cookie_secure,
        path=settings.cookie_path,
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.post("/signup", response_model=UserOut)
def signup(body: SignupIn, response: Response,
           settings: V2Settings = Depends(get_settings),
           sf: sessionmaker[Session] = Depends(get_sf),
           fx_rate: float = Depends(get_fx_rate)) -> UserOut:
    """회원 + 캐릭터 2개(국내/해외) 생성 후 바로 로그인 상태로 만든다."""
    with sf() as session:
        user = auth.signup(session, body.email, body.password, body.nickname, fx_rate)
    _set_session_cookie(response, user, settings)
    return _profile(user)


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response,
          settings: V2Settings = Depends(get_settings),
          sf: sessionmaker[Session] = Depends(get_sf)) -> UserOut:
    with sf() as session:
        user = auth.login(session, body.email, body.password, _client_ip(request))
    _set_session_cookie(response, user, settings)
    return _profile(user)


@router.post("/logout")
def logout(response: Response,
           settings: V2Settings = Depends(get_settings),
           _user: User = Depends(current_user)) -> dict:
    # 발급 때와 같은 path/samesite/secure 여야 브라우저가 같은 쿠키로 인식해 지운다.
    response.delete_cookie(key=SESSION_COOKIE, path=settings.cookie_path,
                           httponly=True, samesite="lax", secure=settings.cookie_secure)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return _profile(user)
