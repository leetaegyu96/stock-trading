// 보유종목 테이블: 숫자 우측 정렬 + 등폭 숫자, 시장 통화 인지 가격 표기(₩/$),
// 손익 상승=빨강/하락=파랑, 시세 지연 시 "지연" 배지.
import type { PositionOut } from "../types";
import { formatPrice, holdingDays, signClass, signedPct } from "./format";

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
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => {
            const pnlPct = pos.pnl_pct === null ? null : pos.pnl_pct * 100;
            const pnlSign = pnlPct === null ? "neutral" : signClass(pnlPct);
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
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default PositionsTable;
