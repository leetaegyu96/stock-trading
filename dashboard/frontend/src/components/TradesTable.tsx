// 거래내역 테이블: 매수/매도 칩, 사유 한글 라벨 칩(손절/익절 강조),
// 켜진 청/적신호 배지, 실현손익(매수는 — 처리, 시장 통화 표기).
import type { TradeOut } from "../types";
import {
  formatPrice,
  formatSignedPrice,
  reasonInfo,
  shortDate,
  sideLabel,
  signClass,
  signalKind,
} from "./format";

export interface TradesTableProps {
  trades: TradeOut[];
  className?: string;
}

function SignalBadges({ fired }: { fired: string[] }) {
  if (fired.length === 0) return <span className="muted">—</span>;
  return (
    <span className="detail-table__signals">
      {fired.map((code) => (
        <span key={code} className={`sig sig--${signalKind(code)}`}>
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
            <th className="ta-r">수량</th>
            <th className="ta-r">체결가</th>
            <th>사유</th>
            <th>신호</th>
            <th className="ta-r">실현손익</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => {
            const side = sideLabel(trade.side);
            const isBuy = side === "매수";
            const reason = reasonInfo(trade.reason);
            return (
              <tr key={`${trade.ts}:${trade.symbol}:${trade.side}`}>
                <td className="num muted">{shortDate(trade.date || trade.ts)}</td>
                <td>
                  <span className="detail-table__symbol">{trade.symbol}</span>
                  <span className={`mkt mkt--${trade.market.toLowerCase()}`}>{trade.market}</span>
                </td>
                <td>
                  <span className={`chip chip--${isBuy ? "up" : "down"}`}>{side}</span>
                </td>
                <td className="ta-r num">{trade.quantity.toLocaleString("ko-KR")}</td>
                <td className="ta-r num">{formatPrice(trade.market, trade.price)}</td>
                <td>
                  <span className={`reason reason--${reason.kind}`}>{reason.label}</span>
                </td>
                <td>
                  <SignalBadges fired={trade.fired} />
                </td>
                <td className={`ta-r num strong ${isBuy ? "muted" : signClass(trade.realized_pnl)}`}>
                  {isBuy ? "—" : formatSignedPrice(trade.market, trade.realized_pnl)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default TradesTable;
