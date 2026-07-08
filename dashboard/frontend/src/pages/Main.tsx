// 메인 페이지 (설계 스펙 §6 "메인"): 캐릭터 카드 3개 + 실시간 갱신.
// 마운트 시 getCharacters()로 초기 스냅샷을 그리고, 이후 useCardsSocket()이
// 밀어주는 `cards` 메시지로 화면을 계속 갱신한다(이름 기준 병합).
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getCharacters, ApiError } from "../api";
import { useCardsSocket } from "../ws";
import { CharacterCard } from "../components/CharacterCard";
import type { CardSummary } from "../types";
import "../components/theme.css";

function formatKrw(value: number): string {
  return `₩${Math.round(value).toLocaleString("ko-KR")}`;
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString("ko-KR", { hour12: false });
}

export function Main() {
  const navigate = useNavigate();
  const [cards, setCards] = useState<CardSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const liveCards = useCardsSocket();

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

  // 실시간 갱신: 서버는 매번 전체 카드 스냅샷(이름 전체)을 보내므로 그대로 교체한다.
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
    <div className="main-page">
      <header className="main-page__topbar">
        <h1 className="main-page__title">simcore dashboard</h1>
        <div className="main-page__summary">
          <span className="main-page__summary-item">
            전체 합계 <strong>{formatKrw(totalAssetKrw)}</strong>
          </span>
          <span className="main-page__summary-item main-page__summary-item--muted">
            마지막 갱신 {lastUpdated ? formatTime(lastUpdated) : "—"}
          </span>
        </div>
      </header>

      {error && cards === null && (
        <div className="main-page__state main-page__state--error">
          데이터를 불러오지 못했습니다: {error}
        </div>
      )}

      {cards === null && !error && (
        <div className="main-page__state">불러오는 중…</div>
      )}

      {cards !== null && cards.length === 0 && (
        <div className="main-page__state">아직 데이터 없음</div>
      )}

      {cards !== null && cards.length > 0 && (
        <div className="main-page__grid">
          {cards.map((card) => (
            <CharacterCard key={card.name} summary={card} onClick={handleCardClick} />
          ))}
        </div>
      )}
    </div>
  );
}

export default Main;
