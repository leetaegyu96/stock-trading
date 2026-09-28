// 화면 5 + 6: 보유 종목 목록(매도벽 시각화 포함)과 매도벽 설정 모달.
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import * as api from "../api";
import { EmptyState } from "../components/EmptyState";
import { PositionCard } from "../components/PositionCard";
import { SellPanel } from "../components/SellPanel";
import { SellWallEditor } from "../components/SellWallEditor";
import { EquityCurve } from "../components/EquityCurve";
import { formatMoney, kindLabel, moneyWithPct, signClass } from "../components/format";
import { useSession } from "../session";
import type { AccountDetail, Position, SellRuleRequest } from "../types";

export function Holdings() {
  const { accountId } = useParams();
  const navigate = useNavigate();
  const { accounts, refresh } = useSession();
  const account = accounts.find((a) => a.id === Number(accountId)) ?? null;

  const [positions, setPositions] = useState<Position[] | null>(null);
  const [detail, setDetail] = useState<AccountDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sellTarget, setSellTarget] = useState<Position | null>(null);
  const [wallTarget, setWallTarget] = useState<Position | null>(null);

  const load = useCallback(async () => {
    if (!account) return;
    try {
      const [pos, det] = await Promise.all([
        api.getPositions(account.id),
        api.getAccount(account.id),
      ]);
      setPositions(pos);
      setDetail(det);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "보유 종목을 불러오지 못했습니다.");
    }
  }, [account]);

  useEffect(() => {
    void load();
  }, [load]);

  const afterChange = useCallback(async () => {
    await Promise.all([load(), refresh()]);
  }, [load, refresh]);

  if (!account) return <div className="page-state">캐릭터를 찾을 수 없습니다.</div>;

  const c = account.currency;

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">{kindLabel(account.kind)} 내 주식</h1>
        <span className="muted small">
          현금 {formatMoney(account.cash, c)} · 주식 {formatMoney(account.market_value, c)}
        </span>
      </div>
      <p className="page-sub">
        전부 합쳐 <b>{formatMoney(account.total_asset, c)}</b> ·{" "}
        <span className={signClass(account.pnl)}>
          처음보다 {moneyWithPct(account.pnl, account.return_pct, c)}
        </span>
      </p>

      {detail && detail.equity_curve.length > 0 && (
        <div className="card">
          <h3 className="card__title">자산 흐름</h3>
          <EquityCurve points={detail.equity_curve} seed={detail.seed} currency={c} />
        </div>
      )}

      {error && <div className="page-state page-state--error">{error}</div>}
      {!error && positions === null && <div className="page-state">불러오는 중…</div>}

      {positions !== null && positions.length === 0 && (
        <EmptyState
          title="아직 가진 주식이 없습니다"
          desc="종목을 하나 골라 사보세요. 산 다음에는 '이만큼 떨어지면 팔기 / 이만큼 오르면 팔기'를 정해둘 수 있습니다."
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

      {positions?.map((p) => (
        <PositionCard
          key={p.id}
          account={account}
          position={p}
          onSell={() => setSellTarget(p)}
          onEditWall={() => setWallTarget(p)}
        />
      ))}

      {sellTarget && (
        <SellPanel
          open
          account={account}
          position={sellTarget}
          onClose={() => setSellTarget(null)}
          onSell={async (quantity) => {
            await api.sell(account.id, { symbol: sellTarget.symbol, quantity });
            await afterChange();
          }}
        />
      )}

      {wallTarget && (
        <SellWallEditor
          account={account}
          position={wallTarget}
          onClose={() => setWallTarget(null)}
          onSave={async (rule: SellRuleRequest) => {
            await api.putSellRule(wallTarget.id, rule);
            await afterChange();
          }}
          onRemove={async () => {
            await api.deleteSellRule(wallTarget.id);
            await afterChange();
          }}
        />
      )}
    </div>
  );
}

export default Holdings;
