// FastAPI 백엔드(`/api/...`)용 fetch 래퍼. base URL은 상대 경로로 두어
// FastAPI가 정적 빌드를 서빙할 때(같은 오리진)와 `vite dev`(프록시 경유) 모두 동작한다.
import type {
  CardSummary,
  Dashboard,
  EquityPoint,
  Metrics,
  PositionOut,
  TradeOut,
} from "./types";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
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

export function getTrades(name: string, limit?: number): Promise<TradeOut[]> {
  const qs = limit !== undefined ? `?limit=${limit}` : "";
  return request<TradeOut[]>(
    `/api/characters/${encodeURIComponent(name)}/trades${qs}`
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

export { ApiError };
