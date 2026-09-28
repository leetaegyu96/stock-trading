// 화면 4: 종목 상세 — 30일 차트 + 사실 지표 + 매수 패널.
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import * as api from "../api";
import { BuyPanel } from "../components/BuyPanel";
import { PriceChart } from "../components/PriceChart";
import { RangeGauge } from "../components/RangeGauge";
import {
  changeArrow,
  compactNumber,
  formatMoney,
  signClass,
  signedPct,
  volumeText,
} from "../components/format";
import { useSession } from "../session";
import type { StockDetail as StockDetailType } from "../types";

export function StockDetail() {
  const { accountId, symbol } = useParams();
  const navigate = useNavigate();
  const { accounts, refresh } = useSession();
  const account = accounts.find((a) => a.id === Number(accountId)) ?? null;

  const [stock, setStock] = useState<StockDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    if (!account || !symbol) return;
    let cancelled = false;
    api
      .getStock(account.kind, symbol)
      .then((d) => !cancelled && setStock(d))
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "종목을 불러오지 못했습니다.");
      });
    return () => {
      cancelled = true;
    };
  }, [account, symbol]);

  const handleBuy = useCallback(
    async (quantity: number) => {
      if (!account || !symbol) return;
      const result = await api.buy(account.id, { symbol, quantity });
      // 체결 직후 계좌 요약을 다시 읽어 현금·수익률이 즉시 맞게 보이도록 한다.
      await refresh();
      setDone(
        `${result.trade.quantity.toLocaleString("ko-KR")}주를 ` +
          `${formatMoney(result.trade.price, account.currency)}에 샀습니다.`
      );
    },
    [account, symbol, refresh]
  );

  if (!account) return <div className="page-state">캐릭터를 찾을 수 없습니다.</div>;
  if (error) return <div className="page-state page-state--error">{error}</div>;
  if (!stock) return <div className="page-state">불러오는 중…</div>;

  const c = account.currency;

  return (
    <div>
      <button type="button" className="btn btn--ghost" onClick={() => navigate(-1)}>
        ← 목록으로
      </button>

      <div className="page-head" style={{ marginTop: 8 }}>
        <h1 className="page-title">{stock.name}</h1>
        <span className="muted small">{stock.symbol}</span>
        {stock.stale && <span className="stale-badge">시세 지연</span>}
      </div>
      <p className="page-sub">
        <span className="num" style={{ fontSize: 22, fontWeight: 800, color: "var(--color-text)" }}>
          {formatMoney(stock.price, c)}
        </span>{" "}
        <span className={signClass(stock.change_pct)}>
          {changeArrow(stock.change_pct)} 어제보다 {signedPct(stock.change_pct, 2)}
        </span>
      </p>

      <div className="grid-2">
        <div>
          <div className="card">
            <h3 className="card__title">최근 30일 움직임</h3>
            <PriceChart bars={stock.bars30} currency={c} />
          </div>

          <div className="card">
            <h3 className="card__title">알아두면 좋은 사실</h3>
            <ul className="summary">
              <li>
                <span className="summary__k">최근 7일</span>
                <span className={`summary__v ${signClass(stock.week_change_pct)}`}>
                  {signedPct(stock.week_change_pct, 1)}
                </span>
              </li>
              <li>
                <span className="summary__k">오늘 거래량</span>
                <span className="summary__v">
                  {compactNumber(stock.volume)}주 · {volumeText(stock.volume_vs_avg)}
                </span>
              </li>
              <li>
                <span className="summary__k">1년 중 지금 위치</span>
                <span className="summary__v" style={{ flex: "0 0 160px" }}>
                  <RangeGauge
                    low={stock.low_52w}
                    high={stock.high_52w}
                    current={stock.price}
                    currency={c}
                    compact
                  />
                </span>
              </li>
              <li>
                <span className="summary__k">1년 최저 ~ 최고</span>
                <span className="summary__v">
                  {formatMoney(stock.low_52w, c)} ~ {formatMoney(stock.high_52w, c)}
                </span>
              </li>
            </ul>
            <p className="small muted" style={{ marginTop: 10 }}>
              이 숫자들은 사실을 그대로 보여줄 뿐, 사라거나 팔라는 뜻이 아닙니다.
            </p>
          </div>
        </div>

        <div>
          {done && (
            <div className="card" style={{ borderColor: "var(--color-up)" }}>
              <p style={{ margin: 0, fontWeight: 700 }}>{done}</p>
              <button
                type="button"
                className="btn btn--outline"
                style={{ marginTop: 10 }}
                onClick={() => navigate(`/accounts/${account.id}/holdings`)}
              >
                내 주식에서 자동 매도 기준 정하기
              </button>
            </div>
          )}
          <BuyPanel account={account} stock={stock} onBuy={handleBuy} />
        </div>
      </div>
    </div>
  );
}

export default StockDetail;
