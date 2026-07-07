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


def kospi200(cache_dir: Path, base_date: Date) -> list[str]:
    path = Path(cache_dir) / f"universe_kospi200_{base_date:%Y%m%d}.csv"
    if path.exists():
        return pd.read_csv(path, dtype=str)["symbol"].tolist()
    from pykrx import stock
    syms = stock.get_index_portfolio_deposit_file("1028", f"{base_date:%Y%m%d}")
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
