"""과거 시세 로딩 + parquet 캐시. 네트워크 실패 시 캐시 우선, 캐시도 없으면 명확한 에러."""
from __future__ import annotations
from datetime import date as Date, timedelta
from pathlib import Path
from typing import Callable
import pandas as pd

LOOKBACK_PAD_DAYS = 180  # 지표 워밍업(일목 78거래일 ≈ 118달력일)을 위한 여유
COLS = ["open", "high", "low", "close", "volume"]


def _cached(cache_dir: Path, key: str, fetch: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.parquet"
    if path.exists():
        df = pd.read_parquet(path)
        # Restore frequency if it was lost during parquet serialization
        if df.index.freq is None and isinstance(df.index, pd.DatetimeIndex):
            inferred = df.index.inferred_freq
            if inferred:
                df.index.freq = inferred
        return df
    df = fetch()
    if df.empty:
        print(f"[data] {key}: 빈 응답 - 캐시에 저장하지 않음 (다음 실행 시 재시도)")
        return df
    df.to_parquet(path)
    return df


def _key(market: str, symbol: str, start: Date, end: Date) -> str:
    return f"{market}_{symbol}_{start:%Y%m%d}_{end:%Y%m%d}"


def load_kr_daily(symbols: list[str], start: Date, end: Date,
                  cache_dir: Path) -> dict[str, pd.DataFrame]:
    from pykrx import stock
    pad_start = start - timedelta(days=LOOKBACK_PAD_DAYS)
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        def fetch(sym=sym):
            raw = stock.get_market_ohlcv(f"{pad_start:%Y%m%d}", f"{end:%Y%m%d}", sym)
            raw = raw.rename(columns={"시가": "open", "고가": "high", "저가": "low",
                                      "종가": "close", "거래량": "volume"})
            raw.index = pd.to_datetime(raw.index)
            return raw[COLS].astype(float).sort_index()
        try:
            df = _cached(cache_dir, _key("KR", sym, pad_start, end), fetch)
            if not df.empty:
                out[sym] = df
        except Exception as exc:  # 개별 종목 실패는 건너뛰고 경고
            print(f"[data] KR {sym} 로딩 실패: {exc}")
    if not out:
        raise RuntimeError("국내 시세를 하나도 로딩하지 못했습니다 (네트워크/캐시 확인)")
    return out


def load_us_daily(symbols: list[str], start: Date, end: Date,
                  cache_dir: Path) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    pad_start = start - timedelta(days=LOOKBACK_PAD_DAYS)
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        def fetch(sym=sym):
            raw = yf.download(sym, start=pad_start, end=end + timedelta(days=1),
                              auto_adjust=True, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.rename(columns=str.lower)[COLS]
            raw.index = pd.to_datetime(raw.index).tz_localize(None)
            return raw.astype(float).sort_index()
        try:
            df = _cached(cache_dir, _key("US", sym, pad_start, end), fetch)
            if not df.empty:
                out[sym] = df
        except Exception as exc:
            print(f"[data] US {sym} 로딩 실패: {exc}")
    if not out:
        raise RuntimeError("미국 시세를 하나도 로딩하지 못했습니다 (네트워크/캐시 확인)")
    return out


def load_fx(start: Date, end: Date, cache_dir: Path) -> pd.Series:
    """KRW per USD 일별 종가."""
    import yfinance as yf
    pad_start = start - timedelta(days=LOOKBACK_PAD_DAYS)

    def fetch():
        raw = yf.download("KRW=X", start=pad_start, end=end + timedelta(days=1),
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        s = raw["Close"] if "Close" in raw.columns else raw["close"]
        s.index = pd.to_datetime(s.index).tz_localize(None)
        return s.rename("fx").to_frame()

    df = _cached(cache_dir, _key("FX", "KRWUSD", pad_start, end), fetch)
    return df["fx"].ffill()


def load_index(market: str, start: Date, end: Date, cache_dir: Path) -> pd.Series:
    """시장 대표 지수 종가. KR=코스피200(pykrx 1028), US=S&P500(^GSPC)."""
    pad_start = start - timedelta(days=LOOKBACK_PAD_DAYS)
    if market == "KR":
        def fetch():
            from pykrx import stock
            s = stock.get_index_ohlcv(f"{pad_start:%Y%m%d}", f"{end:%Y%m%d}", "1028")["종가"]
            s.index = pd.to_datetime(s.index)
            return s.rename("close").to_frame()
        key = _key("IDX", "KOSPI200", pad_start, end)
    else:
        def fetch():
            import yfinance as yf
            raw = yf.download("^GSPC", start=pad_start, end=end + timedelta(days=1),
                              auto_adjust=True, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            s = raw["Close"] if "Close" in raw.columns else raw["close"]
            s.index = pd.to_datetime(s.index).tz_localize(None)
            return s.rename("close").to_frame()
        key = _key("IDX", "SP500", pad_start, end)
    df = _cached(cache_dir, key, fetch)
    return df["close"].astype(float).sort_index() if not df.empty else pd.Series(dtype="float64")
