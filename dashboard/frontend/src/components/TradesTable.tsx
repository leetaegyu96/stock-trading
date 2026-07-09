// 거래내역 테이블: 매수/매도 칩, 사유 한글 라벨 칩(손절/익절 강조),
// 신호 한 줄 요약(🟢/🔴 + signal_summary) + 펼치면 이름·별점 상세.
import { useState } from "react";
import type { TradeOut } from "../types";
import {
  formatPrice,
  formatSignedPrice,
  reasonInfo,
  shortDate,
  sideLabel,
  signClass,
  signalKind,
  starString,
} from "./format";

export interface TradesTableProps {
  trades: TradeOut[];
  className?: string;
}

function SignalCell({ trade }: { trade: TradeOut }) {
  const [expanded, setExpanded] = useState(false);
  const isBuy = sideLabel(trade.side) === "매수";
  const hasSummary = trade.signal_summary.trim().length > 0;
  const hasDetail = trade.signal_detail.length > 0;

  if (!hasSummary && !hasDetail) return <span className="muted">—</span>;

  return (
    <div className="signal-cell">
      <div className="signal-cell__summary">
        <span aria-hidden="true">{isBuy ? "🟢" : "🔴"}</span>
        <span>{hasSummary ? trade.signal_summary : "—"}</span>
        {hasDetail && (
          <button
            type="button"
            className="signal-cell__toggle"
            onClick={() => setExpanded((prev) => !prev)}
          >
            {expanded ? "접기 ˄" : "펼쳐보기 ˅"}
          </button>
        )}
      </div>
      {expanded && hasDetail && (
        <ul className="signal-cell__detail">
          {trade.signal_detail.map((d) => (
            <li key={d.code} className="signal-cell__detail-item">
              <span className={`signal-cell__detail-dot sig--${signalKind(d.code)}`} aria-hidden="true" />
              <span className="signal-cell__detail-name">{d.name}</span>
              <span className="signal-cell__stars" aria-label={`별점 ${d.stars}점`}>
                {starString(d.stars)}
              </span>
              <span className="signal-cell__detail-code muted">{d.code}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
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
                  <span className="detail-table__name">{trade.name}</span>
                  <span className="detail-table__code">{trade.symbol}</span>
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
                <td className="signal-cell-td">
                  <SignalCell trade={trade} />
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
