// 성과 → 아바타 표정 매핑. 순수 함수라 테스트가 쉬움 (Task 10 Step 1).
//
// 단위 규약: `moodFromPnl`은 **퍼센트(%) 단위**의 숫자를 받는다 (예: 1.2 는 +1.2%).
// 백엔드 `CardSummary.today_pnl_pct`는 **비율(ratio)** 로 내려온다 (예: 0.012 는 +1.2%).
// 따라서 카드 경계(CharacterCard)에서 `ratio * 100`으로 변환한 뒤 이 함수에 넘긴다.
// (변환 지점을 한 곳으로 고정해 단위 혼동을 방지)
export type Mood = "happy" | "smile" | "neutral" | "down";

/**
 * 오늘 등락(%, percent 단위)을 표정으로 매핑한다.
 * - `> 1.5` → happy (활짝)
 * - `> 0`   → smile (미소)
 * - `=== 0` → neutral (무표정)
 * - `< 0`   → down (시무룩)
 */
export function moodFromPnl(todayPct: number): Mood {
  if (todayPct > 1.5) return "happy";
  if (todayPct > 0) return "smile";
  if (todayPct === 0) return "neutral";
  return "down";
}
