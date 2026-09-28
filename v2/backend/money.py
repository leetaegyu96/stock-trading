"""금액은 정수 최소단위(KRW=원, USD=센트)로만 다룬다 — SPEC §2.1.

부동소수로 잔고를 누적하면 오차가 쌓여 원장과 잔고가 어긋난다. 모든 내부 계산은
정수로 하고, 사람이 읽는 단위 변환은 API 경계에서만 한다.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# 통화별 최소단위 배수 — KRW 는 원 단위(소수 없음), USD 는 센트.
MINOR_PER_UNIT = {"KRW": 1, "USD": 100}

# 비용률 (SPEC §2.3). v1 simcore.config.CostModel 과 같은 값.
FEE_RATE = {"KR": Decimal("0.00015"), "US": Decimal("0.0009")}
TAX_RATE = {"KR": Decimal("0.0015"), "US": Decimal("0")}   # 매도에만 부과
FX_FEE = Decimal("0.001")


def minor_per_unit(currency: str) -> int:
    try:
        return MINOR_PER_UNIT[currency]
    except KeyError:
        raise ValueError(f"알 수 없는 통화: {currency!r}")


def to_minor(amount: float | Decimal | str, currency: str) -> int:
    """사람 단위 금액 → 최소단위 정수. 반올림은 round-half-up."""
    q = Decimal(str(amount)) * minor_per_unit(currency)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_major(minor: int, currency: str) -> Decimal:
    """최소단위 정수 → 사람 단위 Decimal (표시·직렬화용)."""
    return Decimal(minor) / minor_per_unit(currency)


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def buy_costs(gross_minor: int, market: str) -> int:
    """매수 수수료(최소단위). 필요 현금 = gross + fee."""
    return _round(Decimal(gross_minor) * FEE_RATE[market])


def sell_costs(gross_minor: int, market: str) -> tuple[int, int]:
    """매도 (수수료, 세금). 입금 = gross − fee − tax."""
    fee = _round(Decimal(gross_minor) * FEE_RATE[market])
    tax = _round(Decimal(gross_minor) * TAX_RATE[market])
    return fee, tax


def krw_to_usd_cents(krw: int, fx_rate: float) -> int:
    """원화 → 달러 센트. 환전 수수료 0.1% 차감 (계정 생성 시 1회만 — SPEC §2.1)."""
    usd = Decimal(krw) / Decimal(str(fx_rate)) * (Decimal(1) - FX_FEE)
    return _round(usd * 100)
