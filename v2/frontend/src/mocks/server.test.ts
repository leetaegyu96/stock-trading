// 목 API 가 SPEC §7 계약을 지키는지 고정한다. 목이 실제 응답과 어긋나면 백엔드가
// 붙는 날 화면이 깨지므로, 목도 테스트로 붙잡아 둔다.
import { beforeAll, beforeEach, describe, expect, it } from "vitest";
import * as api from "../api";
import { estimateBuy } from "../components/money";
import { installMockApi, resetMockState } from "./server";

beforeAll(() => {
  installMockApi();
});

beforeEach(() => {
  resetMockState();
});

describe("목 API 계약", () => {
  it("캐릭터는 국내(KRW)·해외(USD) 2개다", async () => {
    const accounts = await api.getAccounts();
    expect(accounts).toHaveLength(2);
    expect(accounts.map((a) => a.kind)).toEqual(["KR", "US"]);
    expect(accounts.map((a) => a.currency)).toEqual(["KRW", "USD"]);
    // 총자산 = 현금 + 평가액 (SPEC §7 계좌 요약)
    for (const a of accounts) {
      expect(a.total_asset).toBeCloseTo(a.cash + a.market_value, 2);
    }
  });

  it("종목 목록은 §4.2 필드를 모두 담는다", async () => {
    const [stock] = await api.getStocks("KR");
    expect(Object.keys(stock).sort()).toEqual(
      [
        "change_pct",
        "high_52w",
        "low_52w",
        "name",
        "price",
        "spark7",
        "stale",
        "symbol",
        "volume",
        "volume_vs_avg",
        "week_change_pct",
      ].sort()
    );
    expect(stock.spark7).toHaveLength(7);
  });

  it("종목 상세는 30일 일봉을 함께 준다", async () => {
    const detail = await api.getStock("KR", "005930");
    expect(detail.bars30).toHaveLength(30);
    expect(detail.currency).toBe("KRW");
    expect(Object.keys(detail.bars30[0]).sort()).toEqual(
      ["close", "date", "high", "low", "open", "volume"].sort()
    );
  });

  it("매수하면 현금이 수수료만큼 더 줄고 포지션이 생긴다", async () => {
    const before = (await api.getAccounts())[0];
    const stock = await api.getStock("KR", "005380");
    const expected = estimateBuy(stock.price, 3, "KR", "KRW");

    const result = await api.buy(before.id, { symbol: "005380", quantity: 3 });

    expect(result.trade.side).toBe("BUY");
    expect(result.trade.reason).toBe("MANUAL");
    expect(result.trade.net).toBe(-expected.total);
    expect(result.account.cash).toBe(before.cash - expected.total);
    expect(result.position?.quantity).toBe(3);
  });

  it("현금보다 비싸게 사려 하면 INSUFFICIENT_CASH 로 거부한다", async () => {
    const accounts = await api.getAccounts();
    await expect(api.buy(accounts[0].id, { symbol: "005930", quantity: 10_000_000 })).rejects.toMatchObject(
      { code: "INSUFFICIENT_CASH" }
    );
  });

  it("매도벽을 저장하면 평단 기준 발동가가 함께 내려온다", async () => {
    const positions = await api.getPositions(1);
    const pos = positions[0];
    const rule = await api.putSellRule(pos.id, { stop_loss_pct: -5, take_profit_pct: 15 });

    expect(rule.stop_price).toBe(Math.round(pos.avg_price * 0.95));
    expect(rule.take_price).toBe(Math.round(pos.avg_price * 1.15));
    expect(rule.active).toBe(true);
  });

  it("전량 매도하면 포지션이 사라진다", async () => {
    const [pos] = await api.getPositions(1);
    const result = await api.sell(1, { symbol: pos.symbol, quantity: pos.quantity });

    expect(result.position).toBeNull();
    expect(result.trade.realized_pnl).not.toBeNull();
    const after = await api.getPositions(1);
    expect(after.find((p) => p.symbol === pos.symbol)).toBeUndefined();
  });

  it("거래 내역에는 자동매도의 발동선이 남아 있다", async () => {
    const page = await api.getTrades(1);
    const auto = page.items.find((t) => t.reason === "AUTO_TAKE_PROFIT");
    expect(auto).toBeDefined();
    expect(auto!.trigger_price).not.toBeNull();
    expect(auto!.sell_rule_id).not.toBeNull();
  });
});
