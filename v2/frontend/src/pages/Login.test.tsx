import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { Login } from "./Login";
import { SessionProvider } from "../session";

function show() {
  render(
    <BrowserRouter>
      <SessionProvider>
        <Login />
      </SessionProvider>
    </BrowserRouter>
  );
}

describe("로그인 / 회원가입 화면(SPEC §8.1 #1)", () => {
  it("한 화면에서 탭으로 전환한다", () => {
    show();
    expect(screen.getByRole("tab", { name: "로그인" })).toBeDefined();
    expect(screen.getByRole("tab", { name: "회원가입" })).toBeDefined();
  });

  it("가입 탭에서 캐릭터 2개와 각 1억원 지급을 안내한다", () => {
    show();
    fireEvent.click(screen.getByRole("tab", { name: "회원가입" }));
    const notice = screen.getByText(/가입하면/);
    expect(notice.textContent).toContain("캐릭터 2개(국내·해외)");
    expect(notice.textContent).toContain("각각 1억원");
  });

  it("이메일 형식이 아니면 왕복 없이 바로 알려준다", () => {
    show();
    fireEvent.change(screen.getByLabelText("이메일"), { target: { value: "not-an-email" } });
    fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "verylongpassword" } });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    expect(screen.getByText("이메일 형식이 아닙니다.")).toBeDefined();
  });

  it("비밀번호가 10자 미만이면 막는다(SPEC §3)", () => {
    show();
    fireEvent.change(screen.getByLabelText("이메일"), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: "로그인" }));
    expect(screen.getByText("비밀번호는 10자 이상이어야 합니다.")).toBeDefined();
  });

  it("가입 시 별명을 비우면 막는다", () => {
    show();
    fireEvent.click(screen.getByRole("tab", { name: "회원가입" }));
    fireEvent.change(screen.getByLabelText("이메일"), { target: { value: "a@b.com" } });
    fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "verylongpassword" } });
    fireEvent.click(screen.getByRole("button", { name: "가입하고 시작하기" }));
    expect(screen.getByText("어떻게 불러드릴지 별명을 적어주세요.")).toBeDefined();
  });
});
