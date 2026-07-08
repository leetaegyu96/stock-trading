"""라이브 시세 병합 — KIS 현재가, 실패 시 daily_bars 마지막 종가 폴백."""
from __future__ import annotations


def current_prices(kis, symbols_by_market: dict[str, list[str]], repo) -> dict[str, dict]:
    """market 별 심볼 목록의 현재가를 조회한다.

    각 심볼에 대해 `kis.current_price(market, symbol)`를 시도하고, 예외가 나면
    `repo.load_daily_bars(market, symbol)`의 마지막 종가로 폴백한다.

    반환: `{symbol: {"price": float | None, "stale": bool}}`.
    `stale=True`는 폴백을 사용했거나(성공적인 폴백 포함) 폴백할 데이터조차 없을 때(price=None).
    """
    result: dict[str, dict] = {}
    for market, symbols in symbols_by_market.items():
        for symbol in symbols:
            try:
                price = float(kis.current_price(market, symbol))
                result[symbol] = {"price": price, "stale": False}
            except Exception:
                bars = repo.load_daily_bars(market, symbol)
                price = float(bars["close"].iloc[-1]) if not bars.empty else None
                result[symbol] = {"price": price, "stale": True}
    return result
