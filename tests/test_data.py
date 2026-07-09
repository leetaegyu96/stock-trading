import numpy as np
import pandas as pd
from simcore.data import _cached, load_fx

def fake_fetch():
    idx = pd.bdate_range("2025-01-02", periods=10)
    return pd.DataFrame({
        "open": np.full(10, 100.0), "high": np.full(10, 101.0),
        "low": np.full(10, 99.0), "close": np.full(10, 100.5),
        "volume": np.full(10, 1000.0),
    }, index=idx)

def test_cache_write_then_read(tmp_path):
    calls = []
    def fetch():
        calls.append(1)
        return fake_fetch()
    df1 = _cached(tmp_path, "KR_005930_20250102_20250115", fetch)
    df2 = _cached(tmp_path, "KR_005930_20250102_20250115", fetch)
    assert len(calls) == 1              # 두 번째는 캐시 히트
    pd.testing.assert_frame_equal(df1, df2)

def test_cache_returns_copy_schema():
    # 캐시 파일이 index 를 보존하는지
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        df = _cached(pathlib.Path(td), "k", fake_fetch)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

def test_empty_fetch_result_is_not_cached(tmp_path):
    calls = []
    def fetch_empty():
        calls.append(1)
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df1 = _cached(tmp_path, "KR_000000_20250101_20250131", fetch_empty)
    df2 = _cached(tmp_path, "KR_000000_20250101_20250131", fetch_empty)
    assert df1.empty and df2.empty
    assert len(calls) == 2  # 빈 응답은 캐시되지 않아 재시도됨
    assert not (tmp_path / "KR_000000_20250101_20250131.parquet").exists()


def test_lookback_pad_covers_ichimoku():
    from simcore.data import LOOKBACK_PAD_DAYS
    assert LOOKBACK_PAD_DAYS >= 120     # 일목 워밍업 안전 여유


def test_market_trend_period_default():
    from simcore.config import SignalParams
    assert SignalParams().market_trend_period == 20


def test_load_index_kr_falls_back_to_yfinance_on_pykrx_failure(tmp_path, monkeypatch):
    """KRX 로그인 실패 등으로 pykrx.get_index_ohlcv가 예외를 던지면
    yfinance ^KS200 폴백으로 넘어가고 예외가 전파되지 않아야 한다."""
    import datetime as dt
    import simcore.data as datamod

    class FakeStock:
        @staticmethod
        def get_index_ohlcv(*_args, **_kwargs):
            raise KeyError("지수명")  # pykrx 내부 실패 재현

    fake_pykrx = type("m", (), {"stock": FakeStock})
    monkeypatch.setitem(__import__("sys").modules, "pykrx", fake_pykrx)

    idx = pd.bdate_range("2025-07-14", periods=5)
    fake_yf_df = pd.DataFrame({"Close": np.full(5, 300.0)}, index=idx)

    class FakeYF:
        @staticmethod
        def download(*_args, **_kwargs):
            return fake_yf_df

    monkeypatch.setitem(__import__("sys").modules, "yfinance", FakeYF)

    start = dt.date(2026, 1, 9)
    end = dt.date(2026, 7, 9)
    s = datamod.load_index("KR", start, end, tmp_path)

    assert not s.empty
    assert s.name == "close"
    assert (s == 300.0).all()


def test_load_index_kr_falls_back_when_pykrx_returns_empty(tmp_path, monkeypatch):
    """예외를 던지지 않아도 빈 결과면 yfinance 폴백으로 넘어가야 한다."""
    import datetime as dt
    import simcore.data as datamod

    class FakeStock:
        @staticmethod
        def get_index_ohlcv(*_args, **_kwargs):
            return pd.DataFrame({"종가": pd.Series(dtype="float64")})

    fake_pykrx = type("m", (), {"stock": FakeStock})
    monkeypatch.setitem(__import__("sys").modules, "pykrx", fake_pykrx)

    idx = pd.bdate_range("2025-07-14", periods=3)
    fake_yf_df = pd.DataFrame({"Close": np.full(3, 250.0)}, index=idx)

    class FakeYF:
        @staticmethod
        def download(*_args, **_kwargs):
            return fake_yf_df

    monkeypatch.setitem(__import__("sys").modules, "yfinance", FakeYF)

    start = dt.date(2026, 1, 9)
    end = dt.date(2026, 7, 9)
    s = datamod.load_index("KR", start, end, tmp_path)

    assert not s.empty
    assert (s == 250.0).all()
