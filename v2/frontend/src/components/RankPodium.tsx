// 상위 3위 시상대. 1위가 가운데·가장 높고, 금/은/동 색조로 등수를 한눈에 읽게 한다.
//
// 절제 규칙: 등수 숫자나 순위 변동에 애니메이션을 넣지 않는다. 높이와 색조만으로
// 서열을 말하고, 나머지는 평소 카드와 같은 톤을 유지한다.
import {
  changeArrow,
  formatMoney,
  formatSignedMoney,
  kindShort,
  signClass,
  signedPct,
} from "./format";
import { medalOf, podiumSlotOrder } from "./ranking";
import type { RankingRow } from "../types";

export interface RankPodiumProps {
  /** 1~3위. 참가자가 적으면 있는 만큼만 넘긴다. */
  rows: RankingRow[];
}

function PodiumCard({ row }: { row: RankingRow }) {
  const medal = medalOf(row.rank) ?? "bronze";
  const cls = [
    "podium__slot",
    `podium__slot--${medal}`,
    row.is_me ? "podium__slot--me" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <li className={cls} style={{ order: podiumSlotOrder(row.rank) }}>
      <div className="podium__card">
        <div className="podium__top">
          <span className="podium__medal num">{row.rank}위</span>
          {row.is_me && <span className="chip chip--me">나</span>}
        </div>

        <div className="podium__name">{row.nickname}</div>
        <div className="podium__tags">
          <span className={`kindtag kindtag--${row.kind.toLowerCase()}`}>
            {kindShort(row.kind)}
          </span>
          <span className="muted small">{row.position_count}종목</span>
          {row.stale && <span className="stale-badge">시세 지연</span>}
        </div>

        <div className={`podium__pct num ${signClass(row.daily_return_pct)}`}>
          <span aria-hidden="true">{changeArrow(row.daily_return_pct)}</span>{" "}
          {signedPct(row.daily_return_pct)}
        </div>
        <div className="podium__sub num">
          오늘 {formatSignedMoney(row.daily_pnl, row.currency)}
        </div>

        <dl className="podium__facts">
          <div>
            <dt>누적</dt>
            <dd className={`num ${signClass(row.total_return_pct)}`}>
              {signedPct(row.total_return_pct)}
            </dd>
          </div>
          <div>
            <dt>총자산</dt>
            <dd className="num">{formatMoney(row.total_asset, row.currency)}</dd>
          </div>
        </dl>
      </div>
      <div className="podium__pillar" aria-hidden="true" />
    </li>
  );
}

export function RankPodium({ rows }: RankPodiumProps) {
  if (rows.length === 0) return null;
  // list-style:none 을 준 목록은 일부 브라우저에서 목록 의미를 잃는다 — role 을 못 박는다.
  return (
    <ol className="podium" role="list" aria-label="상위 3명">
      {rows.map((row) => (
        <PodiumCard key={`${row.account_id}-${row.kind}`} row={row} />
      ))}
    </ol>
  );
}

export default RankPodium;
