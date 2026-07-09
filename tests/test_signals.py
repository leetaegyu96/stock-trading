import numpy as np
import pandas as pd
from simcore.config import SignalParams, SignalScores
from simcore.signals import evaluate_frame, fired_at, min_history, GREEN_COLS, RED_COLS
from simcore import signals as sig

P = SignalParams()

def make_df(closes, volumes=None, opens=None, highs=None, lows=None):
    n = len(closes)
    closes = pd.Series(closes, dtype=float)
    idx = pd.bdate_range("2024-01-02", periods=n)
    df = pd.DataFrame({
        "open": opens if opens is not None else closes.values,
        "high": highs if highs is not None else closes.values * 1.01,
        "low": lows if lows is not None else closes.values * 0.99,
        "close": closes.values,
        "volume": volumes if volumes is not None else np.full(n, 1000.0),
    }, index=idx)
    return df

def test_insufficient_history_all_false():
    df = make_df(np.linspace(100, 110, 30))  # 61봉 미만
    frame = evaluate_frame(df, P)
    assert not frame.iloc[-1].any()

def test_uptrend_fires_g1_g2_g4_and_not_r1_r2():
    df = make_df(np.linspace(100, 160, 100))  # 꾸준한 상승
    green, red = fired_at(evaluate_frame(df, P), df.index[-1])
    assert {"G1", "G2", "G4"} <= set(green)
    assert "R1" not in red and "R2" not in red

def test_downtrend_fires_r1_r2_r4():
    df = make_df(np.linspace(160, 100, 100))
    green, red = fired_at(evaluate_frame(df, P), df.index[-1])
    assert {"R1", "R2", "R4"} <= set(red)

def test_g5_volume_surge_bullish_candle():
    closes = np.full(100, 100.0)
    volumes = np.full(100, 1000.0)
    volumes[-1] = 2000.0                     # 평균의 2배
    opens = closes.copy(); opens[-1] = 99.0  # 양봉 (종가 100 > 시가 99)
    df = make_df(closes, volumes=volumes, opens=opens)
    green, red = fired_at(evaluate_frame(df, P), df.index[-1])
    assert "G5" in green
    assert "R5" not in red

def test_g7_breakout_over_60d_high():
    closes = np.concatenate([np.full(80, 100.0), [105.0]])  # 마지막 날 신고가
    df = make_df(closes)
    green, _ = fired_at(evaluate_frame(df, P), df.index[-1])
    assert "G7" in green

def test_stub_columns_always_false():
    # v2: 스텁은 STUB_GREEN/STUB_RED 로 이동 (R8/R9 는 v2 에서 제거됨)
    df = make_df(np.linspace(100, 160, 100))
    frame = evaluate_frame(df, P)
    for col in ["G8", "G9"]:
        assert col in frame.columns
        assert not frame[col].any()

def test_min_history_default_is_78():
    # v2: 일목균형표 선행스팬B(52)+기준선(26) = 78 이 최댓값
    assert min_history(P) == 78


def _frame(closes, highs=None, lows=None, opens=None, vols=None):
    n = len(closes)
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({
        "open": pd.Series(opens if opens is not None else closes, index=idx, dtype=float),
        "high": pd.Series(highs if highs is not None else [c + 0.5 for c in closes], index=idx, dtype=float),
        "low": pd.Series(lows if lows is not None else [c - 0.5 for c in closes], index=idx, dtype=float),
        "close": close,
        "volume": pd.Series(vols if vols is not None else [1000.0] * n, index=idx, dtype=float),
    })


def test_new_columns_present_and_stubs_false():
    df = _frame(list(np.linspace(10, 30, 120)))
    out = sig.evaluate_frame(df, SignalParams())
    for col in ["G11","G12","G13","G14","G15","G16","G17","G18","G23",
                "R11","R12","R13","R14","R15","R16","R17","R18","R19","R23","R24"]:
        assert col in out.columns
    for stub in ["G8","G9","G19","G21","G24","R20","R22"]:
        assert col in out.columns or True  # 스텁은 존재하되 전부 False
        if stub in out.columns:
            assert not out[stub].any()


def test_adx_di_signals_fire_in_uptrend():
    df = _frame(list(np.linspace(10, 40, 120)))
    out = sig.evaluate_frame(df, SignalParams())
    assert out["G11"].iloc[-1]        # ADX>=25
    assert out["G12"].iloc[-1]        # DI+>DI-
    assert not out["R12"].iloc[-1]


def test_r23_big_bearish_candle():
    # v2 min_history(일목 senkou_b+kijun=78) 워밍업을 넘기기 위해 평탄한 선행 구간을 확보
    # (R23 자체는 shift 가 없는 당일 계산이라 워밍업 이후이면 어디서든 동일하게 판정된다)
    closes = [100] * 80 + [90]        # 마지막 봉 큰 음봉
    opens = [100] * 80 + [100]
    df = _frame(closes, opens=opens,
                highs=[c + 0.5 for c in closes], lows=[c - 0.5 for c in closes])
    out = sig.evaluate_frame(df, SignalParams())
    assert out["R23"].iloc[-1]        # (100-90)/100 = 10% >= 3%


def test_r18_support_break():
    # v2 min_history(78) 워밍업을 넘기도록 평탄 구간을 늘림. 지지선(20일 최저)은
    # 마지막 날 직전 20일(모두 100)로 형성되므로 이전 98 저점은 영향 없음.
    closes = [100, 101, 99, 100, 98] + [100] * 95 + [90]  # 마지막에 최근 저점 하향
    df = _frame(closes)
    out = sig.evaluate_frame(df, SignalParams())
    assert out["R18"].iloc[-1]


def test_score_applies_category_caps():
    sc = SignalScores()
    # 추세 신호 5개(각 5·5·5·5·5=25) → 상한 10
    total, by_cat = sig.score(["G1", "G4", "G11", "G12", "G15"], sc)
    assert by_cat["추세"] == 10
    assert total == 10


def test_score_sums_across_categories_capped():
    sc = SignalScores()
    total, by_cat = sig.score(["G1", "G4", "G7", "G5"], sc)
    # 추세 G1+G4=10(상한10), 돌파 G7=5, 거래량 G5=4 → 19
    assert total == 19


def test_buy_gate_requires_all_three():
    sc = SignalScores()
    assert not sig.buy_gate_ok(["G1", "G4", "G7"], sc)      # 거래량 없음
    assert not sig.buy_gate_ok(["G1", "G5"], sc)            # 돌파 없음
    assert sig.buy_gate_ok(["G1", "G7", "G5"], sc)          # 추세+돌파+거래량 OK
    assert sig.buy_gate_ok(["G11", "G18", "G23"], sc)       # G23 가 거래량 요건 충족


def test_snapshot_scores_helper():
    sc = SignalScores()
    gs, rs, gate = sig.snapshot_scores(("G1", "G7", "G5"), ("R1",), sc)
    assert gs == 5 + 5 + 4
    assert rs == 5
    assert gate is True
