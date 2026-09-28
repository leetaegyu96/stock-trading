// 개발·테스트용 목 데이터. **SPEC §7/§4.2 의 응답 형태와 정확히 같아야** 한다 —
// 여기가 어긋나면 백엔드가 붙는 날 화면이 통째로 깨진다.
import type {
  AccountSummary,
  DailyBar,
  EquityPoint,
  Me,
  Position,
  RankingRow,
  Stock,
  StockDetail,
  Trade,
} from "../types";

export const MOCK_ME: Me = { id: 1, email: "ltk@example.com", nickname: "초보투자자" };

/** 가상 난수 — 목 데이터가 새로고침마다 달라지면 눈으로 비교가 안 되므로 고정 시드. */
function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

function walk(start: number, n: number, vol: number, seed: number): number[] {
  const rnd = seeded(seed);
  const out: number[] = [];
  let v = start;
  for (let i = 0; i < n; i += 1) {
    v = v * (1 + (rnd() - 0.48) * vol);
    out.push(Math.round(v * 100) / 100);
  }
  return out;
}

function isoDaysAgo(days: number): string {
  const d = new Date("2026-09-28T09:00:00+09:00");
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

function makeBars(closes: number[], seed: number): DailyBar[] {
  const rnd = seeded(seed);
  return closes.map((close, i) => {
    const open = Math.round(close * (1 + (rnd() - 0.5) * 0.01) * 100) / 100;
    const high = Math.round(Math.max(open, close) * (1 + rnd() * 0.012) * 100) / 100;
    const low = Math.round(Math.min(open, close) * (1 - rnd() * 0.012) * 100) / 100;
    return {
      date: isoDaysAgo(closes.length - 1 - i).slice(0, 10),
      open,
      high,
      low,
      close,
      volume: Math.round(1_000_000 * (0.6 + rnd() * 1.4)),
    };
  });
}

interface StockSeed {
  symbol: string;
  name: string;
  base: number;
  seed: number;
  vol: number;
}

const KR_SEEDS: StockSeed[] = [
  { symbol: "005930", name: "삼성전자", base: 78_600, seed: 11, vol: 0.02 },
  { symbol: "000660", name: "SK하이닉스", base: 196_500, seed: 22, vol: 0.03 },
  { symbol: "373220", name: "LG에너지솔루션", base: 402_000, seed: 33, vol: 0.03 },
  { symbol: "207940", name: "삼성바이오로직스", base: 812_000, seed: 44, vol: 0.02 },
  { symbol: "005380", name: "현대차", base: 243_500, seed: 55, vol: 0.02 },
  { symbol: "035420", name: "NAVER", base: 178_200, seed: 66, vol: 0.025 },
  { symbol: "051910", name: "LG화학", base: 321_000, seed: 77, vol: 0.03 },
  { symbol: "068270", name: "셀트리온", base: 187_400, seed: 88, vol: 0.025 },
];

const US_SEEDS: StockSeed[] = [
  { symbol: "AAPL", name: "애플", base: 232.45, seed: 101, vol: 0.015 },
  { symbol: "MSFT", name: "마이크로소프트", base: 428.9, seed: 202, vol: 0.015 },
  { symbol: "NVDA", name: "엔비디아", base: 121.33, seed: 303, vol: 0.035 },
  { symbol: "AMZN", name: "아마존", base: 186.2, seed: 404, vol: 0.02 },
  { symbol: "GOOGL", name: "알파벳", base: 163.75, seed: 505, vol: 0.02 },
  { symbol: "TSLA", name: "테슬라", base: 254.1, seed: 606, vol: 0.04 },
];

function buildStock(s: StockSeed, isUs: boolean): StockDetail {
  const closes = walk(s.base, 30, s.vol, s.seed);
  const price = closes[closes.length - 1];
  const prev = closes[closes.length - 2];
  const week = closes[closes.length - 8];
  const bars = makeBars(closes, s.seed + 1);
  const round = (v: number) => (isUs ? Math.round(v * 100) / 100 : Math.round(v));
  const high52 = round(Math.max(...closes) * 1.18);
  const low52 = round(Math.min(...closes) * 0.74);
  return {
    symbol: s.symbol,
    name: s.name,
    price: round(price),
    change_pct: Math.round(((price / prev - 1) * 100) * 100) / 100,
    spark7: closes.slice(-7).map(round),
    week_change_pct: Math.round(((price / week - 1) * 100) * 100) / 100,
    volume: bars[bars.length - 1].volume,
    volume_vs_avg:
      Math.round(
        (bars[bars.length - 1].volume /
          (bars.reduce((a, b) => a + b.volume, 0) / bars.length)) * 100
      ) / 100,
    high_52w: high52,
    low_52w: low52,
    stale: false,
    kind: isUs ? "US" : "KR",
    currency: isUs ? "USD" : "KRW",
    bars30: bars.map((b) => ({ ...b, open: round(b.open), high: round(b.high), low: round(b.low), close: round(b.close) })),
  };
}

export const MOCK_STOCKS: Record<"KR" | "US", StockDetail[]> = {
  KR: KR_SEEDS.map((s) => buildStock(s, false)),
  US: US_SEEDS.map((s) => buildStock(s, true)),
};

/** 목록 응답은 상세 전용 필드(kind/currency/bars30)를 빼고 내려온다(SPEC §4.2). */
export function toListItem(d: StockDetail): Stock {
  const { kind: _kind, currency: _currency, bars30: _bars, ...rest } = d;
  return rest;
}

function equitySeries(seed: number, start: number, n: number): EquityPoint[] {
  const vals = walk(start, n, 0.008, seed);
  return vals.map((equity, i) => ({
    ts: isoDaysAgo(n - 1 - i),
    equity: Math.round(equity),
  }));
}

export const MOCK_EQUITY: Record<number, EquityPoint[]> = {
  1: equitySeries(7, 100_000_000, 30),
  2: equitySeries(9, 70_310, 30),
};

/** 목 초기 상태. 목 서버가 이걸 깊은 복사해 써서, 테스트마다 상태가 새로 시작된다. */
export interface MockState {
  me: Me | null;
  accounts: AccountSummary[];
  positions: Position[];
  trades: Trade[];
  nextTradeId: number;
  nextRuleId: number;
}

export function initialMockState(): MockState {
  const kr = MOCK_STOCKS.KR;
  const samsung = kr[0];
  const hynix = kr[1];

  const positions: Position[] = [
    {
      id: 1,
      account_id: 1,
      symbol: samsung.symbol,
      name: samsung.name,
      quantity: 120,
      avg_price: 74_180,
      current_price: samsung.price,
      market_value: samsung.price * 120,
      cost_basis: 74_180 * 120,
      unrealized_pnl: (samsung.price - 74_180) * 120,
      unrealized_pnl_pct: Math.round((samsung.price / 74_180 - 1) * 10000) / 100,
      opened_at: isoDaysAgo(18),
      stale: false,
      sell_rule: {
        id: 1,
        position_id: 1,
        stop_loss_pct: -5,
        take_profit_pct: 15,
        stop_price: Math.round(74_180 * 0.95),
        take_price: Math.round(74_180 * 1.15),
        quantity: 120,
        active: true,
        created_at: isoDaysAgo(18),
        updated_at: isoDaysAgo(3),
      },
    },
    {
      id: 2,
      account_id: 1,
      symbol: hynix.symbol,
      name: hynix.name,
      quantity: 15,
      avg_price: 203_900,
      current_price: hynix.price,
      market_value: hynix.price * 15,
      cost_basis: 203_900 * 15,
      unrealized_pnl: (hynix.price - 203_900) * 15,
      unrealized_pnl_pct: Math.round((hynix.price / 203_900 - 1) * 10000) / 100,
      opened_at: isoDaysAgo(6),
      stale: false,
      sell_rule: null,
    },
  ];

  const krMarketValue = positions.reduce((a, p) => a + p.market_value, 0);
  const krCash = 100_000_000 - positions.reduce((a, p) => a + p.cost_basis, 0);

  const accounts: AccountSummary[] = [
    {
      id: 1,
      kind: "KR",
      currency: "KRW",
      cash: krCash,
      market_value: krMarketValue,
      total_asset: krCash + krMarketValue,
      seed: 100_000_000,
      pnl: krCash + krMarketValue - 100_000_000,
      return_pct: Math.round(((krCash + krMarketValue) / 100_000_000 - 1) * 10000) / 100,
      position_count: positions.length,
      equity_spark: MOCK_EQUITY[1].map((p) => p.equity),
      stale: false,
    },
    {
      id: 2,
      kind: "US",
      currency: "USD",
      cash: 70_310.55,
      market_value: 0,
      total_asset: 70_310.55,
      seed: 70_310.55,
      pnl: 0,
      return_pct: 0,
      position_count: 0,
      equity_spark: MOCK_EQUITY[2].map((p) => p.equity),
      stale: false,
    },
  ];

  const trades: Trade[] = [
    {
      id: 3,
      account_id: 1,
      symbol: hynix.symbol,
      name: hynix.name,
      side: "BUY",
      quantity: 15,
      price: 203_869,
      fee: 459,
      tax: 0,
      gross: 3_058_035,
      net: -3_058_494,
      realized_pnl: null,
      reason: "MANUAL",
      sell_rule_id: null,
      trigger_price: null,
      executed_at: isoDaysAgo(6),
    },
    {
      id: 2,
      account_id: 1,
      symbol: "035420",
      name: "NAVER",
      side: "SELL",
      quantity: 10,
      price: 191_200,
      fee: 287,
      tax: 2_868,
      gross: 1_912_000,
      net: 1_908_845,
      realized_pnl: 118_445,
      reason: "AUTO_TAKE_PROFIT",
      sell_rule_id: 9,
      trigger_price: 190_000,
      executed_at: isoDaysAgo(9),
    },
    {
      id: 1,
      account_id: 1,
      symbol: samsung.symbol,
      name: samsung.name,
      side: "BUY",
      quantity: 120,
      price: 74_169,
      fee: 1_335,
      tax: 0,
      gross: 8_900_280,
      net: -8_901_615,
      realized_pnl: null,
      reason: "MANUAL",
      sell_rule_id: null,
      trigger_price: null,
      executed_at: isoDaysAgo(18),
    },
  ];

  return {
    me: MOCK_ME,
    accounts: JSON.parse(JSON.stringify(accounts)) as AccountSummary[],
    positions: JSON.parse(JSON.stringify(positions)) as Position[],
    trades: JSON.parse(JSON.stringify(trades)) as Trade[],
    nextTradeId: 4,
    nextRuleId: 10,
  };
}

// ── 랭킹 목 데이터 ───────────────────────────────────────────────────────
/** 서버가 붙여 주는 값(rank·is_me)은 목 서버가 계산하므로 여기서는 뺀다. */
export type RankingSeed = Omit<RankingRow, "rank" | "is_me">;

/**
 * 나 말고 다른 참가자들. 일간 수익률을 넓게 흩어 두어 발산형 막대와 시상대가
 * 실제로 어떻게 보이는지 확인할 수 있게 했다.
 *
 * 의도한 배치: '전체' 탭에서 내 두 캐릭터는 6·7위 → 표 아래 '내 순위'가 뜨고,
 * '해외' 탭에서는 내 캐릭터가 3위 → 시상대 위에서 강조되는 경우까지 덮는다.
 */
export const MOCK_RIVALS: RankingSeed[] = [
  {
    account_id: 101, nickname: "불꽃개미", kind: "KR", currency: "KRW",
    daily_return_pct: 9.24, daily_pnl: 8_120_000,
    total_return_pct: 12.4, total_asset: 112_400_000, position_count: 5, stale: false,
  },
  {
    account_id: 201, nickname: "달러사랑", kind: "US", currency: "USD",
    daily_return_pct: 7.43, daily_pnl: 4_120.55,
    total_return_pct: 9.8, total_asset: 77_200.4, position_count: 4, stale: false,
  },
  {
    account_id: 102, nickname: "느긋한곰", kind: "KR", currency: "KRW",
    daily_return_pct: 5.61, daily_pnl: 4_980_000,
    total_return_pct: 2.1, total_asset: 102_100_000, position_count: 3, stale: false,
  },
  {
    account_id: 202, nickname: "밤에깨는사람", kind: "US", currency: "USD",
    daily_return_pct: 3.32, daily_pnl: 2_180.1,
    total_return_pct: 3.1, total_asset: 72_490.2, position_count: 2, stale: false,
  },
  {
    account_id: 103, nickname: "점심시간매수", kind: "KR", currency: "KRW",
    daily_return_pct: 2.87, daily_pnl: 2_410_000,
    total_return_pct: -1.6, total_asset: 98_400_000, position_count: 2, stale: false,
  },
  {
    account_id: 203, nickname: "커피값벌기", kind: "US", currency: "USD",
    daily_return_pct: -1.85, daily_pnl: -1_290.75,
    total_return_pct: -2.4, total_asset: 68_620.9, position_count: 3, stale: false,
  },
  {
    account_id: 104, nickname: "존버중", kind: "KR", currency: "KRW",
    daily_return_pct: -4.12, daily_pnl: -3_760_000,
    total_return_pct: -8.9, total_asset: 91_100_000, position_count: 6, stale: true,
  },
];

/**
 * 내 캐릭터의 **어제 마감 자산**(일간 수익률의 분모). 백엔드는 마감 스냅샷에서
 * 가져오지만, 목에서는 초기 총자산에서 역산해 고정한다 — 그래야 처음 화면이
 * 국내 +0.62% / 해외 −0.85% 로 항상 같게 나와 눈으로 비교할 수 있다.
 * (매수·매도로 총자산이 바뀌면 일간 수익률도 따라 움직인다.)
 */
const INITIAL_FOR_BASE = initialMockState();
export const MOCK_DAILY_BASE: Record<number, number> = {
  1: Math.round(INITIAL_FOR_BASE.accounts[0].total_asset / 1.0062),
  2: Math.round((INITIAL_FOR_BASE.accounts[1].total_asset / 0.9915) * 100) / 100,
};
