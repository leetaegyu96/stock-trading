from simcore.names import display_name, SYMBOL_NAMES


def test_known_kr_symbol_returns_korean_name():
    assert display_name("005930", "KR") == "삼성전자"


def test_known_us_symbol_returns_company():
    assert display_name("AAPL", "US") == "Apple"


def test_unknown_symbol_falls_back_to_code():
    assert display_name("999999", "KR") == "999999"


def test_map_is_nonempty_and_str():
    assert len(SYMBOL_NAMES) >= 30
    assert all(isinstance(v, str) and v for v in SYMBOL_NAMES.values())
