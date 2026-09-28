// 화면 7: 거래 내역. 산 것 / 판 것 / 자동으로 팔린 것 필터.
// 자동매도는 **왜 팔렸는지(발동선)와 실제 체결가를 나란히** 보여준다(SPEC §6.2).
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import * as api from "../api";
import { EmptyState } from "../components/EmptyState";
import {
  formatMoney,
  formatSignedMoney,
  kindLabel,
  reasonInfo,
  shortDateTime,
  sideLabel,
  signClass,
} from "../components/format";
import { useSession } from "../session";
import type { Trade } from "../types";

type Filter = "all" | "buy" | "sell" | "auto";

const FILTERS: Array<{ key: Filter; label: string }> = [
  { key: "all", label: "전체" },
  { key: "buy", label: "산 것" },
  { key: "sell", label: "직접 판 것" },
  { key: "auto", label: "자동으로 팔린 것" },
];

function matches(trade: Trade, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "buy") return trade.side === "BUY";
  if (filter === "sell") return trade.side === "SELL" && trade.reason === "MANUAL";
  return trade.reason !== "MANUAL";
}

export function Trades() {
  const { accountId } = useParams();
  const navigate = useNavigate();
  const { accounts } = useSession();
  const account = accounts.find((a) => a.id === Number(accountId)) ?? null;

  const [trades, setTrades] = useState<Trade[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const load = useCallback(async () => {
    if (!account) return;
    try {
      const page = await api.getTrades(account.id, { limit: 200 });
      setTrades(page.items);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "거래 내역을 불러오지 못했습니다.");
    }
  }, [account]);

  useEffect(() => {
    void load();
  }, [load]);

  const shown = useMemo(() => (trades ?? []).filter((t) => matches(t, filter)), [trades, filter]);

  if (!account) return <div className="page-state">캐릭터를 찾을 수 없습니다.</div>;
  const c = account.currency;

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">{kindLabel(account.kind)} 거래 내역</h1>
      </div>
      <p className="page-sub">사고 판 기록은 지워지지 않습니다. 자동으로 팔린 건 이유까지 남습니다.</p>

      <div className="filters">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            className={`filter-btn${filter === f.key ? " filter-btn--on" : ""}`}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && <div className="page-state page-state--error">{error}</div>}
      {!error && trades === null && <div className="page-state">불러오는 중…</div>}

      {trades !== null && shown.length === 0 && (
        <EmptyState
          title="해당하는 거래가 없습니다"
          desc="아직 아무것도 사지 않았다면, 종목을 골라 첫 거래를 시작해보세요."
          action={
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => navigate(`/accounts/${account.id}/stocks`)}
            >
              종목 찾으러 가기
            </button>
          }
        />
      )}

      {shown.length > 0 && (
        <div className="card table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>시각</th>
                <th>종목</th>
                <th>무엇을</th>
                <th className="table__num">수량</th>
                <th className="table__num">체결가</th>
                <th className="table__num">수수료·세금</th>
                <th className="table__num">현금 증감</th>
                <th className="table__num">확정 손익</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((t) => {
                const info = reasonInfo(t.reason);
                return (
                  <tr key={t.id} style={{ cursor: "default" }}>
                    <td className="small muted">{shortDateTime(t.executed_at)}</td>
                    <td>
                      <strong>{t.name}</strong>
                      <div className="stock__code">{t.symbol}</div>
                    </td>
                    <td>
                      <span className={`chip chip--${info.kind}`}>
                        {sideLabel(t.side)} · {info.label}
                      </span>
                      {t.reason !== "MANUAL" && t.trigger_price !== null && (
                        <div className="trade-why">
                          정해둔 {formatMoney(t.trigger_price, c)}에 닿아서 팔렸고, 실제로는{" "}
                          {formatMoney(t.price, c)}에 팔렸습니다
                          {t.trigger_price !== t.price && (
                            <>
                              {" "}
                              (차이 {formatSignedMoney(t.price - t.trigger_price, c)})
                            </>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="table__num">{t.quantity.toLocaleString("ko-KR")}주</td>
                    <td className="table__num">{formatMoney(t.price, c)}</td>
                    <td className="table__num">{formatMoney(t.fee + t.tax, c)}</td>
                    <td className={`table__num ${signClass(t.net)}`}>
                      {formatSignedMoney(t.net, c)}
                    </td>
                    <td className={`table__num ${signClass(t.realized_pnl ?? 0)}`}>
                      {t.realized_pnl === null ? "—" : formatSignedMoney(t.realized_pnl, c)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default Trades;
