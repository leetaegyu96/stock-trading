"""거래내역 신호를 초보 친화 표시로 변환. config.SignalScores 를 소비한다(점수/카테고리 정합)."""
from __future__ import annotations
from simcore.config import SignalScores

SIGNAL_NAMES: dict[str, str] = {
    # 청신호
    "G1": "골든크로스", "G2": "20일선 위", "G3": "RSI 상승 전환", "G4": "MACD 골든크로스",
    "G5": "거래량 급증 양봉", "G6": "볼린저 중심 돌파", "G7": "신고가 돌파",
    "G10": "스토캐스틱 반등", "G11": "강한 추세(ADX)", "G12": "상승 우위(DI)",
    "G13": "매집(OBV) 상승", "G14": "평균가(VWAP) 돌파", "G15": "일목구름 돌파",
    "G16": "SAR 매수 전환", "G17": "변동성 수축 후 돌파", "G18": "박스권 상단 돌파",
    "G23": "신고가 + 거래량",
    # 적신호
    "R1": "데드크로스", "R2": "20일선 아래", "R3": "RSI 과열 꺾임", "R4": "MACD 데드크로스",
    "R5": "거래량 급증 음봉", "R6": "볼린저 하단 이탈", "R11": "추세 약화(ADX)",
    "R12": "하락 우위(DI)", "R13": "매집(OBV) 하락", "R14": "평균가(VWAP) 이탈",
    "R15": "일목구름 이탈", "R16": "SAR 매도 전환", "R17": "변동성 급증",
    "R18": "지지선 붕괴", "R19": "갭 하락", "R23": "장대 음봉", "R24": "거래량 없는 상승",
}

def stars(code: str, scores: SignalScores) -> int:
    return int(scores.points.get(code, 0))


def grade(score: int) -> str:
    if score >= 26:
        return "A"
    if score >= 18:
        return "B"
    if score >= 12:
        return "C"
    return "D"


def detail(fired, scores: SignalScores) -> list[dict]:
    out = []
    for c in fired:
        if c not in scores.points:
            continue
        out.append({"code": c, "name": SIGNAL_NAMES.get(c, c),
                    "category": scores.category.get(c, ""), "stars": stars(c, scores)})
    out.sort(key=lambda x: -x["stars"])
    return out


def summarize(fired, score: int, side: str, scores: SignalScores) -> str:
    named = [SIGNAL_NAMES.get(c, c) for c in fired if c in scores.points]
    if not named:
        return "신호 없음"
    head = " + ".join(named[:3])
    if side == "BUY":
        verb = "강력 매수 신호" if score >= 26 else ("매수 신호" if score >= 18 else "매수 후보")
        return f"{head} → {verb} ({score}점/{grade(score)}등급)"
    verb = "전량 매도 신호" if score >= 11 else ("부분 매도 신호" if score >= 9 else "주의 신호")
    return f"{head} → {verb} ({score}점)"
