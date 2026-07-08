from simcore.live.ratelimit import RateLimiter


def test_allows_burst_then_throttles():
    now = [0.0]
    slept = []
    limiter = RateLimiter(rate_per_sec=2.0,
                          clock=lambda: now[0],
                          sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    limiter.acquire()  # 즉시
    limiter.acquire()  # 즉시 (버킷 2개)
    limiter.acquire()  # 세 번째는 대기
    assert slept and slept[-1] > 0
