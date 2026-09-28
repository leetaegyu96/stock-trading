// FastAPI 백엔드(`/api/...`) fetch 래퍼.
//
// 경로는 Vite base(= VITE_BASE_PATH) 기준 상대경로로 만든다. 그래야 백엔드가 정적
// 빌드를 서빙할 때(같은 오리진)와 `vite dev`(프록시 경유)가 모두 동작한다.
// 인증은 httpOnly 쿠키(SPEC §3)라 fetch 마다 credentials: "include" 가 필수다.
import type {
  AccountDetail,
  AccountKind,
  AccountSummary,
  ApiErrorBody,
  EventLog,
  LoginRequest,
  Me,
  OrderRequest,
  OrderResult,
  Position,
  SellRule,
  SellRuleRequest,
  SignupRequest,
  StockDetail,
  StocksPage,
  TradesPage,
  TradesQuery,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
  /** 세션 만료·미로그인 — 호출부는 이때 로그인 화면으로 보낸다. */
  get isUnauthorized(): boolean {
    return this.status === 401 || this.code === "UNAUTHORIZED";
  }
}

// 루트("/") 배포면 빈 문자열, `/stock-v2/` 배포면 "/stock-v2".
export const BASE_PATH =
  import.meta.env.BASE_URL === "/" ? "" : import.meta.env.BASE_URL.replace(/\/$/, "");

/**
 * 401 전역 훅. App 이 여기에 "로그인 화면으로 보내기"를 등록한다.
 * 라우터를 api 모듈이 직접 import 하면 순환 의존이 생기므로 콜백으로 뒤집었다.
 */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE_PATH + path, {
    // 세션 쿠키가 httpOnly 라 자바스크립트로 붙일 수 없다 — 브라우저가 싣게 한다.
    credentials: "include",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });

  if (!res.ok) {
    let code = String(res.status);
    let message = res.statusText || "요청을 처리하지 못했습니다.";
    try {
      const body = (await res.json()) as Partial<ApiErrorBody>;
      if (body?.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
      }
    } catch {
      // 본문이 JSON 이 아니면 statusText 를 그대로 쓴다.
    }
    const err = new ApiError(res.status, code, message);
    // 로그인 시도 자체의 401(비밀번호 틀림)까지 리다이렉트하면 화면이 튀므로 제외한다.
    if (err.isUnauthorized && !path.startsWith("/api/auth/")) onUnauthorized?.();
    throw err;
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function body(data: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(data) };
}

// ── 인증 (SPEC §7 인증) ──────────────────────────────────────────────────
export function signup(payload: SignupRequest): Promise<Me> {
  return request<Me>("/api/auth/signup", body(payload));
}

export function login(payload: LoginRequest): Promise<Me> {
  return request<Me>("/api/auth/login", body(payload));
}

export function logout(): Promise<void> {
  return request<void>("/api/auth/logout", { method: "POST" });
}

export function getMe(): Promise<Me> {
  return request<Me>("/api/auth/me");
}

// ── 계좌·보유 ────────────────────────────────────────────────────────────
export function getAccounts(): Promise<AccountSummary[]> {
  return request<AccountSummary[]>("/api/accounts");
}

export function getAccount(accountId: number): Promise<AccountDetail> {
  return request<AccountDetail>(`/api/accounts/${accountId}`);
}

export function getPositions(accountId: number): Promise<Position[]> {
  return request<Position[]>(`/api/accounts/${accountId}/positions`);
}

export function getTrades(accountId: number, query: TradesQuery = {}): Promise<TradesPage> {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.offset !== undefined) params.set("offset", String(query.offset));
  if (query.symbol) params.set("symbol", query.symbol);
  if (query.side) params.set("side", query.side);
  if (query.reason) params.set("reason", query.reason);
  const qs = params.toString();
  return request<TradesPage>(`/api/accounts/${accountId}/trades${qs ? `?${qs}` : ""}`);
}

export function getEvents(accountId: number): Promise<EventLog[]> {
  return request<EventLog[]>(`/api/accounts/${accountId}/events`);
}

// ── 시세 ────────────────────────────────────────────────────────────────
export const STOCKS_PAGE_SIZE = 30;

export function getStocks(
  kind: AccountKind,
  offset = 0,
  limit = STOCKS_PAGE_SIZE
): Promise<StocksPage> {
  return request<StocksPage>(
    `/api/market/${kind}/stocks?offset=${offset}&limit=${limit}`
  );
}

export function getStock(kind: AccountKind, symbol: string): Promise<StockDetail> {
  return request<StockDetail>(`/api/market/${kind}/stocks/${encodeURIComponent(symbol)}`);
}

// ── 주문 ────────────────────────────────────────────────────────────────
export function buy(accountId: number, order: OrderRequest): Promise<OrderResult> {
  return request<OrderResult>(`/api/accounts/${accountId}/buy`, body(order));
}

export function sell(accountId: number, order: OrderRequest): Promise<OrderResult> {
  return request<OrderResult>(`/api/accounts/${accountId}/sell`, body(order));
}

export function putSellRule(positionId: number, rule: SellRuleRequest): Promise<SellRule> {
  return request<SellRule>(`/api/positions/${positionId}/sell-rule`, {
    method: "PUT",
    body: JSON.stringify(rule),
  });
}

export function deleteSellRule(positionId: number): Promise<void> {
  return request<void>(`/api/positions/${positionId}/sell-rule`, { method: "DELETE" });
}
