// 메인 페이지의 순수 표시 레이아웃(의사결정판, 감사 Phase B): 오늘의 행동 →
// 포트폴리오 위험 스트립 → 캐릭터 카드 → 내 캐릭터/오늘의 시장/최근 거래(하단).
// 데이터 패칭은 pages/Main.tsx가 담당하고, 이 컴포넌트는 props만 받아 렌더링한다 —
// 그래야 fetch 없이도(SSR 정적 렌더) 섹션 순서를 테스트할 수 있다.
import type { CardSummary, Dashboard } from "../types";
import { CharacterCard } from "./CharacterCard";
import { TodayActions } from "./TodayActions";
import { RiskStrip } from "./RiskStrip";
import { HoldingsPreview } from "./HoldingsPreview";
import { MarketMovers } from "./MarketMovers";
import { RecentTrades } from "./RecentTrades";

export interface DecisionBoardProps {
  cards: CardSummary[];
  board: Dashboard | null;
  boardError: string | null;
  onCardClick?: (name: string) => void;
}

export function DecisionBoard({ cards, board, boardError, onCardClick }: DecisionBoardProps) {
  const loadingOrError = <p className="board__empty">{boardError ?? "불러오는 중…"}</p>;

  return (
    <div className="detail-sections">
      <section className="detail-panel" data-section="today-actions">
        <h2 className="detail-panel__title">오늘의 행동</h2>
        {board ? <TodayActions actions={board.today_actions} /> : loadingOrError}
      </section>

      <section className="detail-panel" data-section="risk-strip">
        <h2 className="detail-panel__title">포트폴리오 위험</h2>
        {board ? <RiskStrip risk={board.risk} /> : loadingOrError}
      </section>

      <div className="card-grid" data-section="character-cards">
        {cards.map((card) => (
          <CharacterCard key={card.name} summary={card} onClick={onCardClick} />
        ))}
      </div>

      <section className="detail-panel" data-section="holdings-preview">
        <h2 className="detail-panel__title">내 캐릭터</h2>
        {board ? <HoldingsPreview characters={board.characters} /> : loadingOrError}
      </section>

      <section className="detail-panel" data-section="market-movers">
        <h2 className="detail-panel__title">오늘의 시장</h2>
        {board ? <MarketMovers movers={board.movers} /> : loadingOrError}
      </section>

      <section className="detail-panel" data-section="recent-trades">
        <h2 className="detail-panel__title">최근 거래</h2>
        {board ? <RecentTrades trades={board.recent_trades} /> : loadingOrError}
      </section>
    </div>
  );
}

export default DecisionBoard;
