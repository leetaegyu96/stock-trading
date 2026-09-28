// 랭킹 화면의 순수 계산부. 화면(JSX)과 분리해 두면 막대 길이·시상대 배치 같은
// "틀리면 눈으로 알아채기 어려운" 규칙을 테스트로 고정할 수 있다.
import type { RankingRow } from "../types";

/** 시상대(1~3위)에 올리는 인원 수. */
export const PODIUM_SIZE = 3;

/** 메달 색조. 1·2·3위 외에는 없다. */
export type Medal = "gold" | "silver" | "bronze";

export function medalOf(rank: number): Medal | null {
  if (rank === 1) return "gold";
  if (rank === 2) return "silver";
  if (rank === 3) return "bronze";
  return null;
}

/**
 * 시상대에서 **보이는 자리**(CSS order). 1위를 가운데, 2위를 왼쪽, 3위를 오른쪽에 둔다.
 *
 * DOM 순서는 1·2·3위 그대로 두고 배치만 CSS 로 바꾼다 — 스크린리더는 등수 순으로
 * 읽고, 눈으로는 1위가 가운데 서 있는 시상대로 보인다.
 */
export function podiumSlotOrder(rank: number): number {
  if (rank === 1) return 2;
  if (rank === 2) return 1;
  return rank;
}

/** 막대 정규화 기준 — 지금 보이는 행들의 일간 수익률 절대값 중 최대. */
export function maxAbsDailyReturn(rows: RankingRow[]): number {
  return rows.reduce((max, r) => Math.max(max, Math.abs(r.daily_return_pct)), 0);
}

export interface BarGeometry {
  /** 막대 왼쪽 끝 위치(트랙 폭의 %) */
  leftPct: number;
  /** 막대 폭(트랙 폭의 %) */
  widthPct: number;
  /** 색·기호 축 — 상승=up(빨강), 하락=down(파랑) */
  sign: "up" | "down" | "neutral";
}

/** 0 이 정확히 가운데. 양수는 오른쪽, 음수는 왼쪽으로 자란다. */
const CENTER_PCT = 50;
/** 0 이 아닌 값은 아무리 작아도 보이게 하는 최소 폭. */
const MIN_VISIBLE_PCT = 0.9;

/**
 * 일간 수익률 → 발산형(diverging) 막대 좌표.
 * `maxAbs` 로 정규화하므로 같은 표 안의 막대끼리는 길이를 그대로 비교할 수 있다.
 */
export function dailyBarGeometry(pct: number, maxAbs: number): BarGeometry {
  const sign = pct > 0 ? "up" : pct < 0 ? "down" : "neutral";
  if (!Number.isFinite(pct) || pct === 0 || maxAbs <= 0) {
    return { leftPct: CENTER_PCT, widthPct: 0, sign };
  }
  const ratio = Math.min(Math.abs(pct) / maxAbs, 1);
  const widthPct = Math.max(ratio * CENTER_PCT, MIN_VISIBLE_PCT);
  return {
    leftPct: pct > 0 ? CENTER_PCT : CENTER_PCT - widthPct,
    widthPct,
    sign,
  };
}

/** 내 계정 행들(캐릭터가 2개라 '전체' 탭에서는 둘 다 나올 수 있다). */
export function myRows(rows: RankingRow[]): RankingRow[] {
  return rows.filter((r) => r.is_me);
}

/** 시상대에 못 올라간 내 행 — 표 아래 '내 순위'로 한 번 더 보여줄 대상. */
export function myRowsBelowPodium(rows: RankingRow[]): RankingRow[] {
  return myRows(rows).filter((r) => r.rank > PODIUM_SIZE);
}
