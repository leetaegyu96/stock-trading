// 메인 페이지: 오늘의 의사결정판. 오늘의 행동(대기주문·강제매도 경보) →
// 포트폴리오 위험 스트립 → 캐릭터 카드(실시간 갱신) → 내 캐릭터/오늘의 시장/
// 최근 거래(하단) 순서로 배치한다(감사 Phase B). 실제 레이아웃은 DecisionBoard가
// 담당하고, 이 페이지는 데이터 패칭/로딩·에러 상태만 관리한다.
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, getCharacters, getDashboard } from "../api";
import { useCardsSocket } from "../ws";
import { DecisionBoard } from "../components/DecisionBoard";
import { formatKrw } from "../components/format";
import type { CardSummary, Dashboard } from "../types";
import "../components/theme.css";
import "../components/detail.css";

function formatTime(date: Date): string {
  return date.toLocaleTimeString("ko-KR", { hour12: false });
}

export function Main() {
  const navigate = useNavigate();
  const [cards, setCards] = useState<CardSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [board, setBoard] = useState<Dashboard | null>(null);
  const [boardError, setBoardError] = useState<string | null>(null);
  const { cards: liveCards, connected } = useCardsSocket();

  // 초기 로드: REST로 첫 화면을 그린다.
  useEffect(() => {
    let cancelled = false;
    getCharacters()
      .then((data) => {
        if (cancelled) return;
        setCards(data);
        setLastUpdated(new Date());
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof ApiError ? err.message : "데이터를 불러오지 못했습니다.";
        setError(message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 현황판(시장 movers·캐릭터 요약·최근 체결)은 카드와 독립적으로 로드한다.
  // 실패해도 카드 화면은 그대로 유지하고, 현황판 영역에만 안내를 보여준다.
  useEffect(() => {
    let cancelled = false;
    getDashboard()
      .then((data) => {
        if (cancelled) return;
        setBoard(data);
        setBoardError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof ApiError ? err.message : "현황판을 불러오지 못했습니다.";
        setBoardError(message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 실시간 갱신: 서버는 전체 카드 스냅샷을 보내므로 그대로 교체.
  useEffect(() => {
    if (liveCards.length === 0) return;
    setCards(liveCards);
    setLastUpdated(new Date());
    setError(null);
  }, [liveCards]);

  const totalAssetKrw = useMemo(
    () => (cards ?? []).reduce((sum, c) => sum + c.total_asset_krw, 0),
    [cards]
  );

  const handleCardClick = (name: string) => {
    navigate(`/character/${encodeURIComponent(name)}`);
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar__stat">
          <span className="topbar__stat-label">전체 자산</span>
          <span className="topbar__stat-value num">{formatKrw(totalAssetKrw)}</span>
        </div>
        <span className="topbar__live">
          <span
            className={`topbar__live-dot${connected ? " topbar__live-dot--on" : ""}`}
            aria-hidden="true"
          />
          {connected ? "실시간" : "오프라인"}
          {lastUpdated && ` · ${formatTime(lastUpdated)}`}
        </span>
      </header>

      {error && cards === null && (
        <div className="page-state page-state--error">
          데이터를 불러오지 못했습니다: {error}
        </div>
      )}

      {cards === null && !error && <div className="page-state">불러오는 중…</div>}

      {cards !== null && cards.length === 0 && (
        <div className="page-state">아직 데이터가 없습니다.</div>
      )}

      {cards !== null && cards.length > 0 && (
        <DecisionBoard
          cards={cards}
          board={board}
          boardError={boardError}
          onCardClick={handleCardClick}
        />
      )}
    </div>
  );
}

export default Main;
