// 캐릭터별 보유 요약 미리보기: 오늘 손익·보유종목수·베스트/워스트 종목.
import type { CharPortfolio, HoldingRank } from "../types";
import { formatPrice, signClass, signedPct } from "./format";

export interface HoldingsPreviewProps {
  characters: CharPortfolio[];
}

function RankItem({ label, rank }: { label: string; rank: HoldingRank | null }) {
  if (!rank) {
    return (
      <div className="holdings-preview__rank">
        <span className="holdings-preview__rank-label">{label}</span>
        <span className="holdings-preview__rank-name muted">—</span>
      </div>
    );
  }
  const pct = rank.pnl_pct * 100;
  return (
    <div className="holdings-preview__rank">
      <span className="holdings-preview__rank-label">{label}</span>
      <span className="holdings-preview__rank-name" title={rank.symbol}>
        {rank.name}
      </span>
      <span className="holdings-preview__rank-price">
        {rank.close === null || rank.close === undefined ? "—" : formatPrice(rank.market, rank.close)}
      </span>
      <span className={`num holdings-preview__rank-pct ${signClass(pct)}`}>{signedPct(pct)}</span>
    </div>
  );
}

export function HoldingsPreview({ characters }: HoldingsPreviewProps) {
  if (characters.length === 0) {
    return <p className="board__empty">아직 보유 데이터가 없습니다.</p>;
  }

  return (
    <ul className="holdings-preview">
      {characters.map((c) => {
        const todayPct = c.today_pnl_pct * 100;
        return (
          <li key={c.name} className="holdings-preview__item">
            <div className="holdings-preview__head">
              <span className="holdings-preview__name">{c.name}</span>
              <span className={`chip chip--${signClass(todayPct)}`}>
                오늘 {signedPct(todayPct)}
              </span>
              <span className="holdings-preview__count">
                보유 <span className="num">{c.n_positions}</span>종목
              </span>
            </div>
            <div className="holdings-preview__ranks">
              <RankItem label="베스트 종목" rank={c.best} />
              <RankItem label="워스트 종목" rank={c.worst} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export default HoldingsPreview;
