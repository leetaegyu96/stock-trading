import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ScanStatusStrip } from "./ScanStatusStrip";

const TS_EPOCH = 1_753_101_780_000; // 임의 절대 시각(ms)
const KR = {
  market: "KR",
  ts: "2026-07-21T13:43:00",
  tz: "KST",
  ts_epoch_ms: TS_EPOCH,
  universe_size: 60,
  evaluated: 58,
  failed: 2,
  gate_pass: 3,
  buys: 1,
  sells: 0,
  scan_minutes: 10,
};

describe("ScanStatusStrip", () => {
  it("renders market clock, tz label and relative time", () => {
    const html = renderToStaticMarkup(
      <ScanStatusStrip initialStatuses={[KR]} nowMs={TS_EPOCH + 3 * 60_000} />
    );
    expect(html).toContain("장중 스캔");
    expect(html).toContain("KR");
    expect(html).toContain("13:43");     // 시장 벽시계
    expect(html).toContain("KST");       // tz 라벨
    expect(html).toContain("3분 전");     // 상대 시간
    expect(html).toContain("58");        // 평가 종목 수
    expect(html).toContain("게이트");
    expect(html).toContain("매수 1");
    expect(html).toContain("다음");
  });

  it("shows '방금 전' right after a scan", () => {
    const html = renderToStaticMarkup(
      <ScanStatusStrip initialStatuses={[KR]} nowMs={TS_EPOCH + 5_000} />
    );
    expect(html).toContain("방금 전");
  });

  it("shows a waiting message when there is no scan yet", () => {
    const html = renderToStaticMarkup(<ScanStatusStrip initialStatuses={[]} />);
    expect(html).toContain("장중 스캔");
    expect(html).toContain("대기");
  });
});
