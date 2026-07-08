"""대시보드 카드/상세 집계 — simcore.metrics 재사용.

equity_curve 의 ts(장마감 시각)와 capital_flows 의 date(날짜)를 같은 거래일 인덱스로
맞추기 위해 equity 타임스탬프를 자정으로 정규화한다. capital_flows 는 replay.run_replay
와 동일하게 첫 건(초기입금)을 제외하고 나머지만 순입출금으로 반영한다.

주의(한계): 이 정규화는 "같은 날 중복 포인트"(simcore/live/orchestrator.on_close 가
KR·US 마감마다 하루 2회 equity 를 기록)만 하루 1점으로 접어 해결한다. on_close 는
equity 를 서버 벽시계(datetime.now())로 기록하므로, KST 서버 기준 US 세션 마감은
자정을 넘겨 flow 의 거래일(date=d)보다 하루 뒤 버킷에 잡힐 수 있다 — 이 cross-midnight
귀속 어긋남은 여기서 해결하지 못하며, US 측 입출금 전후 TWR/PNL 이 하루 어긋날 수 있다.
근본 해결은 simcore/live 후속 과제(EquityPoint 에 세션 거래일을 별도 저장)로 추적한다.
"""
from __future__ import annotations

import pandas as pd

from simcore import metrics
from simcore.engine import DEFAULT_CHARACTERS
from simcore.models import Market

from dashboard.backend import queries
from dashboard.backend.schemas import CardSummary, Metrics

_SPARK_POINTS = 30
_ALL_TRADES_LIMIT = 1_000_000  # win_rate/n_trades 는 페이지네이션 없이 전체 이력을 봐야 함
_SPEC_BY_NAME = {s.name: s for s in DEFAULT_CHARACTERS}


def _character_identity(name: str) -> tuple[str, list[str]]:
    """DEFAULT_CHARACTERS(국내형/해외형/범용형)에서 base_currency/markets 매핑.
    테스트 등 알 수 없는 이름은 기본값(KRW, markets 없음)으로 폴백한다."""
    spec = _SPEC_BY_NAME.get(name)
    if spec is None:
        return "KRW", []
    return spec.base_currency.value, [m.value for m in spec.markets]


def _equity_series(sf, name: str) -> pd.Series:
    """자산곡선을 거래일(자정 정규화) 인덱스의 pd.Series 로 변환. 같은 날 여러 점이면 마지막 값 사용."""
    rows = queries.equity_series(sf, name)
    if not rows:
        return pd.Series(dtype="float64")
    idx = pd.DatetimeIndex([pd.Timestamp(ts).normalize() for ts, _ in rows])
    s = pd.Series([float(eq) for _, eq in rows], index=idx)
    return s.groupby(level=0).last()


def _flow_series(sf, name: str) -> pd.Series:
    """순입출금 시계열. 첫 건(초기자금)은 제외 — replay.run_replay 의 flows[1:] 와 동일 패턴."""
    rows = queries.flows(sf, name)
    if len(rows) <= 1:
        return pd.Series(dtype="float64")
    rest = rows[1:]
    idx = pd.DatetimeIndex([pd.Timestamp(r["date"]).normalize() for r in rest])
    s = pd.Series([float(r["amount_krw"]) for r in rest], index=idx)
    return s.groupby(level=0).sum()


def _twr_and_pnl(eq: pd.Series, flows: pd.Series) -> tuple[float, float]:
    twr = metrics.time_weighted_return(eq, flows)
    pnl = metrics.simple_pnl_krw(eq, flows)
    return twr, pnl


def _today_pnl_pct(eq: pd.Series) -> float:
    if len(eq) < 2:
        return 0.0
    prev, last = eq.iloc[-2], eq.iloc[-1]
    if prev == 0:
        return 0.0
    return float(last / prev - 1.0)


def _position_value_krw(pos: dict, last_prices: dict[str, float], fx_rate: float) -> float:
    price = last_prices.get(pos["symbol"], pos["avg_price"])
    value = pos["quantity"] * price
    return value * fx_rate if pos["market"] == Market.US.value else value


def card_summary(sf, name: str, fx_rate: float, last_prices: dict[str, float]) -> CardSummary:
    """카드용 요약: 총자산·TWR·손익·오늘등락·스파크라인·보유종목수·현금."""
    eq = _equity_series(sf, name)
    flows = _flow_series(sf, name)
    twr, pnl_krw = _twr_and_pnl(eq, flows)

    positions = queries.positions(sf, name)
    cash = queries.cash(sf, name)
    cash_krw = cash.get("KRW", 0.0) + cash.get("USD", 0.0) * fx_rate
    positions_krw = sum(_position_value_krw(p, last_prices, fx_rate) for p in positions)

    base_currency, markets = _character_identity(name)

    return CardSummary(
        name=name,
        base_currency=base_currency,
        markets=markets,
        benchmark_delta=None,
        total_asset_krw=cash_krw + positions_krw,
        twr=twr,
        pnl_krw=pnl_krw,
        today_pnl_pct=_today_pnl_pct(eq),
        equity_spark=[float(v) for v in eq.iloc[-_SPARK_POINTS:]],
        n_positions=len(positions),
        cash_krw=cash_krw,
    )


def _win_rate(trades: list[dict]) -> float:
    sells = [t for t in trades if t["side"] == "SELL"]
    if not sells:
        return 0.0
    wins = sum(1 for t in sells if t["realized_pnl"] > 0)
    return wins / len(sells)


def detail_metrics(sf, name: str) -> Metrics:
    """상세 지표: TWR·MDD·거래건수·승률·손익."""
    eq = _equity_series(sf, name)
    flows = _flow_series(sf, name)
    twr, pnl_krw = _twr_and_pnl(eq, flows)
    mdd = metrics.max_drawdown(eq)

    all_trades = queries.trades(sf, name, limit=_ALL_TRADES_LIMIT)
    return Metrics(
        twr=twr,
        mdd=mdd,
        n_trades=len(all_trades),
        win_rate=_win_rate(all_trades),
        pnl_krw=pnl_krw,
    )
