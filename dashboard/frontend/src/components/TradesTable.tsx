// 상세 페이지 거래내역 테이블: 일자·종목·매수/매도·수량·가격·사유·신호 배지·실현손익.
// fired[]의 G*(청신호/매수 신호)/R*(적신호/매도 신호) 코드를 배지로 표시한다.
import type { TradeOut } from "../types";
import { formatKrw, shortDate, sideLabel, signClass, signalKind } from "./format";

export interface TradesTableProps {
  trades: TradeOut[];
  className?: string;
}

function SignalBadges({ fired }: { fired: string[] }) {
  if (fired.length === 0) return <span className="detail-table__no-signal">—</span>;
  return (
    <span className="detail-table__signals">
      {fired.map((code) => (
        <span key={code} className={`badge badge--signal-${signalKind(code)}`}>
          {code}
        </span>
      ))}
    </span>
  );
}

export function TradesTable({ trades, className }: TradesTableProps) {
  if (trades.length === 0) {
    return (
      <div className={className}>
        <div className="detail-panel__state">거래 내역이 없습니다.</div>
      </div>
    );
  }

  return (
    <div className={className} style={{ overflowX: "auto" }}>
      <table className="detail-table">
        <thead>
          <tr>
            <th>일자</th>
            <th>종목</th>
            <th>구분</th>
            <th>수량</th>
            <th>가격</th>
            <th>사유</th>
            <th>신호</th>
            <th>실현손익</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => {
            const side = sideLabel(trade.side);
            const sideClass = side === "매수" ? "up" : side === "매도" ? "down" : "neutral";
            return (
              <tr key={`${trade.ts}:${trade.symbol}:${trade.side}`}>
                <td>{shortDate(trade.date || trade.ts)}</td>
                <td>
                  <span className="detail-table__symbol">{trade.symbol}</span>
                  <span className="detail-table__market">{trade.market}</span>
                </td>
                <td className={sideClass}>{side}</td>
                <td>{trade.quantity.toLocaleString("ko-KR")}</td>
                <td>{formatKrw(trade.price)}</td>
                <td className="detail-table__reason">{trade.reason}</td>
                <td>
                  <SignalBadges fired={trade.fired} />
                </td>
                <td className={signClass(trade.realized_pnl)}>{formatKrw(trade.realized_pnl)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default TradesTable;
