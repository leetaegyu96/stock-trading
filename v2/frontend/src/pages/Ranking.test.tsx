// 랭킹 화면 테스트. 목 API 를 끼운 채 "등수가 실제로 읽히는가"를 확인한다.
import { beforeAll, beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Ranking } from "./Ranking";
import { installMockApi, resetMockState } from "../mocks/server";

beforeAll(() => {
  installMockApi();
});

beforeEach(() => {
  resetMockState();
});

/** 지정한 이름이 들어 있는 표 행(tr)을 찾는다. */
function rowOf(name: string): HTMLElement {
  const cell = screen.getAllByText(name)[0];
  const tr = cell.closest("tr");
  if (!tr) throw new Error(`${name} 의 표 행을 찾지 못했습니다.`);
  return tr;
}

describe("랭킹 화면", () => {
  it("상위 3위가 시상대에 뜨고, 1위가 맨 앞이다", async () => {
    render(<Ranking />);
    const podium = await screen.findByRole("list", { name: "상위 3명" });
    const slots = within(podium).getAllByRole("listitem");
    expect(slots).toHaveLength(3);
    // DOM 순서는 등수 순(스크린리더용) — 1위가 먼저 읽힌다.
    expect(within(slots[0]).getByText("1위")).toBeDefined();
    expect(within(slots[0]).getByText("불꽃개미")).toBeDefined();
    expect(within(slots[2]).getByText("3위")).toBeDefined();
  });

  it("4위부터는 표로 이어지고, 시상대 인원은 표에 없다", async () => {
    render(<Ranking />);
    await screen.findByText("불꽃개미");
    const table = screen.getByRole("table");
    expect(within(table).queryByText("불꽃개미")).toBeNull();
    expect(within(table).getByText("점심시간매수")).toBeDefined();
  });

  it("금액에는 통화가 늘 함께 붙고, 순위 기준이 비율임을 화면이 설명한다", async () => {
    const { container } = render(<Ranking />);
    await screen.findByText("불꽃개미");
    expect(container.textContent).toContain("원");
    expect(container.textContent).toContain("$");
    expect(container.textContent).toMatch(/금액은 서로 비교할 수 없어서/);
  });

  it("일간 수익률 막대는 0 을 가운데 두고 양·음으로 갈라진다", async () => {
    render(<Ranking />);
    await screen.findByText("존버중");

    // 표 안에서 절대값이 가장 큰 -4.12% 는 왼쪽 절반을 꽉 채운다.
    const worst = within(rowOf("존버중")).getByTestId("daily-bar-fill");
    expect(worst.style.left).toBe("0%");
    expect(worst.style.width).toBe("50%");
    expect(within(rowOf("존버중")).getByTestId("daily-bar").dataset.sign).toBe("down");

    // 양수 행은 가운데(50%)에서 오른쪽으로 자란다.
    const good = within(rowOf("밤에깨는사람")).getByTestId("daily-bar-fill");
    expect(good.style.left).toBe("50%");
    expect(parseFloat(good.style.width)).toBeGreaterThan(0);
    expect(within(rowOf("밤에깨는사람")).getByTestId("daily-bar").dataset.sign).toBe("up");
  });

  it("색 없이도 방향을 알 수 있게 부호·화살표를 함께 쓴다", async () => {
    render(<Ranking />);
    await screen.findByText("존버중");
    const tr = rowOf("존버중");
    expect(tr.textContent).toContain("▼");
    expect(tr.textContent).toContain("-4.12%");
    expect(within(rowOf("밤에깨는사람")).getByText(/\+3\.32%/)).toBeDefined();
  });

  it("내 행은 강조되고, 시상대 밖이면 '내 순위'로 한 번 더 나온다", async () => {
    render(<Ranking />);
    await screen.findByText("불꽃개미");

    const mine = document.querySelectorAll(".rank-row--me");
    expect(mine.length).toBeGreaterThan(0);
    expect(screen.getAllByText("나").length).toBeGreaterThan(0);
    expect(screen.getByText(/내 순위/)).toBeDefined();

    // 내 캐릭터 2개(국내·해외)가 모두 '내 순위'에 실린다 — 표 본문 + 고정 행 = 2번씩.
    expect(screen.getAllByText("초보투자자")).toHaveLength(4);
  });

  it("국내 탭은 국내 캐릭터만 남긴다", async () => {
    render(<Ranking />);
    await screen.findByText("달러사랑");

    fireEvent.click(screen.getByRole("button", { name: "국내" }));
    await waitFor(() => expect(screen.queryByText("달러사랑")).toBeNull());
    expect(screen.getByText("불꽃개미")).toBeDefined();
    expect(screen.getByRole("button", { name: "국내" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("해외 탭에서 내 캐릭터가 3위면 시상대 위에서 강조된다", async () => {
    render(<Ranking />);
    await screen.findByText("불꽃개미");

    fireEvent.click(screen.getByRole("button", { name: "해외" }));
    await waitFor(() => expect(screen.queryByText("불꽃개미")).toBeNull());

    const podium = await screen.findByRole("list", { name: "상위 3명" });
    const slots = within(podium).getAllByRole("listitem");
    expect(slots[2].className).toContain("podium__slot--me");
    expect(within(slots[2]).getByText("나")).toBeDefined();
    // 시상대에 올랐으니 '내 순위' 고정 행은 접는다.
    expect(screen.queryByText(/내 순위/)).toBeNull();
  });

  it("시세가 밀린 참가자는 조용히 '시세 지연'으로만 알린다", async () => {
    render(<Ranking />);
    await screen.findByText("존버중");
    expect(within(rowOf("존버중")).getByText("시세 지연")).toBeDefined();
    // 요란한 경고가 아니라 뱃지 하나 — 다른 행에는 붙지 않는다.
    expect(screen.getAllByText("시세 지연")).toHaveLength(1);
  });

  it("표에 제목 행과 등수 행 머리글이 있다(접근성)", async () => {
    render(<Ranking />);
    await screen.findByText("존버중");
    expect(screen.getByRole("columnheader", { name: "오늘 수익률" })).toBeDefined();
    const rankCell = within(rowOf("존버중")).getAllByRole("rowheader")[0];
    expect(rankCell.textContent).toContain("위");
  });

  it("참가자가 없으면 다음을 안내한다(빈 상태)", async () => {
    const real = globalThis.fetch;
    globalThis.fetch = async () =>
      new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
    try {
      render(<Ranking />);
      expect(await screen.findByText("아직 순위에 오를 참가자가 없습니다")).toBeDefined();
      expect(screen.queryByRole("table")).toBeNull();
    } finally {
      globalThis.fetch = real;
    }
  });

  it("불러오기에 실패하면 이유와 '다시 시도'를 준다", async () => {
    const real = globalThis.fetch;
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: "랭킹 준비 중입니다." } }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    try {
      render(<Ranking />);
      expect(await screen.findByText(/랭킹 준비 중입니다./)).toBeDefined();
      globalThis.fetch = real;
      fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
      expect(await screen.findByText("불꽃개미")).toBeDefined();
    } finally {
      globalThis.fetch = real;
    }
  });
});
