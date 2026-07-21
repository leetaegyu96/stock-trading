import pytest
from simcore.live.settings import LiveSettings


def _mk(**over):
    base = dict(kis_app_key="AK", kis_app_secret="SEKRET",
                database_url="postgresql://u:p@localhost/db")
    base.update(over)
    return LiveSettings(**base)


def test_defaults_and_base_url():
    s = _mk()
    assert s.kis_env == "real"
    assert s.kis_base_url() == "https://openapi.koreainvestment.com:9443"
    assert s.kis_rate_limit_per_sec == 10.0


def test_paper_base_url():
    assert _mk(kis_env="paper").kis_base_url().endswith(":29443")


def test_secrets_masked_in_repr():
    s = _mk()
    text = repr(s)
    assert "SEKRET" not in text
    assert "AK" not in text
    assert "***" in text


def test_intraday_defaults_off():
    s = _mk()
    assert s.intraday_enabled is False
    assert s.intraday_scan_minutes == 10


def test_intraday_enabled_from_env(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "AK")
    monkeypatch.setenv("KIS_APP_SECRET", "SEKRET")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("INTRADAY_ENABLED", "true")
    monkeypatch.setenv("INTRADAY_SCAN_MINUTES", "5")
    s = LiveSettings()
    assert s.intraday_enabled is True
    assert s.intraday_scan_minutes == 5
