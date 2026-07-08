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
