import { describe, expect, it } from "vitest";
import {
  dailyBarGeometry,
  maxAbsDailyReturn,
  medalOf,
  myRows,
  myRowsBelowPodium,
  podiumSlotOrder,
} from "./ranking";
import type { RankingRow } from "../types";

function row(over: Partial<RankingRow> = {}): RankingRow {
  return {
    rank: 1,
    account_id: 1,
    nickname: "참가자",
    kind: "KR",
    currency: "KRW",
    daily_return_pct: 0,
    daily_pnl: 0,
    total_return_pct: 0,
    total_asset: 100_000_000,
    position_count: 0,
    is_me: false,
    stale: false,
    ...over,
  };
}

describe("메달·시상대 배치", () => {
  it("1·2·3위에만 메달이 있다", () => {
    expect(medalOf(1)).toBe("gold");
    expect(medalOf(2)).toBe("silver");
    expect(medalOf(3)).toBe("bronze");
    expect(medalOf(4)).toBeNull();
  });

  it("1위가 가운데, 2위가 왼쪽, 3위가 오른쪽에 선다", () => {
    expect(podiumSlotOrder(2)).toBeLessThan(podiumSlotOrder(1));
    expect(podiumSlotOrder(1)).toBeLessThan(podiumSlotOrder(3));
  });
});

describe("일간 수익률 막대", () => {
  it("정규화 기준은 절대값 최대", () => {
    const rows = [row({ daily_return_pct: 2.1 }), row({ daily_return_pct: -5.4 })];
    expect(maxAbsDailyReturn(rows)).toBe(5.4);
    expect(maxAbsDailyReturn([])).toBe(0);
  });

  it("양수는 가운데에서 오른쪽으로 자란다", () => {
    const g = dailyBarGeometry(4, 8);
    expect(g.leftPct).toBe(50);
    expect(g.widthPct).toBe(25);
    expect(g.sign).toBe("up");
  });

  it("음수는 가운데에서 왼쪽으로 자란다", () => {
    const g = dailyBarGeometry(-4, 8);
    expect(g.leftPct).toBe(25);
    expect(g.widthPct).toBe(25);
    expect(g.sign).toBe("down");
    // 왼쪽 끝 + 폭 = 가운데(0 지점)에 정확히 닿아야 한다.
    expect(g.leftPct + g.widthPct).toBe(50);
  });

  it("절대값 최대인 행은 트랙의 절반을 꽉 채운다", () => {
    expect(dailyBarGeometry(-8, 8).widthPct).toBe(50);
    expect(dailyBarGeometry(8, 8).widthPct).toBe(50);
  });

  it("0 이면 막대가 없고, 0 이 아니면 아무리 작아도 보인다", () => {
    expect(dailyBarGeometry(0, 8).widthPct).toBe(0);
    expect(dailyBarGeometry(0, 8).sign).toBe("neutral");
    expect(dailyBarGeometry(0.0001, 8).widthPct).toBeGreaterThan(0);
  });

  it("기준이 0 이거나 값이 이상해도 깨지지 않는다", () => {
    expect(dailyBarGeometry(3, 0).widthPct).toBe(0);
    expect(dailyBarGeometry(Number.NaN, 8).widthPct).toBe(0);
  });
});

describe("내 순위 찾기", () => {
  const rows = [
    row({ rank: 1, account_id: 101 }),
    row({ rank: 2, account_id: 2, is_me: true, kind: "US", currency: "USD" }),
    row({ rank: 5, account_id: 1, is_me: true }),
  ];

  it("내 계정은 캐릭터 수만큼 나올 수 있다", () => {
    expect(myRows(rows)).toHaveLength(2);
  });

  it("시상대에 오른 내 행은 '내 순위'로 또 보여주지 않는다", () => {
    const below = myRowsBelowPodium(rows);
    expect(below.map((r) => r.rank)).toEqual([5]);
  });
});
