// 화면 3: 종목 탐색(매수 진입점). 카드/표 토글 + 이름·코드 검색.
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import * as api from "../api";
import { EmptyState } from "../components/EmptyState";
import { StockList, type StockListView } from "../components/StockList";
import { formatMoney, kindLabel } from "../components/format";
import { useSession } from "../session";
import type { Stock } from "../types";

export function Explore() {
  const { accountId } = useParams();
  const navigate = useNavigate();
  const { accounts } = useSession();
  const account = accounts.find((a) => a.id === Number(accountId)) ?? null;

  const [stocks, setStocks] = useState<Stock[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<StockListView>("card");
  const [q, setQ] = useState("");

  useEffect(() => {
    if (!account) return;
    let cancelled = false;
    api
      .getStocks(account.kind)
      .then((data) => !cancelled && setStocks(data))
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "종목을 불러오지 못했습니다.");
      });
    return () => {
      cancelled = true;
    };
  }, [account?.kind, account]);

  const filtered = useMemo(() => {
    if (!stocks) return [];
    const key = q.trim().toLowerCase();
    if (!key) return stocks;
    return stocks.filter(
      (s) => s.name.toLowerCase().includes(key) || s.symbol.toLowerCase().includes(key)
    );
  }, [stocks, q]);

  if (!account) return <div className="page-state">캐릭터를 찾을 수 없습니다.</div>;

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">{kindLabel(account.kind)} 종목 찾기</h1>
        <span className="muted small">
          쓸 수 있는 현금 {formatMoney(account.cash, account.currency)}
        </span>
      </div>
      <p className="page-sub">
        추천 종목은 없습니다. 가격·최근 흐름·거래량을 보고 직접 고르세요.
      </p>

      <div className="toolbar">
        <input
          className="input toolbar__grow"
          type="search"
          placeholder="종목 이름이나 코드로 찾기"
          aria-label="종목 검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button
          type="button"
          className={`filter-btn${view === "card" ? " filter-btn--on" : ""}`}
          onClick={() => setView("card")}
        >
          카드
        </button>
        <button
          type="button"
          className={`filter-btn${view === "table" ? " filter-btn--on" : ""}`}
          onClick={() => setView("table")}
        >
          표
        </button>
      </div>

      {error && <div className="page-state page-state--error">{error}</div>}
      {!error && stocks === null && <div className="page-state">불러오는 중…</div>}
      {stocks !== null && filtered.length === 0 && (
        <EmptyState
          title="찾는 종목이 없습니다"
          desc="검색어를 지우면 전체 목록이 다시 보입니다."
          action={
            <button type="button" className="btn btn--outline" onClick={() => setQ("")}>
              검색어 지우기
            </button>
          }
        />
      )}
      {filtered.length > 0 && (
        <StockList
          stocks={filtered}
          kind={account.kind}
          currency={account.currency}
          view={view}
          onSelect={(symbol) => navigate(`/accounts/${account.id}/stocks/${symbol}`)}
        />
      )}
    </div>
  );
}

export default Explore;
