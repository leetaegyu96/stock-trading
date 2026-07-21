"""보유 종목 signal_status 행 생성 공용 헬퍼.

run_replay(simcore/replay.py) 와 Orchestrator._signal_status_rows
(simcore/live/orchestrator.py) 두 곳이 각자 인라인으로 '보유' 상태 행을
만들면서 stop_px/trail_px 공식이 어긋날 위험이 있었다(감사 Phase B 후속,
#7). 두 호출부의 기존 공식을 그대로 옮겨 하나로 통합한다."""
from __future__ import annotations
from datetime import date as Date

from simcore.models import Market, Position


def holding_signal_row(*, date: Date, character: str, symbol: str, market: Market,
                       pos: Position, red_score: int, close: float | None,
                       trail_pct: float, trailing_top: float) -> dict:
    """kind="보유" signal_status 행을 만든다.

    stop_px = avg_price*(1+locked_stop_pct), trail_px 는 peak_gain(=peak/avg-1)
    이 trailing_top 이상일 때만 peak_price*(1-trail_pct), 아니면 None."""
    stop_px = pos.avg_price * (1 + pos.locked_stop_pct)
    peak_gain = pos.peak_price / pos.avg_price - 1.0
    trail_px = (pos.peak_price * (1 - trail_pct)
                if peak_gain >= trailing_top else None)
    return {
        "date": date, "character": character, "symbol": symbol,
        "market": market.value, "kind": "보유",
        "green_score": 0, "red_score": red_score,
        "buy_gate": False, "status": "", "block_reason": "",
        "stop_px": stop_px, "trail_px": trail_px,
        "close": close,
    }
