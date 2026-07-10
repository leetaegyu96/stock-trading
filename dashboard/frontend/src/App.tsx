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

function App() {
  return (
    <BrowserRouter>
      <AppShellBar />
      <Routes>
        <Route path="/" element={<Main />} />
        <Route path="/character/:name" element={<Detail />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
