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
