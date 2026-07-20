// FastAPI 백엔드(`/api/...`)용 fetch 래퍼. base URL은 상대 경로로 두어
// FastAPI가 정적 빌드를 서빙할 때(같은 오리진)와 `vite dev`(프록시 경유) 모두 동작한다.
import type {
  CandidateOut,
  CardSummary,
  Dashboard,
  EquityPoint,
  LifecycleOut,
  MarketStatus,
  Metrics,
  PositionOut,
  TradesPage,
  TradesQuery,
} from "./types";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// Vite base(서브패스 배포시 VITE_BASE_PATH)를 그대로 API prefix로 재사용한다.
// 루트("/") 배포면 빈 문자열이라 기존 동작과 동일.
const BASE_PATH =
  import.meta.env.BASE_URL === "/" ? "" : import.meta.env.BASE_URL.replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE_PATH + path, {
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      // 응답 본문이 JSON이 아니면 statusText 그대로 사용
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export function getCharacters(): Promise<CardSummary[]> {
  return request<CardSummary[]>("/api/characters");
}

export function getDetail(name: string): Promise<Metrics> {
  return request<Metrics>(`/api/characters/${encodeURIComponent(name)}`);
}

export function getEquity(name: string): Promise<EquityPoint[]> {
  return request<EquityPoint[]>(
    `/api/characters/${encodeURIComponent(name)}/equity`
  );
}

export function getPositions(name: string): Promise<PositionOut[]> {
  return request<PositionOut[]>(
    `/api/characters/${encodeURIComponent(name)}/positions`
  );
}

/** 오늘의 매수후보(의사결정판, 감사 Phase B). */
export function getCandidates(name: string): Promise<CandidateOut[]> {
  return request<CandidateOut[]>(
    `/api/characters/${encodeURIComponent(name)}/candidates`
  );
}

/** 거래 내역(페이지네이션+필터) — 응답은 TradesPage({items, total}). */
export function getTrades(name: string, query: TradesQuery = {}): Promise<TradesPage> {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.offset !== undefined) params.set("offset", String(query.offset));
  if (query.symbol) params.set("symbol", query.symbol);
  if (query.side) params.set("side", query.side);
  if (query.decision_type) params.set("decision_type", query.decision_type);
  if (query.date_from) params.set("date_from", query.date_from);
  if (query.date_to) params.set("date_to", query.date_to);
  const qs = params.toString();
  return request<TradesPage>(
    `/api/characters/${encodeURIComponent(name)}/trades${qs ? `?${qs}` : ""}`
  );
}

/** 포지션 생애(진입→청산) 목록 — 진행중 우선+최근 entry_date 정렬. limit은 하한. */
export function getLifecycles(name: string, limit?: number): Promise<LifecycleOut[]> {
  const qs = limit !== undefined ? `?limit=${limit}` : "";
  return request<LifecycleOut[]>(
    `/api/characters/${encodeURIComponent(name)}/lifecycles${qs}`
  );
}

export function postDeposit(
  name: string,
  amount_krw: number
): Promise<{ queued: boolean; request_id: number }> {
  return request(`/api/characters/${encodeURIComponent(name)}/deposit`, {
    method: "POST",
    body: JSON.stringify({ amount_krw }),
  });
}

export function postWithdraw(
  name: string,
  amount_krw: number,
  liquidate: string[] = []
): Promise<{ queued: boolean; request_id: number }> {
  return request(`/api/characters/${encodeURIComponent(name)}/withdraw`, {
    method: "POST",
    body: JSON.stringify({ amount_krw, liquidate }),
  });
}

export function getDashboard(): Promise<Dashboard> {
  return request<Dashboard>("/api/dashboard");
}

/** 시장별 데이터 기준(run_state) — as-of 표시용(P0). */
export function getMarketStatus(): Promise<MarketStatus[]> {
  return request<MarketStatus[]>("/api/status");
}

export { ApiError };
