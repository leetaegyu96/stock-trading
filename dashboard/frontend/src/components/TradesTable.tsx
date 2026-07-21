// 거래내역 테이블: 매수/매도 칩, 사유 한글 라벨 칩(손절/익절 강조),
// 신호 한 줄 요약(🟢/🔴 + signal_summary) + 펼치면 이름·별점 상세.
// + 페이지네이션(기본 20건), 필터(기간·종목·매수/매도·결정유형), "포지션 생애" 토글 뷰.
// 프레젠테이션 컴포넌트로 유지(fetch/effect 없음) — 페이지네이션/필터/뷰 상태는 전부
// props로 주입받아 SSR(renderToStaticMarkup)로도 검증 가능하다. 실제 상태 보관·API
// 호출은 pages/Detail.tsx가 담당한다.
import { useState } from "react";
import type { LifecycleOut, TradeOut } from "../types";
import {
  NEWS_FLOW_DISCLAIMER,
  SIGNAL_AXIS_LABEL,
  TECH_AXIS_ONLY_BADGE,
  UNCOMPUTED_AXIS_LABEL,
  changeArrow,
  decisionInfo,
  formatPrice,
  formatSignedPrice,
  reasonInfo,
  shortDate,
  sideLabel,
  signClass,
  signalKind,
  starString,
} from "./format";

export type TradesView = "flat" | "lifecycle";

export interface TradesPaginationState {
  /** 1-based 현재 페이지. */
  page: number;
  pageSize: number;
  /** 필터 기준 전체 건수(TradesPage.total). */
  total: number;
}

export interface TradesFilterState {
  symbol: string;
  side: string; // "" | "BUY" | "SELL"
  decisionType: string; // "" | "BUY" | "PARTIAL_SELL" | "FULL_SELL" | "FORCED_SELL"
  dateFrom: string;
  dateTo: string;
}

export interface TradesTableProps {
  /** 현재 페이지(플랫 뷰)의 거래 목록. */
  trades: TradeOut[];
  className?: string;
  pagination?: TradesPaginationState;
  onPageChange?: (page: number) => void;
  filters?: TradesFilterState;
  onFilterChange?: (patch: Partial<TradesFilterState>) => void;
  view?: TradesView;
  onViewChange?: (view: TradesView) => void;
  /** "포지션 생애" 뷰용 데이터. view==="lifecycle"일 때만 사용. */
  lifecycles?: LifecycleOut[];
}

