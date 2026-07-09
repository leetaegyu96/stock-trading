"""종목 코드 → 표시 이름 정적 매핑. 미스 시 코드 그대로 반환(안전 폴백).
라이브에서는 live_prices 가 KIS 종목명으로 보강할 수 있다."""
from __future__ import annotations

SYMBOL_NAMES: dict[str, str] = {
    # --- KR (코스피 대형주 / 리플레이 폴백 유니버스, universe.FALLBACK_KOSPI200 전종목 포함) ---
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스", "005935": "삼성전자우", "005380": "현대차",
    "000270": "기아", "068270": "셀트리온", "005490": "POSCO홀딩스",
    "035420": "NAVER", "051910": "LG화학", "006400": "삼성SDI",
    "035720": "카카오", "028260": "삼성물산", "105560": "KB금융",
    "055550": "신한지주", "012330": "현대모비스", "086790": "하나금융지주",
    "066570": "LG전자", "003670": "포스코퓨처엠", "096770": "SK이노베이션",
    "015760": "한국전력", "017670": "SK텔레콤", "034730": "SK",
    "003550": "LG", "018260": "삼성에스디에스", "032830": "삼성생명",
    "009150": "삼성전기", "011200": "HMM", "010130": "고려아연",
    "196170": "알테오젠", "247540": "에코프로비엠",
    "323410": "카카오뱅크", "033780": "KT&G", "024110": "기업은행",
    "090430": "아모레퍼시픽",
    # --- US (S&P500 주요, universe.FALLBACK_SP500 전종목 포함) ---
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AMZN": "Amazon",
    "GOOGL": "Alphabet", "META": "Meta", "TSLA": "Tesla", "AVGO": "Broadcom",
    "BRK-B": "Berkshire", "JPM": "JPMorgan", "V": "Visa", "MA": "Mastercard",
    "UNH": "UnitedHealth", "HD": "Home Depot", "PG": "P&G", "KO": "Coca-Cola",
    "JNJ": "J&J", "COST": "Costco", "WMT": "Walmart", "XOM": "ExxonMobil",
    "NFLX": "Netflix", "AMD": "AMD", "CRM": "Salesforce", "ADBE": "Adobe",
    "PEP": "PepsiCo", "INTC": "Intel", "CSCO": "Cisco", "ORCL": "Oracle",
    "DIS": "Disney", "BAC": "Bank of America",
    "LLY": "Eli Lilly", "ABBV": "AbbVie", "CVX": "Chevron", "MRK": "Merck",
}


def display_name(symbol: str, market: str | None = None) -> str:
    return SYMBOL_NAMES.get(symbol, symbol)
