import { useEffect } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { setUnauthorizedHandler } from "./api";
import { Nav } from "./components/Nav";
import { Explore } from "./pages/Explore";
import { Holdings } from "./pages/Holdings";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { Ranking } from "./pages/Ranking";
import { StockDetail } from "./pages/StockDetail";
import { Trades } from "./pages/Trades";
import { SessionProvider, useSession } from "./session";
import "./components/theme.css";
import "./components/app.css";

// 서브패스 배포(VITE_BASE_PATH)시 라우터도 그 프리픽스를 알아야 매칭된다.
const ROUTER_BASENAME =
  import.meta.env.BASE_URL === "/" ? undefined : import.meta.env.BASE_URL.replace(/\/$/, "");

/** URL 에서 현재 보고 있는 캐릭터 id 를 뽑는다(내비 하이라이트·링크용). */
function useActiveAccountId(): number | null {
  const { pathname } = useLocation();
  const m = pathname.match(/\/accounts\/(\d+)/);
  return m ? Number(m[1]) : null;
}

/** 로그인한 사용자만 통과. 세션 확인이 끝나기 전에는 화면을 비워 깜빡임을 막는다. */
function Shell() {
  const { me, accounts, loading, logout } = useSession();
  const navigate = useNavigate();
  const activeAccountId = useActiveAccountId();

  // 어떤 화면에서든 401 이 나면 로그인 화면으로 보낸다(SPEC §3 세션 만료).
  useEffect(() => {
    setUnauthorizedHandler(() => navigate("/login", { replace: true }));
    return () => setUnauthorizedHandler(null);
  }, [navigate]);

  if (loading) return <div className="page-state">불러오는 중…</div>;
  if (!me) return <Navigate to="/login" replace />;

  return (
    <div className="shell">
      <Nav
        me={me}
        accounts={accounts}
        activeAccountId={activeAccountId}
        onLogout={async () => {
          await logout();
          navigate("/login", { replace: true });
        }}
      />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/ranking" element={<Ranking />} />
        <Route path="/accounts/:accountId/stocks" element={<Explore />} />
        <Route path="/accounts/:accountId/stocks/:symbol" element={<StockDetail />} />
        <Route path="/accounts/:accountId/holdings" element={<Holdings />} />
        <Route path="/accounts/:accountId/trades" element={<Trades />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}

export function App() {
  return (
    <BrowserRouter basename={ROUTER_BASENAME}>
      <SessionProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/*" element={<Shell />} />
        </Routes>
      </SessionProvider>
    </BrowserRouter>
  );
}

export default App;
