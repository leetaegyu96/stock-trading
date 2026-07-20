import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { CandidatesTable } from "./CandidatesTable";
import type { CandidateOut } from "../types";

function makeCandidate(overrides: Partial<CandidateOut>): CandidateOut {
  return {
    symbol: "005930",
    name: "삼성전자",
    green_score: 3,
    red_score: 1,
    buy_gate: true,
    status: "예약",
    block_reason: "",
    as_of: "2026-07-20",
    ...overrides,
  };
}

describe("CandidatesTable", () => {
  it("shows an empty state when there are no candidates", () => {
    const html = renderToStaticMarkup(<CandidatesTable candidates={[]} />);
    expect(html).toContain("오늘의 후보가 없습니다.");
  });

  it("renders reserved candidates without a block reason", () => {
    const html = renderToStaticMarkup(
      <CandidatesTable candidates={[makeCandidate({ status: "예약", block_reason: "" })]} />
    );
    expect(html).toContain("예약");
    expect(html).toContain("삼성전자");
  });

  it("renders each documented block reason for blocked candidates", () => {
    const reasons = [
      "점수부족",
      "게이트미충족",
      "보유중",
      "쿨다운",
      "슬롯부족",
      "현금부족",
      "가격없음",
    ];
    for (const reason of reasons) {
      const html = renderToStaticMarkup(
        <CandidatesTable
          candidates={[
            makeCandidate({ symbol: "X", status: "차단", block_reason: reason, buy_gate: false }),
          ]}
        />
      );
      expect(html).toContain(reason);
      expect(html).toContain("차단");
    }
  });

  it("renders green/red scores as plain numbers", () => {
    const html = renderToStaticMarkup(
      <CandidatesTable candidates={[makeCandidate({ green_score: 4, red_score: 2 })]} />
    );
    expect(html).toContain(">4<");
    expect(html).toContain(">2<");
  });
});
