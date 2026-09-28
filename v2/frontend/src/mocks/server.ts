// 목 API 서버. 백엔드(:8030)가 아직 없어도 프론트를 끝까지 눌러볼 수 있게
// `fetch` 를 가로채 SPEC §7 계약대로 응답한다.
//
// 상태를 들고 있어서 매수 → 보유 → 매도벽 → 매도 흐름이 실제처럼 이어진다.
// `VITE_USE_MOCK=1 npm run dev` 일 때만 끼우고, 실제 백엔드가 붙으면 건드리지 않는다.
import { BASE_PATH } from "../api";
import { currencyOf } from "../components/sellwall";
import { estimateBuy, estimateRealizedPnl, estimateSell, roundMinor } from "../components/money";
import { triggerPrice } from "../components/sellwall";
import type {
  AccountDetail,
  AccountSummary,
  Position,
  SellRule,
  SellRuleRequest,
  Trade,
  TradesPage,
} from "../types";
import { MOCK_EQUITY, MOCK_STOCKS, initialMockState, toListItem, type MockState } from "./data";

let state: MockState = initialMockState();

/** 테스트에서 상태를 초기화할 때 쓴다. */
export function resetMockState(): void {
  state = initialMockState();
}

function json(data: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fail(status: number, code: string, message: string): Response {
  return json({ error: { code, message } }, status);
}

function findStock(kind: "KR" | "US", symbol: string) {
  return MOCK_STOCKS[kind].find((s) => s.symbol === symbol) ?? null;
}

function accountById(id: number): AccountSummary | undefined {
  return state.accounts.find((a) => a.id === id);
}

/** 포지션 평가액·손익과 계좌 요약을 현재 시세로 다시 계산한다(불변식 유지). */
function recompute(accountId: number): void {
  const acc = accountById(accountId);
  if (!acc) return;
  const positions = state.positions.filter((p) => p.account_id === accountId);
  for (const p of positions) {
    const stock = findStock(acc.kind, p.symbol);
    if (stock) p.current_price = stock.price;
    p.market_value = roundMinor(p.current_price * p.quantity, acc.currency);
    p.cost_basis = roundMinor(p.avg_price * p.quantity, acc.currency);
    p.unrealized_pnl = roundMinor(p.market_value - p.cost_basis, acc.currency);
    p.unrealized_pnl_pct =
      p.avg_price > 0 ? Math.round((p.current_price / p.avg_price - 1) * 10000) / 100 : 0;
  }
  acc.market_value = roundMinor(
    positions.reduce((a, p) => a + p.market_value, 0),
    acc.currency
  );
  acc.total_asset = roundMinor(acc.cash + acc.market_value, acc.currency);
  acc.pnl = roundMinor(acc.total_asset - acc.seed, acc.currency);
  acc.return_pct = acc.seed > 0 ? Math.round((acc.total_asset / acc.seed - 1) * 10000) / 100 : 0;
  acc.position_count = positions.length;
}

function orderResult(trade: Trade, accountId: number, symbol: string) {
  recompute(accountId);
  return {
    trade,
    account: accountById(accountId)!,
    position: state.positions.find((p) => p.account_id === accountId && p.symbol === symbol) ?? null,
  };
}

function handleBuy(accountId: number, payload: OrderBody): Response {
  const acc = accountById(accountId);
  if (!acc) return fail(404, "NOT_FOUND", "캐릭터를 찾을 수 없습니다.");
  const { symbol, quantity } = payload;
  if (!Number.isInteger(quantity) || quantity <= 0) {
    return fail(400, "INVALID_QUANTITY", "수량은 1주 이상의 정수여야 합니다.");
  }
  const stock = findStock(acc.kind, symbol);
  if (!stock) return fail(400, "MARKET_MISMATCH", "이 캐릭터가 살 수 없는 종목입니다.");

  const est = estimateBuy(stock.price, quantity, acc.kind, acc.currency);
  if (est.total > acc.cash) {
    return fail(
      400,
      "INSUFFICIENT_CASH",
      `현금이 부족합니다. ${Math.round(est.total).toLocaleString("ko-KR")}이 필요한데 ` +
        `잔고는 ${Math.round(acc.cash).toLocaleString("ko-KR")}입니다.`
    );
  }

  acc.cash = roundMinor(acc.cash - est.total, acc.currency);
  const existing = state.positions.find((p) => p.account_id === accountId && p.symbol === symbol);
  if (existing) {
    // 평단 가중평균: 매수 수수료를 포함해 갱신한다(SPEC §5.1).
    const invested = existing.avg_price * existing.quantity + est.total;
    existing.quantity += quantity;
    existing.avg_price = roundMinor(invested / existing.quantity, acc.currency);
  } else {
    state.positions.push({
      id: Math.max(0, ...state.positions.map((p) => p.id)) + 1,
      account_id: accountId,
      symbol,
      name: stock.name,
      quantity,
      avg_price: roundMinor(est.total / quantity, acc.currency),
      current_price: stock.price,
      market_value: 0,
      cost_basis: 0,
      unrealized_pnl: 0,
      unrealized_pnl_pct: 0,
      opened_at: new Date().toISOString(),
      stale: stock.stale,
      sell_rule: null,
    });
  }

  const trade: Trade = {
    id: state.nextTradeId++,
    account_id: accountId,
    symbol,
    name: stock.name,
    side: "BUY",
    quantity,
    price: stock.price,
    fee: est.fee,
    tax: 0,
    gross: est.gross,
    net: -est.total,
    realized_pnl: null,
    reason: "MANUAL",
    sell_rule_id: null,
    trigger_price: null,
    executed_at: new Date().toISOString(),
  };
  state.trades.unshift(trade);
  return json(orderResult(trade, accountId, symbol));
}

function handleSell(accountId: number, payload: OrderBody): Response {
  const acc = accountById(accountId);
  if (!acc) return fail(404, "NOT_FOUND", "캐릭터를 찾을 수 없습니다.");
  const { symbol, quantity } = payload;
  const pos = state.positions.find((p) => p.account_id === accountId && p.symbol === symbol);
  if (!pos) return fail(404, "NOT_FOUND", "가지고 있지 않은 종목입니다.");
  if (!Number.isInteger(quantity) || quantity <= 0) {
    return fail(400, "INVALID_QUANTITY", "수량은 1주 이상의 정수여야 합니다.");
  }
  if (quantity > pos.quantity) {
    return fail(400, "INSUFFICIENT_QUANTITY", `가진 수량은 ${pos.quantity}주입니다.`);
  }
  const stock = findStock(acc.kind, symbol);
  if (!stock) return fail(503, "PRICE_UNAVAILABLE", "현재가를 불러오지 못했습니다.");

  const est = estimateSell(stock.price, quantity, acc.kind, acc.currency);
  const realized = estimateRealizedPnl(stock.price, pos.avg_price, quantity, acc.kind, acc.currency);
  acc.cash = roundMinor(acc.cash + est.net, acc.currency);

  // 부분 매도는 평단 유지, 전량 매도는 포지션(과 매도벽)을 지운다(SPEC §6.1).
  pos.quantity -= quantity;
  if (pos.quantity === 0) {
    state.positions = state.positions.filter((p) => p.id !== pos.id);
  }

  const trade: Trade = {
    id: state.nextTradeId++,
    account_id: accountId,
    symbol,
    name: pos.name,
    side: "SELL",
    quantity,
    price: stock.price,
    fee: est.fee,
    tax: est.tax,
    gross: est.gross,
    net: est.net,
    realized_pnl: realized,
    reason: "MANUAL",
    sell_rule_id: null,
    trigger_price: null,
    executed_at: new Date().toISOString(),
  };
  state.trades.unshift(trade);
  return json(orderResult(trade, accountId, symbol));
}

function handleSellRule(positionId: number, payload: SellRuleRequest): Response {
  const pos = state.positions.find((p) => p.id === positionId);
  if (!pos) return fail(404, "NOT_FOUND", "보유 종목을 찾을 수 없습니다.");
  const acc = accountById(pos.account_id)!;
  const stop = payload.stop_loss_pct ?? null;
  const take = payload.take_profit_pct ?? null;
  if (stop === null && take === null) {
    return fail(400, "INVALID_SELL_RULE", "둘 중 하나는 정해야 합니다.");
  }
  const currency = currencyOf(acc.kind);
  const rule: SellRule = {
    id: pos.sell_rule?.id ?? state.nextRuleId++,
    position_id: pos.id,
    stop_loss_pct: stop,
    take_profit_pct: take,
    stop_price: triggerPrice(pos.avg_price, stop, currency),
    take_price: triggerPrice(pos.avg_price, take, currency),
    quantity: payload.quantity ?? pos.quantity,
    active: true,
    created_at: pos.sell_rule?.created_at ?? new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  pos.sell_rule = rule;
  return json(rule);
}

interface OrderBody {
  symbol: string;
  quantity: number;
}

const ROUTES: Array<{
  method: string;
  pattern: RegExp;
  /** payload 는 요청 본문을 파싱한 값(본문이 없으면 빈 객체). */
  handle: (m: RegExpMatchArray, payload: never) => Response;
}> = [
  { method: "POST", pattern: /^\/api\/auth\/signup$/, handle: () => json(state.me) },
  { method: "POST", pattern: /^\/api\/auth\/login$/, handle: () => json(state.me) },
  { method: "POST", pattern: /^\/api\/auth\/logout$/, handle: () => json(null, 204) },
  {
    method: "GET",
    pattern: /^\/api\/auth\/me$/,
    handle: () =>
      state.me ? json(state.me) : fail(401, "UNAUTHORIZED", "로그인이 필요합니다."),
  },
  {
    method: "GET",
    pattern: /^\/api\/accounts$/,
    handle: () => {
      state.accounts.forEach((a) => recompute(a.id));
      return json(state.accounts);
    },
  },
  {
    method: "GET",
    pattern: /^\/api\/accounts\/(\d+)$/,
    handle: (m) => {
      const id = Number(m[1]);
      recompute(id);
      const acc = accountById(id);
      if (!acc) return fail(404, "NOT_FOUND", "캐릭터를 찾을 수 없습니다.");
      const detail: AccountDetail = { ...acc, equity_curve: MOCK_EQUITY[id] ?? [] };
      return json(detail);
    },
  },
  {
    method: "GET",
    pattern: /^\/api\/accounts\/(\d+)\/positions$/,
    handle: (m) => {
      const id = Number(m[1]);
      recompute(id);
      return json(state.positions.filter((p: Position) => p.account_id === id));
    },
  },
  {
    method: "GET",
    pattern: /^\/api\/accounts\/(\d+)\/trades/,
    handle: (m) => {
      const items = state.trades.filter((t) => t.account_id === Number(m[1]));
      const page: TradesPage = { items, total: items.length };
      return json(page);
    },
  },
  { method: "GET", pattern: /^\/api\/accounts\/(\d+)\/events$/, handle: () => json([]) },
  {
    method: "GET",
    pattern: /^\/api\/market\/(KR|US)\/stocks$/,
    handle: (m) => json(MOCK_STOCKS[m[1] as "KR" | "US"].map(toListItem)),
  },
  {
    method: "GET",
    pattern: /^\/api\/market\/(KR|US)\/stocks\/([^/]+)$/,
    handle: (m) => {
      const stock = findStock(m[1] as "KR" | "US", decodeURIComponent(m[2]));
      return stock ? json(stock) : fail(404, "NOT_FOUND", "종목을 찾을 수 없습니다.");
    },
  },
  {
    method: "POST",
    pattern: /^\/api\/accounts\/(\d+)\/buy$/,
    handle: (m, payload: OrderBody) => handleBuy(Number(m[1]), payload),
  },
  {
    method: "POST",
    pattern: /^\/api\/accounts\/(\d+)\/sell$/,
    handle: (m, payload: OrderBody) => handleSell(Number(m[1]), payload),
  },
  {
    method: "PUT",
    pattern: /^\/api\/positions\/(\d+)\/sell-rule$/,
    handle: (m, payload: SellRuleRequest) => handleSellRule(Number(m[1]), payload),
  },
  {
    method: "DELETE",
    pattern: /^\/api\/positions\/(\d+)\/sell-rule$/,
    handle: (m) => {
      const pos = state.positions.find((p) => p.id === Number(m[1]));
      if (pos) pos.sell_rule = null;
      return json(null, 204);
    },
  },
];

/** `fetch` 를 가로채는 목 어댑터를 설치한다. 이미 설치됐으면 아무것도 하지 않는다. */
export function installMockApi(): void {
  const g = globalThis as typeof globalThis & { __v2MockInstalled?: boolean };
  if (g.__v2MockInstalled) return;
  g.__v2MockInstalled = true;

  const real = globalThis.fetch.bind(globalThis);
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    // jsdom 에서는 상대경로로 Request 를 만들 수 없어(절대 URL 강제), 직접 파싱한다.
    const href =
      typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const base =
      typeof globalThis.location === "undefined" ? "http://localhost" : globalThis.location.href;
    const path = new URL(href, base).pathname;
    const apiPath = BASE_PATH && path.startsWith(BASE_PATH) ? path.slice(BASE_PATH.length) : path;
    if (!apiPath.startsWith("/api/")) return real(input as RequestInfo, init);

    const method = (init?.method ?? "GET").toUpperCase();
    let payload: unknown = {};
    if (typeof init?.body === "string") {
      try {
        payload = JSON.parse(init.body);
      } catch {
        return fail(400, "INVALID_INPUT", "요청 본문을 읽지 못했습니다.");
      }
    }

    for (const route of ROUTES) {
      if (route.method !== method) continue;
      const m = apiPath.match(route.pattern);
      if (m) return route.handle(m, payload as never);
    }
    return fail(404, "NOT_FOUND", `목 API 에 없는 경로입니다: ${method} ${apiPath}`);
  };
}
