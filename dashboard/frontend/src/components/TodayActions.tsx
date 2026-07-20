// 오늘의 행동(의사결정판, 감사 Phase B): 캐릭터별 대기주문(BUY/SELL 결정) + 최신일
// 강제청산 경보. 전 캐릭터에 걸쳐 아무 것도 없으면 "오늘 예정된 행동 없음"을 그대로
// 보여준다(조용히 빈 화면으로 두지 않음).
import type { TodayActionsOut } from "../types";
import { formatSignedPrice, reasonInfo, shortDate, sideLabel } from "./format";

export interface TodayActionsProps {
  actions: TodayActionsOut[];
}

export function TodayActions({ actions }: TodayActionsProps) {
  const groups = actions.filter(
    (a) => a.pending_orders.length > 0 || a.forced_sell_alerts.length > 0
  );

  if (groups.length === 0) {
    return <p className="board__empty">오늘 예정된 행동 없음</p>;
  }

  return (
    <div className="today-actions">
      {groups.map((a) => (
        <div key={a.character} className="today-actions__group">
          <h4 className="today-actions__char">{a.character}</h4>
          {a.forced_sell_alerts.length > 0 && (
            <ul className="today-actions__alerts">
              {a.forced_sell_alerts.map((f) => (
                <li key={`fs:${f.symbol}`} className="today-actions__alert">
                  <span className="chip chip--forced">강제매도</span>
                  <span className="today-actions__name" title={f.symbol}>
                    {f.name}
                  </span>
                  <span className={`num ${f.realized_pnl >= 0 ? "up" : "down"}`}>
                    {formatSignedPrice(f.market, f.realized_pnl)}
                  </span>
                  <span className="muted">{shortDate(f.date)}</span>
                </li>
              ))}
            </ul>
          )}
          {a.pending_orders.length > 0 && (
            <ul className="today-actions__orders">
              {a.pending_orders.map((o, i) => {
                const side = sideLabel(o.side);
                const isBuy = side === "매수";
                const reason = o.reason ? reasonInfo(o.reason) : null;
                return (
                  <li key={`${o.symbol}:${i}`} className="today-actions__order">
                    <span className={`chip chip--${isBuy ? "up" : "down"}`}>{side}</span>
                    <span className="today-actions__name" title={o.symbol}>
                      {o.name}
                    </span>
                    {reason && <span className={`reason reason--${reason.kind}`}>{reason.label}</span>}
                    {o.trigger_rule && <span className="muted">{o.trigger_rule}</span>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

export default TodayActions;
