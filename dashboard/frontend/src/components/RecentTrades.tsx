// 최근 체결: 캐릭터·종목명·사유(한글)·손익 색.
import type { RecentTrade } from "../types";
import { formatSignedPrice, reasonInfo, shortDate, sideLabel, signClass } from "./format";

export interface RecentTradesProps {
  trades: RecentTrade[];
}

export function RecentTrades({ trades }: RecentTradesProps) {
  if (trades.length === 0) {
    return <p className="board__empty">최근 체결 내역이 없습니다.</p>;
  }

  return (
    <ul className="recent-trades">
      {trades.map((t, i) => {
        const side = sideLabel(t.side);
        const isBuy = side === "매수";
        const reason = reasonInfo(t.reason);
        return (
          <li key={`${t.date}:${t.character}:${t.symbol}:${i}`} className="recent-trades__item">
            <span className="recent-trades__char">{t.character}</span>
            <span className="recent-trades__name" title={t.symbol}>
              {t.name}
            </span>
            <span className={`chip chip--${isBuy ? "up" : "down"}`}>{side}</span>
            <span className={`reason reason--${reason.kind}`}>{reason.label}</span>
            <span className={`num recent-trades__pnl ${isBuy ? "muted" : signClass(t.realized_pnl)}`}>
              {isBuy ? "—" : formatSignedPrice(t.market, t.realized_pnl)}
            </span>
            <span className="recent-trades__date muted">{shortDate(t.date)}</span>
          </li>
        );
      })}
    </ul>
  );
}

export default RecentTrades;
