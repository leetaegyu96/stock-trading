import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ScanStatusStrip } from "./ScanStatusStrip";

const KR = {
  market: "KR",
  ts: "2026-07-21T13:43:00",
  universe_size: 60,
  evaluated: 58,
  failed: 2,
  gate_pass: 3,
  buys: 1,
  sells: 0,
  scan_minutes: 10,
};

describe("ScanStatusStrip", () => {
  it("renders the scan heartbeat for a market", () => {
    const html = renderToStaticMarkup(<ScanStatusStrip initialStatuses={[KR]} />);
    expect(html).toContain("장중 스캔");
    expect(html).toContain("KR");
    expect(html).toContain("13:43");     // 시장 벽시계(스캔 시각)
    expect(html).toContain("58");        // 평가 성공 종목 수
    expect(html).toContain("게이트");     // 게이트 통과 라벨
    expect(html).toContain("매수 1");
    expect(html).toContain("다음");       // 다음 스캔 주기 안내
  });

  it("shows a waiting message when there is no scan yet", () => {
    const html = renderToStaticMarkup(<ScanStatusStrip initialStatuses={[]} />);
    expect(html).toContain("장중 스캔");
    expect(html).toContain("대기");
  });
});
