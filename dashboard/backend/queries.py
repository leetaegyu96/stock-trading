"""대시보드 백엔드 — Postgres 조회 (simcore.live.db ORM 재사용, 읽기 전용)."""
from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import func, select

from simcore.live import db
from simcore.live.repository import Repository
from simcore.names import display_name


def list_characters(sf) -> list[dict]:
    """등록된 전체 캐릭터 목록."""
    with sf() as s:
        rows = s.execute(select(db.CharacterRow)).scalars().all()
        return [{"name": r.name, "base_currency": r.base_currency} for r in rows]


def positions(sf, name: str) -> list[dict]:
    """캐릭터의 보유 종목."""
    with sf() as s:
        rows = s.execute(
            select(db.PositionRow)
            .where(db.PositionRow.character == name)
            .order_by(db.PositionRow.symbol)
        ).scalars().all()
        return [
            {
                "symbol": r.symbol,
                "name": display_name(r.symbol, r.market),
                "market": r.market,
                "quantity": r.quantity,
                "avg_price": r.avg_price,
                "opened_date": r.opened_date,
            }
            for r in rows
        ]


def _trade_dict(r: db.TradeRow) -> dict:
    return {
        "ts": r.ts,
        "date": r.date,
        "symbol": r.symbol,
        "name": display_name(r.symbol, r.market),
        "market": r.market,
        "side": r.side,
        "quantity": r.quantity,
        "price": r.price,
        "fee": r.fee,
        "tax": r.tax,
        "reason": r.reason,
        "green_count": r.green_count,
        "red_count": r.red_count,
        "green_score": r.green_score,
        "red_score": r.red_score,
        "fired": list(r.fired or []),
        "realized_pnl": r.realized_pnl,
        "decision_type": r.decision_type,
        "trigger_rule": r.trigger_rule,
    }


