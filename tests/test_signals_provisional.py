"""장중 잠정봉의 거래량 왜곡 차단 — fired_at_provisional / VOLUME_SCALE_DEPENDENT.

배경: on_intraday 는 당일 "누적" 거래량으로 잠정봉을 만드는데, 지표는 이를 전일/평균의
"완성" 거래량과 비교한다. 그래서 R24(거래량 없는 상승, 적 4점)가 장 초반 상시 점등됐다.
실측(일봉 3,278 종목일, f=0.10 vs f=1.00): R24 22.7%→49.5%(뒤집힘 26.8%),
R5 3.3%→0.0%, G5 3.0%→0.0%, G23 0.7%→0.0%. 나머지 33개는 뒤집힘 0.0%.
근거: docs/reviews/2026-09-02-live-loss-autopsy.html
"""
import pandas as pd
import pytest

from simcore.config import Config
from simcore import signals as sigmod


def _frame_with(codes: set[str]) -> tuple[pd.DataFrame, pd.Timestamp]:
    """지정 코드만 True 인 1행 프레임(발화 필터만 검증하므로 지표 계산은 불필요)."""
    ts = pd.Timestamp("2026-09-02")
    cols = sigmod.GREEN_COLS + sigmod.RED_COLS + sigmod.STUB_GREEN + sigmod.STUB_RED
    return pd.DataFrame([{c: (c in codes) for c in cols}], index=[ts]), ts


# ── 제외 집합 자체 ────────────────────────────────────────────────────────
def test_volume_scale_dependent_is_exactly_the_measured_four():
    assert sigmod.VOLUME_SCALE_DEPENDENT == {"G5", "G23", "R5", "R24"}


def test_obv_and_vwap_are_not_excluded():
    """OBV(방향=종가차 부호)와 VWAP 은 실측상 뒤집힘 0.0% — 멀쩡한 신호를 죽이면 안 된다."""
    for code in ("G13", "R13", "G14", "R14"):
        assert code not in sigmod.VOLUME_SCALE_DEPENDENT


def test_excluded_codes_all_exist_in_signal_columns():
    assert sigmod.VOLUME_SCALE_DEPENDENT <= set(sigmod.GREEN_COLS + sigmod.RED_COLS)


# ── 필터 동작 ─────────────────────────────────────────────────────────────
def test_provisional_drops_r24_keeps_the_rest():
    frame, ts = _frame_with({"R1", "R13", "R24"})
    green, red = sigmod.fired_at_provisional(frame, ts)
    assert green == ()
    assert red == ("R1", "R13")            # R24 만 빠진다


def test_provisional_drops_surge_signals():
    frame, ts = _frame_with({"G5", "G13", "G23", "R5", "R23"})
    green, red = sigmod.fired_at_provisional(frame, ts)
    assert green == ("G13",)               # G5·G23 제외
    assert red == ("R23",)                 # R5 제외


def test_provisional_is_noop_when_no_volume_signal_fires():
    codes = {"G1", "G7", "R1", "R2", "R13"}
    frame, ts = _frame_with(codes)
    assert sigmod.fired_at_provisional(frame, ts) == sigmod.fired_at(frame, ts)


def test_fired_at_unchanged_for_confirmed_bar():
    """마감 확정봉 경로(fired_at)는 그대로 R24·G5 를 반환해야 한다."""
    frame, ts = _frame_with({"G5", "R24"})
    green, red = sigmod.fired_at(frame, ts)
    assert green == ("G5",) and red == ("R24",)


def test_provisional_missing_date_returns_empty():
    frame, _ = _frame_with({"R24"})
    assert sigmod.fired_at_provisional(frame, pd.Timestamp("2020-01-01")) == ((), ())


# ── 점수 영향 ─────────────────────────────────────────────────────────────
def test_r24_removal_drops_red_score_below_full_sell():
    """추세 cap(10점) + R24(4점) = 14점 → 전량매도였던 조합이 10점으로 내려간다."""
    scores = Config().scores
    fired_confirmed = ("R1", "R4", "R24")          # 5+5(추세 cap 10) + 4
    fired_provisional = tuple(c for c in fired_confirmed
                              if c not in sigmod.VOLUME_SCALE_DEPENDENT)
    rs_conf, _ = sigmod.score(fired_confirmed, scores)
    rs_prov, _ = sigmod.score(fired_provisional, scores)
    rules = Config().rules
    assert rs_conf == 14 and rs_conf >= rules.sell_full_min
    assert rs_prov == 10 and rs_prov < rules.sell_full_min


def test_buy_gate_still_passable_intraday_via_g13():
    """거래량 관문 {G5,G13,G23} 중 G5·G23 이 빠져도 G13 으로 통과 가능해야 한다.

    라이브 매수 105건 전부가 G13 으로 통과했으므로 실질 매수 경로는 유지된다."""
    scores = Config().scores
    frame, ts = _frame_with({"G1", "G7", "G13", "G5", "G23"})
    green, _ = sigmod.fired_at_provisional(frame, ts)
    assert "G13" in green and "G5" not in green and "G23" not in green
    assert sigmod.buy_gate_ok(green, scores) is True


def test_buy_gate_fails_intraday_when_only_surge_carried_volume_slot():
    """G13 없이 G5/G23 만으로 통과하던 경우는 장중에 막힌다(의도된 보수적 동작)."""
    scores = Config().scores
    frame, ts = _frame_with({"G1", "G7", "G5", "G23"})
    green, _ = sigmod.fired_at_provisional(frame, ts)
    assert sigmod.buy_gate_ok(green, scores) is False
    # 같은 조합이 마감 확정봉에서는 통과한다
    assert sigmod.buy_gate_ok(sigmod.fired_at(frame, ts)[0], scores) is True


# ── 실제 지표 계산 경로에서의 회귀(누적 거래량 축소 시뮬) ──────────────────
@pytest.mark.parametrize("fraction", [0.05, 0.10, 0.25])
def test_partial_volume_no_longer_flips_red_score(fraction):
    """마지막 봉 거래량만 축소해도(=장중 누적) 잠정 판정의 적신호 점수가 변하지 않는다."""
    p = Config().signals
    scores = Config().scores
    n = sigmod.min_history(p) + 40
    # 완만한 상승 추세 + 일정 거래량 — R24(상승 & 거래량 감소) 가 걸리기 쉬운 형태
    close = pd.Series([100.0 + i * 0.3 for i in range(n)])
    df = pd.DataFrame({
        "open": close - 0.1, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": pd.Series([1_000_000.0] * n),
    }, index=pd.date_range("2026-01-01", periods=n, freq="B"))
    ts = df.index[-1]

    full = sigmod.evaluate_frame(df, p)
    rs_full = sigmod.score(sigmod.fired_at(full, ts)[1], scores)[0]

    part = df.copy()
    part.iloc[-1, part.columns.get_loc("volume")] *= fraction
    prov = sigmod.evaluate_frame(part, p)
    rs_prov = sigmod.score(sigmod.fired_at_provisional(prov, ts)[1], scores)[0]
    rs_naive = sigmod.score(sigmod.fired_at(prov, ts)[1], scores)[0]

    # 수정 전(naive)에는 R24 가 끼어들어 점수가 부풀려졌고, 수정 후에는 확정봉과 같다.
    assert rs_prov == sigmod.score(
        tuple(c for c in sigmod.fired_at(full, ts)[1]
              if c not in sigmod.VOLUME_SCALE_DEPENDENT), scores)[0]
    assert rs_naive >= rs_prov
    assert rs_full >= 0        # 계산이 성립함을 확인(형태 의존 값이라 절대값은 고정하지 않음)
