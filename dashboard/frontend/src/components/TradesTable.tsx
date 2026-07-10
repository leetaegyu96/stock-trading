// 거래내역 테이블: 매수/매도 칩, 사유 한글 라벨 칩(손절/익절 강조),
// 신호 한 줄 요약(🟢/🔴 + signal_summary) + 펼치면 이름·별점 상세.
import { useState } from "react";
import type { TradeOut } from "../types";
import {
  NEWS_FLOW_DISCLAIMER,
  SIGNAL_AXIS_LABEL,
  TECH_AXIS_ONLY_BADGE,
  UNCOMPUTED_AXIS_LABEL,
  decisionInfo,
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

/** 결정유형 칩(부분/전량/강제매도). BUY/미분류는 칩을 그리지 않는다 —
 * "구분" 열의 매수/매도 칩으로 이미 충분하고, 이 칩은 매도의 강도만 보탠다. */
function DecisionChip({ decisionType }: { decisionType: string }) {
  const info = decisionInfo(decisionType);
  if (info.kind === "buy" || info.kind === "unknown") return null;
  return <span className={`chip chip--${info.kind}`}>{info.label}</span>;
}

/** 신호 표시 상단 고지: 라벨을 "청/적신호"가 아닌 "기술적 매수/매도 신호"로 통일하고,
 * Phase A엔 기술적 축만 계산된다는 점 + 뉴스·공시·수급 미반영을 항상 함께 보여준다(P0-2).
 * 미계산 축은 0점으로 위장하지 않고 UNCOMPUTED_AXIS_LABEL("미수집/판단 불가")로
 * 명시적으로 표시한다 — 조용히 생략하지 않는다. */
function SignalNotice() {
  return (
    <div className="signal-notice">
      <span className="signal-notice__title">{SIGNAL_AXIS_LABEL}</span>
      <span className="signal-notice__badge">{TECH_AXIS_ONLY_BADGE}</span>
      <p className="signal-notice__disclaimer">{NEWS_FLOW_DISCLAIMER}</p>
      <p className="signal-notice__axis">
        뉴스 · 공시 · 수급 · 거시: {UNCOMPUTED_AXIS_LABEL}
      </p>
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
    <div className={className}>
      <SignalNotice />
      <div style={{ overflowX: "auto" }}>
        <table className="detail-table">
          <thead>
            <tr>
              <th>일자</th>
              <th>종목</th>
              <th>구분</th>
              <th className="ta-r">수량</th>
              <th className="ta-r">체결가</th>
              <th>사유</th>
              <th>{SIGNAL_AXIS_LABEL}</th>
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
                    <span className={`chip chip--${isBuy ? "up" : "down"}`}>{side}</span>{" "}
                    <DecisionChip decisionType={trade.decision_type} />
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
    </div>
  );
}

export default TradesTable;
