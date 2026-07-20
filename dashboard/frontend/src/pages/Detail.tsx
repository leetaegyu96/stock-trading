// 캐릭터 상세 페이지: 헤더(아바타·이름·입출금) → 성과지표 스트립 → 자산곡선 →
// 보유종목 → 거래내역. 카드 브로드캐스트에서 이 캐릭터 값이 바뀌면 조용히 재조회.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  getCandidates,
  getDetail,
  getEquity,
  getPositions,
  getTrades,
} from "../api";
import { useCardsSocket } from "../ws";
import { Avatar } from "../components/Avatar";
import { moodFromPnl } from "../components/mood";
import { EquityChart } from "../components/EquityChart";
import { CandidatesTable } from "../components/CandidatesTable";
import { PositionsTable } from "../components/PositionsTable";
import { TradesTable } from "../components/TradesTable";
import { MetricsPanel } from "../components/MetricsPanel";
import { FlowModal } from "../components/FlowModal";
import type { FlowMode } from "../components/FlowModal";
import type { CandidateOut, EquityPoint, Metrics, PositionOut, TradeOut } from "../types";
import "../components/theme.css";
import "../components/detail.css";

interface DetailData {
  metrics: Metrics;
  equity: EquityPoint[];
  positions: PositionOut[];
  trades: TradeOut[];
  candidates: CandidateOut[];
}

const TRADES_LIMIT = 100;

export function Detail() {
  const { name: rawName } = useParams<{ name: string }>();
  const name = rawName ?? "";

  const [data, setData] = useState<DetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [flowMode, setFlowMode] = useState<FlowMode | null>(null);
  const { cards: liveCards } = useCardsSocket();
  const positionsSignatureRef = useRef<string | null>(null);

  const load = useCallback((targetName: string, showSpinner: boolean) => {
    if (showSpinner) setLoading(true);
    return Promise.all([
      getDetail(targetName),
      getEquity(targetName),
      getPositions(targetName),
      getTrades(targetName, TRADES_LIMIT),
      getCandidates(targetName),
    ])
      .then(([metrics, equity, positions, trades, candidates]) => {
        setData({ metrics, equity, positions, trades, candidates });
        setError(null);
      })
      .catch((err: unknown) => {
        const message =
          err instanceof ApiError ? err.message : "데이터를 불러오지 못했습니다.";
        setError(message);
      })
      .finally(() => {
        if (showSpinner) setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!name) {
      setLoading(false);
      return;
    }
    setData(null);
    setError(null);
    positionsSignatureRef.current = null;
    void load(name, true);
  }, [name, load]);

  // 실시간: 카드 스냅샷에서 이 캐릭터의 포지션 관련 값이 바뀌면 스피너 없이 재조회.
  useEffect(() => {
    if (!name || liveCards.length === 0) return;
    const card = liveCards.find((c) => c.name === name);
    if (!card) return;
    const signature = `${card.n_positions}:${card.total_asset_krw}:${card.cash_krw}`;
    if (positionsSignatureRef.current === null) {
      positionsSignatureRef.current = signature;
      return;
    }
    if (positionsSignatureRef.current === signature) return;
    positionsSignatureRef.current = signature;
    void load(name, false);
  }, [liveCards, name, load]);

  const liveCard = liveCards.find((c) => c.name === name);
  const mood = liveCard ? moodFromPnl(liveCard.today_pnl_pct * 100) : "neutral";
  const meta = liveCard
    ? `${liveCard.markets.join(" · ")} · ${liveCard.base_currency}`
    : null;

  return (
    <div className="app-shell">
      <header className="detail-header">
        <Link to="/" className="btn btn--ghost detail-header__back">
          ← 대시보드
        </Link>
        <div className="detail-header__identity">
          <Avatar character={name || "?"} mood={mood} size={48} />
          <div>
            <h1 className="detail-header__name">{name || "알 수 없음"}</h1>
            {meta && <span className="detail-header__meta">{meta}</span>}
          </div>
        </div>
        {name && (
          <div className="detail-header__actions">
            <button type="button" className="btn btn--primary" onClick={() => setFlowMode("deposit")}>
              입금
            </button>
            <button type="button" className="btn btn--outline" onClick={() => setFlowMode("withdraw")}>
              출금
            </button>
          </div>
        )}
      </header>

      {name && flowMode && (
        <FlowModal
          name={name}
          mode={flowMode}
          positions={data?.positions ?? []}
          onClose={() => setFlowMode(null)}
        />
      )}

      {!name && (
        <div className="page-state page-state--error">캐릭터 이름이 없습니다.</div>
      )}

      {name && loading && <div className="page-state">불러오는 중…</div>}

      {name && !loading && error && !data && (
        <div className="page-state page-state--error">
          데이터를 불러오지 못했습니다: {error}
        </div>
      )}

      {name && !loading && data && (
        <div className="detail-sections">
          <section className="detail-panel detail-panel--strip">
            <MetricsPanel metrics={data.metrics} />
          </section>

          <section className="detail-panel">
            <h2 className="detail-panel__title">자산곡선</h2>
            <EquityChart points={data.equity} />
          </section>

          <section className="detail-panel">
            <h2 className="detail-panel__title">
              오늘의 후보
              <span className="detail-panel__count num">{data.candidates.length}</span>
            </h2>
            <CandidatesTable candidates={data.candidates} />
          </section>

          <section className="detail-panel">
            <h2 className="detail-panel__title">
              보유종목
              <span className="detail-panel__count num">{data.positions.length}</span>
            </h2>
            <PositionsTable positions={data.positions} />
          </section>

          <section className="detail-panel">
            <h2 className="detail-panel__title">
              거래내역
              <span className="detail-panel__count num">{data.trades.length}</span>
            </h2>
            <TradesTable trades={data.trades} />
          </section>
        </div>
      )}
    </div>
  );
}

export default Detail;
