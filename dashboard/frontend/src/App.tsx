import { useEffect, useMemo, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Main } from "./pages/Main";
import { Detail } from "./pages/Detail";
import { ModeBar } from "./components/ModeBar";
import { useCardsSocket } from "./ws";

/** 운영모드 바의 데이터 소스: 카드 스냅샷을 독립적으로 구독해 as-of/시장 목록을 뽑는다.
 * Main/Detail 각 페이지의 REST 로딩과는 무관하게, 이 바는 모든 화면에서 항상 보인다. */
function AppShellBar() {
  const { cards, connected } = useCardsSocket();
  const [asOf, setAsOf] = useState<Date | null>(null);

  // 새 스냅샷이 도착한 시점 = 데이터 최신성. WebSocket 연결 여부와는 별개 신호.
  useEffect(() => {
    if (cards.length > 0) setAsOf(new Date());
  }, [cards]);

  const markets = useMemo(
    () => Array.from(new Set(cards.flatMap((c) => c.markets))),
    [cards]
  );

  return (
    <div className="mode-bar-shell">
      <ModeBar connected={connected} asOf={asOf} markets={markets} />
    </div>
  );
}

// 서브패스 배포(VITE_BASE_PATH)시 라우터도 그 프리픽스를 알아야 매칭된다.
// api.ts/ws.ts 와 동일하게 Vite의 base 를 그대로 재사용 — 루트("/") 배포면 undefined
// 라 기존과 동일하게 동작.
const ROUTER_BASENAME =
  import.meta.env.BASE_URL === "/" ? undefined : import.meta.env.BASE_URL.replace(/\/$/, "");

function App() {
  return (
    <BrowserRouter basename={ROUTER_BASENAME}>
      <AppShellBar />
      <Routes>
        <Route path="/" element={<Main />} />
        <Route path="/character/:name" element={<Detail />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
