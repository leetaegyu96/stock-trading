// 세션 컨텍스트: 로그인한 사용자와 캐릭터 2개를 앱 전체가 공유한다.
//
// 인증이 httpOnly 쿠키라 프론트에는 토큰이 없다 — "로그인했는가"는 오직
// `GET /api/auth/me` 가 200 을 주는지로 판단한다(SPEC §3).
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import * as api from "./api";
import type { AccountSummary, Me } from "./types";

export interface SessionValue {
  me: Me | null;
  accounts: AccountSummary[];
  /** 첫 /me 확인이 끝나기 전 — 이 동안은 로그인 화면으로 튕기지 않는다. */
  loading: boolean;
  /** 로그인 직후/주문 직후 등 계좌 숫자를 다시 읽어야 할 때 */
  refresh: () => Promise<void>;
  setMe: (me: Me | null) => void;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const user = await api.getMe();
      setMe(user);
      setAccounts(await api.getAccounts());
    } catch {
      // 401 이면 미로그인 — 오류로 떠들 필요 없이 로그인 화면으로 보낸다.
      setMe(null);
      setAccounts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setMe(null);
      setAccounts([]);
    }
  }, []);

  const value = useMemo<SessionValue>(
    () => ({ me, accounts, loading, refresh, setMe, logout }),
    [me, accounts, loading, refresh, logout]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession 은 SessionProvider 안에서만 쓸 수 있습니다.");
  return ctx;
}