def trades(
    sf,
    name: str,
    limit: int = 20,
    offset: int = 0,
    symbol: str | None = None,
    side: str | None = None,
    decision_type: str | None = None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
) -> dict:
    """캐릭터의 거래 내역(최신순) — 필터+페이지네이션.

    반환: {"items": [...거래 dict...], "total": int}. total 은 limit/offset 적용
    전, 같은 필터 조건에서의 전체 건수(페이지 UI가 전체 페이지 수를 계산할 수 있게)."""
    conditions = [db.TradeRow.character == name]
    if symbol is not None:
        conditions.append(db.TradeRow.symbol == symbol)
    if side is not None:
        conditions.append(db.TradeRow.side == side)
    if decision_type is not None:
        conditions.append(db.TradeRow.decision_type == decision_type)
    if date_from is not None:
        conditions.append(db.TradeRow.date >= date_from)
    if date_to is not None:
        conditions.append(db.TradeRow.date <= date_to)

    with sf() as s:
        total = s.execute(
            select(func.count()).select_from(db.TradeRow).where(*conditions)
        ).scalar_one()
        rows = s.execute(
            select(db.TradeRow)
            .where(*conditions)
            .order_by(db.TradeRow.ts.desc(), db.TradeRow.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars().all()
        return {"items": [_trade_dict(r) for r in rows], "total": total}


def _all_trades(sf, name: str) -> list[dict]:
    """페이지네이션 없이 캐릭터 전체 거래 이력(집계용: 승률/n_trades 등 — 요청 경로
    에서 전체 이력을 필요로 하는 내부 호출부 전용). 순서는 trades()와 동일(최신순)."""
    return trades(sf, name, limit=1_000_000)["items"]


def position_lifecycles(sf, name: str, limit: int = 10) -> list[dict]:
    """캐릭터의 포지션 생애(진입→청산) 그룹핑 — 종목별 보유수량을 시간순으로 추적한다.

    규칙: 보유수량이 0인 상태에서 BUY가 오면 새 생애 시작. SELL은 수량을 줄이고,
    0(또는 그 이하 — 데이터 이상으로 초과매도가 있어도 크래시하지 않도록 방어)에
    도달하면 그 생애를 종료(exit_date 기록)한다. 청산 후 재매수는 별도의 새 생애.

    엣지 케이스: 시드 데이터가 이력 중간부터 시작해 사전 BUY 없이 SELL이 먼저
    나타나는 경우(orphan SELL) — 대응하는 생애가 없으므로 크래시하지 않고 그
    거래를 건너뛴다(어떤 생애에도 포함되지 않음)."""
    with sf() as s:
        rows = s.execute(
            select(db.TradeRow)
            .where(db.TradeRow.character == name)
            .order_by(db.TradeRow.ts, db.TradeRow.id)
        ).scalars().all()

    lifecycles: list[dict] = []
    open_by_symbol: dict[str, dict] = {}
    qty_by_symbol: dict[str, int] = {}

    for r in rows:
        symbol = r.symbol
        current_qty = qty_by_symbol.get(symbol, 0)
        trade = _trade_dict(r)

        if r.side == "BUY":
            if current_qty == 0:
                life = {
                    "symbol": symbol,
                    "name": display_name(symbol, r.market),
                    "market": r.market,
                    "entry_date": r.date,
                    "exit_date": None,
                    "open": True,
                    "trades": [],
                    "qty_peak": 0,
                    "realized_pnl_sum": 0.0,
                    "entry_trigger": r.trigger_rule,
                }
                open_by_symbol[symbol] = life
                lifecycles.append(life)
            life = open_by_symbol[symbol]
            life["trades"].append(trade)
            current_qty += r.quantity
            life["qty_peak"] = max(life["qty_peak"], current_qty)
            qty_by_symbol[symbol] = current_qty
        else:  # SELL
            life = open_by_symbol.get(symbol)
            if life is None:
                # orphan SELL: 대응하는 생애가 없다(시드가 이력 중간부터 시작하는
                # 경우 등) — 스킵하고 계속 진행(크래시 방지).
                continue
            life["trades"].append(trade)
            life["realized_pnl_sum"] += r.realized_pnl
            current_qty -= r.quantity
            if current_qty <= 0:
                life["exit_date"] = r.date
                life["open"] = False
                current_qty = 0
                del open_by_symbol[symbol]
            qty_by_symbol[symbol] = current_qty

    # 진행중(open) 생애는 오래된 것이라도 limit에 밀려 누락되면 안 되므로,
    # truncate 전에 open/closed로 분리한다 — open은 전부 선택하고(최신 entry_date
    # 우선), 남은 자리를 가장 최근에 진입한 closed 생애로 채운다.
    lifecycles.sort(key=lambda life: life["entry_date"], reverse=True)
    open_lifecycles = [life for life in lifecycles if life["open"]]
    closed_lifecycles = [life for life in lifecycles if not life["open"]]
    remaining = max(limit - len(open_lifecycles), 0)
    return open_lifecycles + closed_lifecycles[:remaining]


def flows(sf, name: str) -> list[dict]:
    """캐릭터의 입출금(자본 흐름) 이력, 날짜순."""
    with sf() as s:
        rows = s.execute(
            select(db.CapitalFlowRow)
            .where(db.CapitalFlowRow.character == name)
            .order_by(db.CapitalFlowRow.date, db.CapitalFlowRow.id)
        ).scalars().all()
        return [
            {
                "date": r.date,
                "amount_krw": r.amount_krw,
                "fx_rate": r.fx_rate,
            }
            for r in rows
        ]


def equity_series(sf, name: str) -> list[tuple[datetime, float]]:
    """캐릭터의 자산곡선(시각순)."""
    with sf() as s:
        rows = s.execute(
            select(db.EquityPoint)
            .where(db.EquityPoint.character == name)
            .order_by(db.EquityPoint.ts)
        ).scalars().all()
        return [(r.ts, r.equity_krw) for r in rows]


def last_prices(sf, positions: list[dict]) -> dict[str, float]:
    """보유 종목의 daily_bars 최신 종가. 없으면 비워두어 summary 쪽 avg_price 폴백에 맡긴다."""
    repo = Repository(sf)
    prices: dict[str, float] = {}
    for pos in positions:
        bars = repo.load_daily_bars(pos["market"], pos["symbol"])
        if not bars.empty:
            prices[pos["symbol"]] = float(bars["close"].iloc[-1])
    return prices


def universe_movers(sf, top: int = 5) -> dict:
    """daily_bars 최근 2봉으로 시장별 등락률 상/하위 top."""
    with sf() as s:
        rows = s.execute(select(db.DailyBarRow)
                         .order_by(db.DailyBarRow.symbol, db.DailyBarRow.date)).scalars().all()
    by_sym: dict[tuple, list] = {}
    for r in rows:
        by_sym.setdefault((r.market, r.symbol), []).append(r)
    changes: dict[str, list] = {"KR": [], "US": []}
    for (market, symbol), bars in by_sym.items():
        if len(bars) < 2:
            continue
        prev, last = bars[-2].close, bars[-1].close
        if prev:
            changes.setdefault(market, []).append(
                {"symbol": symbol, "market": market, "close": last,
                 "change_pct": last / prev - 1.0})
    out = {}
    for market, lst in changes.items():
        lst.sort(key=lambda x: x["change_pct"])
        out[market] = {"down": lst[:top], "up": list(reversed(lst[-top:]))}
    return out


def recent_trades(sf, limit: int = 12) -> list[dict]:
    """전체 캐릭터 통합 최신 체결 N건."""
    with sf() as s:
        rows = s.execute(select(db.TradeRow)
                         .order_by(db.TradeRow.ts.desc(), db.TradeRow.id.desc())
                         .limit(limit)).scalars().all()
        return [{"character": r.character, "symbol": r.symbol, "market": r.market,
                 "side": r.side, "reason": r.reason, "realized_pnl": r.realized_pnl,
                 "date": r.date, "decision_type": r.decision_type,
                 "trigger_rule": r.trigger_rule} for r in rows]


def benchmark(sf, name: str) -> dict | None:
    """캐릭터의 벤치마크(지수) 수익률 스냅샷. 시딩 안 됐으면 None —
    호출부(summary)가 이를 '숨기지 않고' benchmark_available=False 로 노출해야 한다."""
    with sf() as s:
        row = s.execute(
            select(db.BenchmarkRow).where(db.BenchmarkRow.character == name)
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "benchmark_return": row.benchmark_return,
            "benchmark_name": row.benchmark_name,
            "ts": row.ts,
        }


def market_status(sf) -> list[dict]:
    """시장별 데이터 기준(run_state) — as-of 표시용."""
    with sf() as s:
        rows = s.execute(select(db.RunState)).scalars().all()
        return [{"market": r.market,
                 "last_close_date": r.last_close_date.isoformat() if r.last_close_date else None,
                 "last_open_date": r.last_open_date.isoformat() if r.last_open_date else None}
                for r in rows]


def cash(sf, name: str) -> dict[str, float]:
    """캐릭터의 통화별 현금 잔고."""
    with sf() as s:
        rows = s.execute(
            select(db.CashBalance).where(db.CashBalance.character == name)
        ).scalars().all()
        return {r.currency: r.amount for r in rows}
