import numpy as np
import pandas as pd
from simcore.config import SignalParams
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


def test_market_trend_period_defaults():
    assert SignalParams().market_trend_period_kr == 20
    assert SignalParams().market_trend_period_us == 20


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


def test_make_bearish_fn_basic_and_fallbacks():
    import numpy as np
    import pandas as pd
    from simcore.data import make_bearish_fn
    idx = pd.bdate_range("2026-01-01", periods=60)
    down = pd.Series(np.linspace(200, 100, 60), index=idx)   # 종가 < SMA20
    up = pd.Series(np.linspace(100, 200, 60), index=idx)     # 종가 > SMA20
    fn = make_bearish_fn({"KR": down, "US": up}, {"KR": 20, "US": 20})
    assert fn(idx[-1]) == {"KR": True, "US": False}
    # 지수 없음(None) → False
    assert make_bearish_fn({"KR": None}, {"KR": 20})(idx[-1]) == {"KR": False}
    # 워밍업(SMA NaN) → False
    assert make_bearish_fn({"KR": down}, {"KR": 20})(idx[3]) == {"KR": False}


def test_make_bearish_fn_period_independent_per_market():
    # 같은 지수라도 시장별 기간이 다르면 판정이 갈린다 (하락 후 단기 반등 시나리오)
    import numpy as np
    import pandas as pd
    from simcore.data import make_bearish_fn
    idx = pd.bdate_range("2026-01-01", periods=60)
    v = np.concatenate([np.linspace(200, 100, 50), np.linspace(103, 130, 10)])
    s = pd.Series(v, index=idx)
    fn = make_bearish_fn({"KR": s, "US": s}, {"KR": 5, "US": 60})
    assert fn(idx[-1]) == {"KR": False, "US": True}   # 단기(5)는 반등 반영, 장기(60)는 하락


def test_make_bearish_fn_empty_and_asof_failure_fallback():
    import pandas as pd
    from simcore.data import make_bearish_fn
    # 빈 지수(예: load_index 무데이터 폴백) → asof에서 IndexError → except 폴백 경로에서 False
    empty = pd.Series(dtype="float64")
    assert make_bearish_fn({"KR": empty}, {"KR": 20})(pd.Timestamp("2026-01-10")) == {"KR": False}
    # asof가 파싱 불가능한 값을 받아 예외를 던지는 경우에도 False (안전 폴백)
    idx = pd.bdate_range("2026-01-01", periods=30)
    s = pd.Series(range(30), index=idx, dtype=float)
    fn = make_bearish_fn({"KR": s}, {"KR": 5})
    assert fn("not-a-timestamp") == {"KR": False}
