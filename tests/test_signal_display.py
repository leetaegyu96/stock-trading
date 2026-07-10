from simcore.config import SignalScores
from simcore import signal_display as sd


def test_names_cover_implemented_codes():
    for code in ["G1","G7","G5","R1","R3","R18"]:
        assert code in sd.SIGNAL_NAMES and sd.SIGNAL_NAMES[code]


def test_stars_equal_points():
    sc = SignalScores()
    assert sd.stars("G1", sc) == 5    # G1 = 5점
    assert sd.stars("G3", sc) == 3


def test_grade_bands():
    assert sd.grade(30) == "A"
    assert sd.grade(20) == "B"
    assert sd.grade(14) == "C"
    assert sd.grade(5) == "D"


def test_summarize_buy_mentions_names_and_score():
    sc = SignalScores()
    text = sd.summarize(["G1", "G7", "G5"], 14, "BUY", sc)
    assert "골든크로스" in text or "신고가" in text
    assert "14" in text
    assert "매수" in text


def test_detail_has_name_category_stars():
    sc = SignalScores()
    d = sd.detail(["G1"], sc)
    assert d and d[0]["code"] == "G1" and d[0]["name"] and d[0]["category"] == "추세" and d[0]["stars"] == 5


def test_names_cover_all_scored_codes_exactly():
    assert set(sd.SIGNAL_NAMES) == set(SignalScores().points)


def test_summarize_uses_decision_not_score():
    from simcore.signal_display import summarize
    from simcore.models import DecisionType
    from simcore.config import SignalScores
    s = SignalScores()
    # R5+R23 강제, score 8 — 재계산이면 "주의", 결정기반이면 "강제 전량매도"
    out = summarize(("R5","R23"), 8, "SELL", s,
                    decision_type=DecisionType.FORCED_SELL, trigger_rule="R5+R23")
    assert "강제 전량매도" in out and "주의" not in out


def test_summarize_forced_causes():
    from simcore.signal_display import summarize
    from simcore.models import DecisionType
    from simcore.config import SignalScores
    s = SignalScores()
    m = {"R18":"지지선 붕괴", "R7":"잠금 손절선 도달", "R10":"최고가 대비 트레일링선 도달"}
    for trig, phrase in m.items():
        out = summarize((), 0, "SELL", s, decision_type=DecisionType.FORCED_SELL, trigger_rule=trig)
        assert phrase in out and "강제 전량매도" in out


def test_summarize_withdrawal_or_delisting_full_sell_is_neutral():
    """FULL_SELL with empty trigger_rule AND no scored fired codes (e.g. USER_WITHDRAWAL /
    DELISTED default decision) must NOT fabricate a signal phrase — should be neutral
    so the display layer falls back to the real `reason`."""
    from simcore.signal_display import summarize
    from simcore.models import DecisionType
    from simcore.config import SignalScores
    s = SignalScores()
    out = summarize((), 0, "SELL", s, decision_type=DecisionType.FULL_SELL, trigger_rule="")
    assert out == "신호 없음"
