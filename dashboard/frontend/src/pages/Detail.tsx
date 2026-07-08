// 캐릭터 상세 페이지 (설계 스펙 §6 "상세"): 자산곡선 차트 · 성과지표 · 보유종목 ·
// 거래내역. 마운트 시 REST로 4종 데이터를 한 번에 불러오고, 백엔드에 캐릭터 단위
// WS 스트림이 없으므로 메인 카드 브로드캐스트(useCardsSocket)에서 이 캐릭터의
// 포지션 관련 값(보유종목수/총자산/현금)이 바뀌면 조용히 재조회한다.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, getDetail, getEquity, getPositions, getTrades } from "../api";
import { useCardsSocket } from "../ws";
import { Avatar } from "../components/Avatar";
import { moodFromPnl } from "../components/mood";
import { EquityChart } from "../components/EquityChart";
import { PositionsTable } from "../components/PositionsTable";
import { TradesTable } from "../components/TradesTable";
import { MetricsPanel } from "../components/MetricsPanel";
import { FlowModal } from "../components/FlowModal";
import type { FlowMode } from "../components/FlowModal";
import type { EquityPoint, Metrics, PositionOut, TradeOut } from "../types";
import "../components/theme.css";
import "../components/detail.css";

interface DetailData {
  metrics: Metrics;
  equity: EquityPoint[];
  positions: PositionOut[];
  trades: TradeOut[];
}

const TRADES_LIMIT = 100;

export function Detail() {
  const { name: rawName } = useParams<{ name: string }>();
  const name = rawName ?? "";

  const [data, setData] = useState<DetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [flowMode, setFlowMode] = useState<FlowMode | null>(null);
  const liveCards = useCardsSocket();
  const positionsSignatureRef = useRef<string | null>(null);

  const load = useCallback((targetName: string, showSpinner: boolean) => {
    if (showSpinner) setLoading(true);
    return Promise.all([
      getDetail(targetName),
      getEquity(targetName),
      getPositions(targetName),
      getTrades(targetName, TRADES_LIMIT),
    ])
      .then(([metrics, equity, positions, trades]) => {
        setData({ metrics, equity, positions, trades });
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

  // 초기 로드: 캐릭터가 바뀔 때마다 REST로 4종 데이터를 새로 불러온다.
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

  // 실시간 갱신: 카드 스냅샷에서 이 캐릭터의 포지션 관련 값이 바뀌면 스피너 없이 재조회.
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

  return (
    <div className="main-page">
      <p>
        <Link to="/">← 메인으로</Link>
      </p>
      <header className="detail-header">
        <Avatar character={name || "?"} mood={mood} size={64} />
        <h1 className="main-page__title">{name || "알 수 없음"}</h1>
        {name && (
          <div className="detail-header__actions">
            <button
              type="button"
              className="detail-header__flow-btn"
              onClick={() => setFlowMode("deposit")}
            >
              입금
            </button>
            <button
              type="button"
              className="detail-header__flow-btn"
              onClick={() => setFlowMode("withdraw")}
            >
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
        <div className="main-page__state main-page__state--error">
          캐릭터 이름이 없습니다.
        </div>
      )}

      {name && loading && <div className="main-page__state">불러오는 중…</div>}

      {name && !loading && error && !data && (
        <div className="main-page__state main-page__state--error">
          데이터를 불러오지 못했습니다: {error}
        </div>
      )}

      {name && !loading && data && (
        <div className="detail-sections">
          <section className="detail-panel">
            <h2 className="detail-panel__title">자산곡선</h2>
            <EquityChart points={data.equity} />
          </section>

          <section className="detail-panel">
            <h2 className="detail-panel__title">성과지표</h2>
            <MetricsPanel metrics={data.metrics} />
          </section>

          <section className="detail-panel">
            <h2 className="detail-panel__title">보유종목</h2>
            <PositionsTable positions={data.positions} />
          </section>

          <section className="detail-panel">
            <h2 className="detail-panel__title">거래내역</h2>
            <TradesTable trades={data.trades} />
          </section>
        </div>
      )}
    </div>
  );
}

export default Detail;
