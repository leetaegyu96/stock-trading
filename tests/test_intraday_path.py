"""일봉 OHLC → 장중 슬라이스 근사 (simcore.intraday_path)."""
import pytest

from simcore.intraday_path import PATH_ORDERS, day_slices


def test_no_slices_when_n_is_zero_or_negative():
    assert day_slices(10, 12, 9, 11, 1000, 0) == []
    assert day_slices(10, 12, 9, 11, 1000, -3) == []


def test_slice_count_and_fractions_are_interior():
    sl = day_slices(100, 110, 90, 105, 1000, 4)
    assert len(sl) == 4
    assert [s.index for s in sl] == [1, 2, 3, 4]
    # k/(n+1) — 구간 내부만, 종가(1.0)는 포함하지 않는다
    assert [round(s.fraction, 4) for s in sl] == [0.2, 0.4, 0.6, 0.8]
    assert all(0.0 < s.fraction < 1.0 for s in sl)


@pytest.mark.parametrize("order", PATH_ORDERS)
def test_prices_stay_within_day_range(order):
    o, h, l, c = 100.0, 112.0, 88.0, 104.0
    for s in day_slices(o, h, l, c, 1000, 12, order):
        assert l <= s.close <= h
        assert l <= s.low <= s.high <= h


@pytest.mark.parametrize("order", PATH_ORDERS)
def test_running_extremes_are_monotonic(order):
    """high/low 는 그 시점까지의 누적 극값 — 미래 정보를 미리 흘리면 안 된다."""
    sl = day_slices(100, 112, 88, 104, 1000, 10, order)
    for a, b in zip(sl, sl[1:]):
        assert b.high >= a.high
        assert b.low <= a.low
    assert sl[0].high >= sl[0].open >= sl[0].low


def test_open_is_fixed_across_slices():
    sl = day_slices(100, 110, 90, 105, 1000, 6)
    assert {s.open for s in sl} == {100.0}


def test_low_first_reaches_low_before_high():
    sl = day_slices(100, 110, 90, 105, 1000, 12, "low_first")
    first_low = next(i for i, s in enumerate(sl) if s.low == 90)
    first_high = next(i for i, s in enumerate(sl) if s.high == 110)
    assert first_low < first_high


def test_high_first_reaches_high_before_low():
    sl = day_slices(100, 110, 90, 105, 1000, 12, "high_first")
    first_high = next(i for i, s in enumerate(sl) if s.high == 110)
    first_low = next(i for i, s in enumerate(sl) if s.low == 90)
    assert first_high < first_low


def test_traversed_extremes_capture_vertices_between_samples():
    """두 샘플 사이에서 찍고 되돌아온 저가·고가를 놓치지 않아야 한다.

    샘플 지점만으로 극값을 잡으면 손절선을 스친 날을 통째로 흘려버린다.
    """
    sl = day_slices(100, 110, 90, 105, 1000, 12, "low_first")
    assert min(s.close for s in sl) > 90, "샘플 지점 자체는 저가에 정확히 닿지 않는다"
    assert min(s.low for s in sl) == 90, "그래도 지나간 저가는 반영돼야 한다"
    assert max(s.high for s in sl) == 110
    # 저가를 품은 슬라이스는 seg_low 로도 그 사실을 알린다
    assert any(s.seg_low == 90 for s in sl)
    assert any(s.seg_high == 110 for s in sl)


def test_segment_extremes_bound_the_step():
    """seg_low/seg_high 는 직전 종가와 현재 종가를 모두 감싼다."""
    sl = day_slices(100, 112, 88, 104, 1000, 8, "low_first")
    prev = 100.0
    for s in sl:
        assert s.seg_low <= min(prev, s.close)
        assert s.seg_high >= max(prev, s.close)
        prev = s.close


def test_final_slice_extremes_approach_the_day_bar():
    """마지막 슬라이스의 누적 고저는 일봉의 고저와 일치한다(경로가 둘 다 밟으므로)."""
    sl = day_slices(100, 112, 88, 104, 1000, 8, "low_first")
    assert sl[-1].low == 88 and sl[-1].high == 112


def test_orders_differ_for_a_ranged_day():
    a = day_slices(100, 110, 90, 105, 1000, 6, "low_first")
    b = day_slices(100, 110, 90, 105, 1000, 6, "high_first")
    assert [s.close for s in a] != [s.close for s in b]


def test_volume_accumulates_linearly():
    sl = day_slices(100, 110, 90, 105, 1000.0, 4)
    assert [round(s.volume, 6) for s in sl] == [200.0, 400.0, 600.0, 800.0]
    assert all(s.volume < 1000.0 for s in sl)      # 항상 하루치 미만(=누적 중)


def test_flat_day_produces_constant_path():
    sl = day_slices(50, 50, 50, 50, 999.0, 5)
    assert {s.close for s in sl} == {50.0}
    assert {s.high for s in sl} == {50.0} and {s.low for s in sl} == {50.0}


def test_rejects_inconsistent_ohlc():
    with pytest.raises(ValueError, match="OHLC"):
        day_slices(open_=100, high=90, low=95, close=97, volume=1, n=3)


def test_rejects_unknown_order():
    with pytest.raises(ValueError, match="경로 순서"):
        day_slices(100, 110, 90, 105, 1000, 3, order="sideways")   # type: ignore[arg-type]


def test_deterministic():
    args = (100, 113, 87, 92, 5000, 7, "low_first")
    assert [s.close for s in day_slices(*args)] == [s.close for s in day_slices(*args)]
