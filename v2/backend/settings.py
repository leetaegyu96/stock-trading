"""v2 설정. v1 과 DB·포트·토큰 저장소를 공유하지 않는다(SPEC §1)."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class V2Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",
                                      extra="ignore", populate_by_name=True)

    # v2 전용 DB. v1 의 simcore DB 와 테이블을 섞지 않는다.
    database_url: str = Field(alias="V2_DATABASE_URL")
    test_database_url: str | None = Field(default=None, alias="V2_TEST_DATABASE_URL")

    # 세션 쿠키 서명 키. 운영에서는 반드시 .env 로 주입한다.
    secret_key: str = Field(alias="V2_SECRET_KEY")
    session_days: int = Field(default=7, alias="V2_SESSION_DAYS")
    # 서브패스(/stock-v2/)로 서비스되므로 쿠키 경로를 좁혀 v1 과 섞이지 않게 한다.
    cookie_path: str = Field(default="/stock-v2", alias="V2_COOKIE_PATH")
    cookie_secure: bool = Field(default=True, alias="V2_COOKIE_SECURE")

    # KIS — v1 과 같은 앱키를 쓰되 토큰 저장소는 v2 DB 에 따로 둔다(SPEC §4.1).
    kis_app_key: str = Field(alias="KIS_APP_KEY")
    kis_app_secret: str = Field(alias="KIS_APP_SECRET")
    kis_account_no: str = Field(default="", alias="KIS_ACCOUNT_NO")
    kis_env: str = Field(default="paper", alias="KIS_ENV")
    kis_rate_limit_per_sec: float = Field(default=10.0, alias="KIS_RATE_LIMIT_PER_SEC")

    # 매도벽 감시 주기(분). 장중에만 돈다.
    sellwall_scan_minutes: int = Field(default=1, alias="V2_SELLWALL_SCAN_MINUTES")
    # 감시 잡 자체의 on/off — 문제 시 코드 수정 없이 끌 수 있어야 한다.
    sellwall_enabled: bool = Field(default=True, alias="V2_SELLWALL_ENABLED")

    def kis_base_url(self) -> str:
        return ("https://openapivts.koreainvestment.com:29443" if self.kis_env == "paper"
                else "https://openapi.koreainvestment.com:9443")

    def __repr__(self) -> str:      # 시크릿 마스킹
        return (f"V2Settings(kis_env={self.kis_env!r}, database_url='***', "
                f"secret_key='***', kis_app_key='***')")

    __str__ = __repr__


def load_settings() -> V2Settings:
    return V2Settings()  # type: ignore[call-arg]
