"""거래 유니버스. 국내 = 코스피200(pykrx), 미국 = S&P500(Wikipedia, 실패 시 내장 목록)."""
from __future__ import annotations
from datetime import date as Date
from pathlib import Path
import pandas as pd

FALLBACK_SP500 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "LLY", "AVGO", "JPM",
    "TSLA", "XOM", "UNH", "V", "PG", "MA", "COST", "JNJ", "HD", "WMT",
    "NFLX", "ABBV", "CRM", "BAC", "ORCL", "CVX", "MRK", "KO", "AMD", "PEP",
]

# pykrx>=1.2.0 부터 지수구성종목/시세 스냅샷류 KRX 엔드포인트가 KRX_ID/KRX_PW
# 인증 세션을 요구하도록 바뀌었다 (2026-07 확인). 개별 종목 시세(get_market_ohlcv)는
# 인증 없이 계속 동작하므로 코스피200 "목록" 조회가 실패할 때만 이 목록으로 대체한다.
# 시가총액 상위 30종목 기준 (2026-07 기준 수동 갱신, 필요 시 교체).
FALLBACK_KOSPI200 = [
    "005930", "000660", "373220", "207940", "005380", "005490", "051910", "006400",
    "035420", "105560", "012330", "068270", "196170", "003670", "000270", "055550",
    "032830", "066570", "323410", "086790", "015760", "033780", "017670", "018260",
    "009150", "010130", "011200", "024110", "028260", "090430",
]


def kospi200(cache_dir: Path, base_date: Date) -> list[str]:
    path = Path(cache_dir) / f"universe_kospi200_{base_date:%Y%m%d}.csv"
    if path.exists():
        return pd.read_csv(path, dtype=str)["symbol"].tolist()
    try:
        from pykrx import stock
        syms = stock.get_index_portfolio_deposit_file("1028", f"{base_date:%Y%m%d}")
        syms = list(syms)
        if len(syms) == 0:
            raise RuntimeError("빈 목록 응답")
    except Exception as exc:
        print(f"[universe] 코스피200 목록 조회 실패 ({exc!r}) - 내장 대체 목록 사용")
        syms = list(FALLBACK_KOSPI200)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"symbol": syms}).to_csv(path, index=False)
    return list(syms)


def sp500(cache_dir: Path) -> list[str]:
    path = Path(cache_dir) / "universe_sp500.csv"
    if path.exists():
        return pd.read_csv(path, dtype=str)["symbol"].tolist()
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        syms = [s.replace(".", "-") for s in tables[0]["Symbol"].tolist()]
    except Exception:
        syms = list(FALLBACK_SP500)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"symbol": syms}).to_csv(path, index=False)
    return syms
