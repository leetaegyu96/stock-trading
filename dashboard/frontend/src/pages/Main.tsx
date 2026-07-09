// 메인 페이지: 캐릭터 카드 그리드 + 실시간 갱신 + 상단 요약(전체 자산·연결 상태).
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getCharacters, ApiError } from "../api";
import { useCardsSocket } from "../ws";
import { CharacterCard } from "../components/CharacterCard";
import { formatKrw } from "../components/format";
import type { CardSummary } from "../types";
import "../components/theme.css";

function formatTime(date: Date): string {
  return date.toLocaleTimeString("ko-KR", { hour12: false });
}

export function Main() {
  const navigate = useNavigate();
  const [cards, setCards] = useState<CardSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
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
        <div className="topbar__brand">
          <h1 className="topbar__title">simcore</h1>
          <span className="topbar__tag">모의투자</span>
        </div>
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
        <div className="card-grid">
          {cards.map((card) => (
            <CharacterCard key={card.name} summary={card} onClick={handleCardClick} />
          ))}
        </div>
      )}
    </div>
  );
}

export default Main;
