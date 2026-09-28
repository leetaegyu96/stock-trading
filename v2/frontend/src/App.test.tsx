// 앱 전체 스모크 테스트. 목 API 를 끼운 채 실제 라우팅·세션·화면 전환이 도는지 본다.
// 개별 컴포넌트 테스트가 잡지 못하는 배선 실수(잘못된 경로, 컨텍스트 누락)를 잡는 그물이다.
import { beforeAll, beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { installMockApi, resetMockState } from "./mocks/server";

beforeAll(() => {
  installMockApi();
});

beforeEach(() => {
  resetMockState();
  window.history.pushState({}, "", "/");
});

describe("앱 스모크", () => {
  it("홈에 캐릭터 2장이 뜬다", async () => {
    render(<App />);
    expect(await screen.findByText("국내 주식")).toBeDefined();
    expect(screen.getByText("해외 주식")).toBeDefined();
  });

  it("캐릭터를 누르면 종목 목록으로 간다", async () => {
    render(<App />);
    fireEvent.click(await screen.findByText("국내 주식"));
    expect(await screen.findByRole("heading", { name: /종목 찾기/ })).toBeDefined();
    expect(await screen.findByText("삼성전자")).toBeDefined();
  });

  it("종목 목록에 추천·점수 표시가 없다(SPEC §4.2)", async () => {
    window.history.pushState({}, "", "/accounts/1/stocks");
    const { container } = render(<App />);
    await screen.findByText("삼성전자");
    expect(container.textContent).not.toMatch(/점수|청신호|적신호/);
  });

  it("보유 화면에 매도벽 게이지가 그려진다", async () => {
    window.history.pushState({}, "", "/accounts/1/holdings");
    render(<App />);
    await screen.findByText("삼성전자");
    await waitFor(() => expect(screen.getAllByTestId("wall-now").length).toBeGreaterThan(0));
  });

  it("보유가 없는 해외 캐릭터는 다음 행동을 안내한다(빈 상태)", async () => {
    window.history.pushState({}, "", "/accounts/2/holdings");
    render(<App />);
    expect(await screen.findByText("아직 가진 주식이 없습니다")).toBeDefined();
    expect(screen.getByRole("button", { name: "종목 찾으러 가기" })).toBeDefined();
  });

  it("내비에서 랭킹으로 갈 수 있다", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("link", { name: "랭킹" }));
    expect(await screen.findByRole("heading", { name: "랭킹" })).toBeDefined();
    expect(await screen.findByText("불꽃개미")).toBeDefined();
  });

  it("거래 내역에서 자동매도는 발동 근거를 함께 보여준다", async () => {
    window.history.pushState({}, "", "/accounts/1/trades");
    const { container } = render(<App />);
    await screen.findByText("자동으로 팔린 것");
    await waitFor(() => expect(container.textContent).toContain("정해둔"));
    expect(container.textContent).toContain("에 닿아서 팔렸고");
  });
});
