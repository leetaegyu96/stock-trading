// 상단 내비. 계좌(캐릭터)를 고른 뒤에만 종목/보유/내역으로 들어갈 수 있으므로
// 링크는 선택된 계좌 id 를 품는다.
import { NavLink } from "react-router-dom";
import type { AccountSummary, Me } from "../types";
import { kindLabel } from "./format";

export interface NavProps {
  me: Me | null;
  accounts: AccountSummary[];
  activeAccountId: number | null;
  onLogout: () => void;
}

export function Nav({ me, accounts, activeAccountId, onLogout }: NavProps) {
  const active = accounts.find((a) => a.id === activeAccountId) ?? null;
  const cls = ({ isActive }: { isActive: boolean }) =>
    `nav__link${isActive ? " nav__link--on" : ""}`;

  return (
    <nav className="nav">
      <NavLink to="/" className="nav__brand" style={{ textDecoration: "none", color: "inherit" }}>
        모의투자
      </NavLink>
      <NavLink to="/" className={cls} end>
        홈
      </NavLink>
      {active && (
        <>
          <NavLink to={`/accounts/${active.id}/stocks`} className={cls}>
            종목 찾기
          </NavLink>
          <NavLink to={`/accounts/${active.id}/holdings`} className={cls}>
            내 주식
          </NavLink>
          <NavLink to={`/accounts/${active.id}/trades`} className={cls}>
            거래 내역
          </NavLink>
        </>
      )}
      <span className="nav__spacer" />
      {active && <span className="nav__who">{kindLabel(active.kind)}</span>}
      {me && <span className="nav__who">{me.nickname}님</span>}
      <button type="button" className="btn btn--ghost" onClick={onLogout}>
        로그아웃
      </button>
    </nav>
  );
}

export default Nav;
