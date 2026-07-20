// 오늘의 매수후보 테이블(의사결정판, 감사 Phase B): 청/적신호 점수·매수게이트·상태·
// 차단 사유. block_reason은 백엔드가 확정한 표시값을 그대로 렌더한다(프론트에서
// 재계산/재해석하지 않음).
import type { CandidateOut } from "../types";

export interface CandidatesTableProps {
  candidates: CandidateOut[];
  className?: string;
}

export function CandidatesTable({ candidates, className }: CandidatesTableProps) {
  if (candidates.length === 0) {
    return (
      <div className={className}>
        <div className="detail-panel__state">오늘의 후보가 없습니다.</div>
      </div>
    );
  }

  return (
    <div className={className} style={{ overflowX: "auto" }}>
      <table className="detail-table">
        <thead>
          <tr>
            <th>종목</th>
            <th className="ta-r">청신호</th>
            <th className="ta-r">적신호</th>
            <th>매수게이트</th>
            <th>상태</th>
            <th>차단 사유</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => {
            const reserved = c.status === "예약";
            return (
              <tr key={c.symbol}>
                <td>
                  <span className="detail-table__name">{c.name}</span>
                  <span className="detail-table__code">{c.symbol}</span>
                </td>
                <td className="ta-r num">{c.green_score}</td>
                <td className="ta-r num">{c.red_score}</td>
                <td>
                  <span className={`chip chip--${c.buy_gate ? "up" : "neutral"}`}>
                    {c.buy_gate ? "통과" : "미충족"}
                  </span>
                </td>
                <td>
                  <span className={`chip chip--${reserved ? "up" : "neutral"}`}>{c.status}</span>
                </td>
                <td className="muted">{c.block_reason || "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default CandidatesTable;
