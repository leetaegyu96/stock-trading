// 포트폴리오 위험 스트립(의사결정판, 감사 Phase B): 캐릭터별 현금비중·총노출·
// 최대 보유 비중(종목 집중)·일 손익. "업종 집중"이 아니다 — 업종/실적일 데이터가
// 없으므로 해당 컬럼을 만들지 않는다.
import type { CharacterRiskOut } from "../types";
import { changeArrow, formatSignedKrw, signClass } from "./format";

export interface RiskStripProps {
  risk: CharacterRiskOut[];
}

function pct1(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}

export function RiskStrip({ risk }: RiskStripProps) {
  if (risk.length === 0) {
    return <p className="board__empty">위험 데이터가 없습니다.</p>;
  }

  return (
    <div className="risk-overview">
      {risk.map((r) => {
        const dailySign = signClass(r.daily_pnl_krw);
        return (
          <div key={r.character} className="risk-overview__item">
            <span className="risk-overview__char">{r.character}</span>
            <div className="risk-overview__metrics">
              <div className="risk-overview__metric">
                <span className="risk-overview__label">현금비중</span>
                <span className="risk-overview__value num">{pct1(r.cash_ratio)}</span>
              </div>
              <div className="risk-overview__metric">
                <span className="risk-overview__label">총노출</span>
                <span className="risk-overview__value num">{pct1(r.total_exposure_pct)}</span>
              </div>
              <div className="risk-overview__metric">
                <span className="risk-overview__label">최대 보유 비중(종목 집중)</span>
                <span className="risk-overview__value num">{pct1(r.max_position_weight_pct)}</span>
              </div>
              <div className="risk-overview__metric">
                <span className="risk-overview__label">일 손익</span>
                <span className={`risk-overview__value num ${dailySign}`}>
                  <span aria-hidden="true">{changeArrow(r.daily_pnl_krw)}</span>{" "}
                  {formatSignedKrw(r.daily_pnl_krw)}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default RiskStrip;
