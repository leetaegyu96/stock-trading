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