function SignalCell({ trade }: { trade: TradeOut }) {
  const [expanded, setExpanded] = useState(false);
  const isBuy = sideLabel(trade.side) === "매수";
  const hasSummary = trade.signal_summary.trim().length > 0;
  const hasDetail = trade.signal_detail.length > 0;

  if (!hasSummary && !hasDetail) return <span className="muted">—</span>;

  return (
    <div className="signal-cell">
      <div className="signal-cell__summary">
        <span aria-hidden="true">{isBuy ? "🟢" : "🔴"}</span>
        <span>{hasSummary ? trade.signal_summary : "—"}</span>
        {hasDetail && (
          <button
            type="button"
            className="signal-cell__toggle"
            onClick={() => setExpanded((prev) => !prev)}
          >
            {expanded ? "접기 ˄" : "펼쳐보기 ˅"}
          </button>
        )}
      </div>
      {expanded && hasDetail && (
        <ul className="signal-cell__detail">
          {trade.signal_detail.map((d) => (
            <li key={d.code} className="signal-cell__detail-item">
              <span className={`signal-cell__detail-dot sig--${signalKind(d.code)}`} aria-hidden="true" />
              <span className="signal-cell__detail-name">{d.name}</span>
              <span className="signal-cell__stars" aria-label={`별점 ${d.stars}점`}>
                {starString(d.stars)}
              </span>
              <span className="signal-cell__detail-code muted">{d.code}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 결정유형 칩(부분/전량/강제매도). BUY/미분류는 칩을 그리지 않는다 —
 * "구분" 열의 매수/매도 칩으로 이미 충분하고, 이 칩은 매도의 강도만 보탠다. */
function DecisionChip({ decisionType }: { decisionType: string }) {
  const info = decisionInfo(decisionType);
  if (info.kind === "buy" || info.kind === "unknown") return null;
  return <span className={`chip chip--${info.kind}`}>{info.label}</span>;
}

/** 신호 표시 상단 고지: 라벨을 "청/적신호"가 아닌 "기술적 매수/매도 신호"로 통일하고,
 * Phase A엔 기술적 축만 계산된다는 점 + 뉴스·공시·수급 미반영을 항상 함께 보여준다(P0-2).
 * 미계산 축은 0점으로 위장하지 않고 UNCOMPUTED_AXIS_LABEL("미수집/판단 불가")로
 * 명시적으로 표시한다 — 조용히 생략하지 않는다. */
function SignalNotice() {
  return (
    <div className="signal-notice">
      <span className="signal-notice__title">{SIGNAL_AXIS_LABEL}</span>
      <span className="signal-notice__badge">{TECH_AXIS_ONLY_BADGE}</span>
      <p className="signal-notice__disclaimer">{NEWS_FLOW_DISCLAIMER}</p>
      <p className="signal-notice__axis">
        뉴스 · 공시 · 수급 · 거시: {UNCOMPUTED_AXIS_LABEL}
      </p>
    </div>
  );
}

/** 실현손익 셀: 색상 단독이 아니라 ▲/▼ 부호를 aria-hidden 스팬으로 병행한다(접근성). */
function PnlCell({ trade }: { trade: TradeOut }) {
  const isBuy = sideLabel(trade.side) === "매수";
  if (isBuy) return <>—</>;
  return (
    <>
      <span aria-hidden="true">{changeArrow(trade.realized_pnl)}</span>{" "}
      {formatSignedPrice(trade.market, trade.realized_pnl)}
    </>
  );
}

function TradesFlatTable({ trades }: { trades: TradeOut[] }) {
  if (trades.length === 0) {
    return <div className="detail-panel__state">거래 내역이 없습니다.</div>;
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table className="detail-table">
        <thead>
          <tr>
            <th>일자</th>
            <th>종목</th>
            <th>구분</th>
            <th className="ta-r">수량</th>
            <th className="ta-r">체결가</th>
            <th>사유</th>
            <th>{SIGNAL_AXIS_LABEL}</th>
            <th className="ta-r">실현손익</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => {
            const side = sideLabel(trade.side);
            const isBuy = side === "매수";
            const reason = reasonInfo(trade.reason);
            return (
              <tr key={`${trade.ts}:${trade.symbol}:${trade.side}`}>
                <td className="num muted">{shortDate(trade.date || trade.ts)}</td>
                <td>
                  <span className="detail-table__name">{trade.name}</span>
                  <span className="detail-table__code">{trade.symbol}</span>
                  <span className={`mkt mkt--${trade.market.toLowerCase()}`}>{trade.market}</span>
                </td>
                <td>
                  <span className={`chip chip--${isBuy ? "up" : "down"}`}>{side}</span>{" "}
                  <DecisionChip decisionType={trade.decision_type} />
                </td>
                <td className="ta-r num">{trade.quantity.toLocaleString("ko-KR")}</td>
                <td className="ta-r num">{formatPrice(trade.market, trade.price)}</td>
                <td>
                  <span className={`reason reason--${reason.kind}`}>{reason.label}</span>
                </td>
                <td className="signal-cell-td">
                  <SignalCell trade={trade} />
                </td>
                <td className={`ta-r num strong ${isBuy ? "muted" : signClass(trade.realized_pnl)}`}>
                  <PnlCell trade={trade} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** 거래/필터 바 — 기간·종목·매수/매도·결정유형. onFilterChange는 부분 패치를 받는다. */
function FilterBar({
  filters,
  onFilterChange,
}: {
  filters: TradesFilterState;
  onFilterChange: (patch: Partial<TradesFilterState>) => void;
}) {
  return (
    <div className="trades-filter-bar">
      <input
        type="text"
        className="trades-filter-bar__symbol"
        placeholder="종목코드"
        value={filters.symbol}
        onChange={(e) => onFilterChange({ symbol: e.target.value })}
      />
      <select
        aria-label="매수/매도"
        value={filters.side}
        onChange={(e) => onFilterChange({ side: e.target.value })}
      >
        <option value="">전체</option>
        <option value="BUY">매수</option>
        <option value="SELL">매도</option>
      </select>
      <select
        aria-label="결정유형"
        value={filters.decisionType}
        onChange={(e) => onFilterChange({ decisionType: e.target.value })}
      >
        <option value="">전체</option>
        <option value="BUY">매수</option>
        <option value="PARTIAL_SELL">부분매도</option>
        <option value="FULL_SELL">전량매도</option>
        <option value="FORCED_SELL">강제매도</option>
        <option value="INTRADAY_BUY">장중 매수</option>
        <option value="INTRADAY_SELL">장중 매도</option>
      </select>
      <input
        type="date"
        aria-label="시작일"
        value={filters.dateFrom}
        onChange={(e) => onFilterChange({ dateFrom: e.target.value })}
      />
      <span className="muted">~</span>
      <input
        type="date"
        aria-label="종료일"
        value={filters.dateTo}
        onChange={(e) => onFilterChange({ dateTo: e.target.value })}
      />
    </div>
  );
}

/** 거래내역/포지션 생애 뷰 토글. */
function ViewToggle({
  view,
  onViewChange,
}: {
  view: TradesView;
  onViewChange: (view: TradesView) => void;
}) {
  return (
    <div className="seg" role="group" aria-label="거래 보기 전환">
      <button
        type="button"
        className={`seg__btn${view === "flat" ? " is-active" : ""}`}
        onClick={() => onViewChange("flat")}
      >
        거래내역
      </button>
      <button
        type="button"
        className={`seg__btn${view === "lifecycle" ? " is-active" : ""}`}
        onClick={() => onViewChange("lifecycle")}
      >
        포지션 생애
      </button>
    </div>
  );
}

/** 페이지네이션 풋터 — 페이지 표시(N / M)와 이전/다음 버튼 상태(경계에서 비활성화). */
function PaginationFooter({
  pagination,
  onPageChange,
}: {
  pagination: TradesPaginationState;
  onPageChange?: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(pagination.total / pagination.pageSize));
  const page = Math.min(Math.max(1, pagination.page), totalPages);
  return (
    <div className="trades-pagination">
      <span className="trades-pagination__total muted">
        총 {pagination.total.toLocaleString("ko-KR")}건
      </span>
      <div className="trades-pagination__controls">
        <button
          type="button"
          aria-label="이전 페이지"
          className="btn btn--ghost"
          disabled={page <= 1}
          onClick={() => onPageChange?.(page - 1)}
        >
          이전
        </button>
        <span className="trades-pagination__pos num">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          aria-label="다음 페이지"
          className="btn btn--ghost"
          disabled={page >= totalPages}
          onClick={() => onPageChange?.(page + 1)}
        >
          다음
        </button>
      </div>
    </div>
  );
}

/** 포지션 생애 카드 하나 — 진입→(부분)→청산 거래 묶음 + 생애 손익 합계 + 진행중 표시. */
function LifecycleCard({ life }: { life: LifecycleOut }) {
  const pnlSign = signClass(life.realized_pnl_sum);
  return (
    <div className="lifecycle-card">
      <div className="lifecycle-card__head">
        <span className="detail-table__name">{life.name}</span>
        <span className="detail-table__code">{life.symbol}</span>
        <span className={`mkt mkt--${life.market.toLowerCase()}`}>{life.market}</span>
        {life.open ? (
          <span className="chip chip--down">진행중</span>
        ) : (
          <span className="muted">청산 {life.exit_date ? shortDate(life.exit_date) : "—"}</span>
        )}
        <span className="lifecycle-card__entry muted">
          진입 {shortDate(life.entry_date)} · 최대 {life.qty_peak.toLocaleString("ko-KR")}주
        </span>
        <span className={`lifecycle-card__sum num strong ${pnlSign}`}>
          <span aria-hidden="true">{changeArrow(life.realized_pnl_sum)}</span>{" "}
          생애손익 {formatSignedPrice(life.market, life.realized_pnl_sum)}
        </span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="detail-table lifecycle-card__trades">
          <thead>
            <tr>
              <th>일자</th>
              <th>구분</th>
              <th className="ta-r">수량</th>
              <th className="ta-r">체결가</th>
              <th className="ta-r">실현손익</th>
            </tr>
          </thead>
          <tbody>
            {life.trades.map((trade) => {
              const side = sideLabel(trade.side);
              const isBuy = side === "매수";
              return (
                <tr key={`${trade.ts}:${trade.side}:${trade.quantity}`}>
                  <td className="num muted">{shortDate(trade.date || trade.ts)}</td>
                  <td>
                    <span className={`chip chip--${isBuy ? "up" : "down"}`}>{side}</span>{" "}
                    <DecisionChip decisionType={trade.decision_type} />
                  </td>
                  <td className="ta-r num">{trade.quantity.toLocaleString("ko-KR")}</td>
                  <td className="ta-r num">{formatPrice(trade.market, trade.price)}</td>
                  <td className={`ta-r num ${isBuy ? "muted" : signClass(trade.realized_pnl)}`}>
                    <PnlCell trade={trade} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LifecycleView({ lifecycles }: { lifecycles: LifecycleOut[] }) {
  if (lifecycles.length === 0) {
    return <div className="detail-panel__state">포지션 생애 데이터가 없습니다.</div>;
  }
  return (
    <div className="lifecycle-list">
      {lifecycles.map((life) => (
        <LifecycleCard key={`${life.symbol}:${life.entry_date}`} life={life} />
      ))}
    </div>
  );
}

export function TradesTable({
  trades,
  className,
  pagination,
  onPageChange,
  filters,
  onFilterChange,
  view = "flat",
  onViewChange,
  lifecycles,
}: TradesTableProps) {
  const showLifecycle = view === "lifecycle";

  return (
    <div className={className}>
      {filters && onFilterChange && <FilterBar filters={filters} onFilterChange={onFilterChange} />}
      {onViewChange && <ViewToggle view={view} onViewChange={onViewChange} />}
      {!showLifecycle && <SignalNotice />}
      {showLifecycle ? (
        <LifecycleView lifecycles={lifecycles ?? []} />
      ) : (
        <TradesFlatTable trades={trades} />
      )}
      {pagination && !showLifecycle && (
        <PaginationFooter pagination={pagination} onPageChange={onPageChange} />
      )}
    </div>
  );
}

export default TradesTable;
