// 보유종목 테이블: 숫자 우측 정렬 + 등폭 숫자, 시장 통화 인지 가격 표기(₩/$),
// 손익 상승=빨강/하락=파랑, 시세 지연 시 "지연" 배지.
// 의사결정판 확장(감사 Phase B): 비중·진입사유·현재 적신호·손절가·트레일가·거리%·
// 잠재손실·매도대기·기준시각. 업종/실적일 컬럼은 데이터가 없으므로 만들지 않는다.
// 확장 필드는 SignalStatusRow(kind=보유)가 없으면 전부 null — 조용히 숨기지 않고
// "—"로 있는 그대로 노출한다.
import type { PositionOut } from "../types";
import { formatKrw, formatPrice, holdingDays, shortDate, signClass, signedPct } from "./format";

export interface PositionsTableProps {
  positions: PositionOut[];
  className?: string;
}

export function PositionsTable({ positions, className }: PositionsTableProps) {
  if (positions.length === 0) {
    return (
      <div className={className}>
        <div className="detail-panel__state">보유 종목이 없습니다.</div>
      </div>
    );
  }

  return (
    <div className={className} style={{ overflowX: "auto" }}>
      <table className="detail-table">
        <thead>
          <tr>
            <th>종목</th>
            <th className="ta-r">수량</th>
            <th className="ta-r">평단가</th>
            <th className="ta-r">현재가</th>
            <th className="ta-r">평가액</th>
            <th className="ta-r">손익률</th>
            <th className="ta-r">보유일</th>
            <th className="ta-r">비중</th>
            <th>진입사유</th>
            <th className="ta-r">현재 적신호</th>
            <th className="ta-r">손절가</th>
            <th className="ta-r">트레일가</th>
            <th className="ta-r">거리%</th>
            <th className="ta-r">잠재손실</th>
            <th>매도대기</th>
            <th>기준시각</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => {
            const pnlPct = pos.pnl_pct === null ? null : pos.pnl_pct * 100;
            const pnlSign = pnlPct === null ? "neutral" : signClass(pnlPct);
            const weightPct = pos.weight_pct === null ? null : pos.weight_pct * 100;
            const distPct = pos.stop_distance_pct === null ? null : pos.stop_distance_pct * 100;
            return (
              <tr key={`${pos.market}:${pos.symbol}`}>
                <td>
                  <span className="detail-table__name">{pos.name}</span>
                  <span className="detail-table__code">{pos.symbol}</span>
                  <span className={`mkt mkt--${pos.market.toLowerCase()}`}>{pos.market}</span>
                  {pos.stale && <span className="badge badge--stale">지연</span>}
                </td>
                <td className="ta-r num">{pos.quantity.toLocaleString("ko-KR")}</td>
                <td className="ta-r num">{formatPrice(pos.market, pos.avg_price)}</td>
                <td className="ta-r num">
                  {pos.current_price === null ? "—" : formatPrice(pos.market, pos.current_price)}
                </td>
                <td className="ta-r num">
                  {pos.eval_value === null ? "—" : formatPrice(pos.market, pos.eval_value)}
                </td>
                <td className={`ta-r num strong ${pnlSign}`}>
                  {pnlPct === null ? "—" : signedPct(pnlPct)}
                </td>
                <td className="ta-r num muted">{holdingDays(pos.opened_date)}일</td>
                <td className="ta-r num">{weightPct === null ? "—" : `${weightPct.toFixed(1)}%`}</td>
                <td className="muted">{pos.entry_trigger || "—"}</td>
                <td className="ta-r num">
                  {pos.current_red_score === null ? "—" : pos.current_red_score}
                </td>
                <td className="ta-r num">
                  {pos.stop_px === null ? "—" : formatPrice(pos.market, pos.stop_px)}
                </td>
                <td className="ta-r num">
                  {pos.trail_px === null ? "—" : formatPrice(pos.market, pos.trail_px)}
                </td>
                <td className="ta-r num">{distPct === null ? "—" : `${distPct.toFixed(1)}%`}</td>
                {/* potential_loss는 원화 환산 값 — 시장과 무관하게 항상 ₩로 표기(formatPrice 아님). */}
                <td className="ta-r num">
                  {pos.potential_loss === null ? "—" : formatKrw(pos.potential_loss)}
                </td>
                <td>
                  {pos.pending_sell ? (
                    <span className="chip chip--down">대기중</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="muted">{pos.as_of === null ? "—" : shortDate(pos.as_of)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default PositionsTable;
