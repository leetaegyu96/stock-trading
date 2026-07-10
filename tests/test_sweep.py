"""sweep 채택 규칙(순수 함수) 단위 테스트. 규칙: TWR ≥ OFF−1%p AND |MDD| 개선 →
|MDD| 최소, 동률 시 TWR 최대. 후보 없으면 None."""
from simcore.sweep import improves, pick_single, pick_universal


def s(twr, mdd, n=10):
    return {"twr": twr, "mdd": mdd, "pnl_krw": 0.0, "n_trades": n}


OFF = {"국내형": s(0.39, -0.17), "해외형": s(0.16, -0.11), "범용형": s(-0.12, -0.26)}


def test_improves_rule():
    assert improves(OFF["해외형"], s(0.27, -0.065))            # TWR·MDD 모두 개선
    assert improves(OFF["국내형"], s(0.385, -0.15))            # TWR −0.5%p(허용) + MDD 개선
    assert not improves(OFF["국내형"], s(0.30, -0.10))         # TWR −9%p → 탈락
    assert not improves(OFF["해외형"], s(0.20, -0.12))         # MDD 악화 → 탈락


def test_pick_single_dedupes_by_period_and_prefers_min_mdd():
    runs = [
        {"kr": 20, "us": 20, "summary": {"국내형": s(0.30, -0.10)}},   # TWR 손해 커서 탈락
        {"kr": 60, "us": 20, "summary": {"국내형": s(0.385, -0.12)}},  # 후보
        {"kr": 60, "us": 40, "summary": {"국내형": s(0.385, -0.12)}},  # kr 중복 → 1회만
        {"kr": 120, "us": 20, "summary": {"국내형": s(0.383, -0.08)}}, # 후보(|MDD| 최소) → 선정
    ]
    got = pick_single("국내형", OFF, runs, "kr")
    assert got["period"] == 120 and got["mdd"] == -0.08


def test_pick_single_none_when_no_candidate():
    runs = [{"kr": 20, "us": 20, "summary": {"국내형": s(0.10, -0.30)}}]
    assert pick_single("국내형", OFF, runs, "kr") is None


def test_pick_universal_respects_fixed_periods():
    runs = [
        {"kr": 20, "us": 20, "summary": {"범용형": s(-0.11, -0.20)}},
        {"kr": 60, "us": 20, "summary": {"범용형": s(-0.10, -0.18)}},  # kr 고정 60 → 이것만
        {"kr": 60, "us": 40, "summary": {"범용형": s(-0.09, -0.22)}},  # us≠20 → 제외
    ]
    got = pick_universal(OFF, runs, kr_p=60, us_p=20)
    assert (got["kr"], got["us"], got["mdd"]) == (60, 20, -0.18)
    # 고정 기간이 None 이면 그 축은 자유 탐색
    got_free = pick_universal(OFF, runs, kr_p=None, us_p=None)
    assert (got_free["kr"], got_free["us"]) == (60, 20)   # -0.22 는 MDD 악화(-0.26 대비 개선이지만 -0.18 이 최소)
