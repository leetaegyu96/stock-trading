// 상세 페이지 보유종목 테이블: 종목·수량·평단·현재가·평가액·손익%·보유일.
// 상승(손익 양수)=빨강, 하락(음수)=파랑. 시세가 지연된 종목은 "지연" 배지 표시.
// 주의: PositionOut.pnl_pct는 백엔드 관례상 비율(ratio, 예: 0.05 = +5%)로 내려온다
// (CardSummary.twr/today_pnl_pct와 동일 관례) — 화면 표기 직전에 한 번만 *100 한다.
import type { PositionOut } from "../types";
import { formatKrw, holdingDays, signClass, signedPct } from "./format";

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
            <th>수량</th>
            <th>평단</th>
            <th>현재가</th>
            <th>평가액</th>
            <th>손익%</th>
            <th>보유일</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => {
            const pnlPct = pos.pnl_pct === null ? null : pos.pnl_pct * 100;
            const pnlSign = pnlPct === null ? "neutral" : signClass(pnlPct);
            return (
              <tr key={`${pos.market}:${pos.symbol}`}>
                <td>
                  <span className="detail-table__symbol">{pos.symbol}</span>
                  <span className="detail-table__market">{pos.market}</span>
                  {pos.stale && <span className="badge badge--stale">지연</span>}
                </td>
                <td>{pos.quantity.toLocaleString("ko-KR")}</td>
                <td>{formatKrw(pos.avg_price)}</td>
                <td>{pos.current_price === null ? "—" : formatKrw(pos.current_price)}</td>
                <td>{pos.eval_value === null ? "—" : formatKrw(pos.eval_value)}</td>
                <td className={pnlSign}>
                  {pnlPct === null ? "—" : signedPct(pnlPct)}
                </td>
                <td>{holdingDays(pos.opened_date)}일</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default PositionsTable;
