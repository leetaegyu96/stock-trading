"""라이브 모드 설정. .env 에서 로드하며 시크릿을 마스킹한다."""
from __future__ import annotations
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REAL = "https://openapi.koreainvestment.com:9443"
_PAPER = "https://openapivts.koreainvestment.com:29443"


class LiveSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",
                                       extra="ignore", populate_by_name=True)
    kis_app_key: str = Field(alias="KIS_APP_KEY")
    kis_app_secret: str = Field(alias="KIS_APP_SECRET")
    kis_account_no: str = Field(default="", alias="KIS_ACCOUNT_NO")
    kis_env: str = Field(default="real", alias="KIS_ENV")
    database_url: str = Field(alias="DATABASE_URL")
    test_database_url: str | None = Field(default=None, alias="TEST_DATABASE_URL")
    kis_rate_limit_per_sec: float = Field(default=10.0, alias="KIS_RATE_LIMIT_PER_SEC")
    # 운영 서버에서 장중 자동매매(인트라데이) on/off — 기본 OFF, 코드 수정 없이 env 로만 전환.
    intraday_enabled: bool = Field(default=False, alias="INTRADAY_ENABLED")
    intraday_scan_minutes: int = Field(default=10, alias="INTRADAY_SCAN_MINUTES")
    # 적신호 점수 기반 매도 on/off. False = "손절/트레일만" 모드(강제매도는 유지).
    signal_sell_enabled: bool = Field(default=True, alias="SIGNAL_SELL_ENABLED")
    # 동시 보유 종목 수. 분산도 조절용(기본은 TradeRules.max_positions=5).
    max_positions: int = Field(default=5, alias="MAX_POSITIONS")

    def kis_base_url(self) -> str:
        return _PAPER if self.kis_env == "paper" else _REAL

    def __repr__(self) -> str:
        return (f"LiveSettings(kis_env={self.kis_env!r}, "
                f"kis_app_key='***', kis_app_secret='***', "
                f"database_url='***', account='***')")

    __str__ = __repr__


def load_settings() -> LiveSettings:
    return LiveSettings()  # type: ignore[call-arg]
