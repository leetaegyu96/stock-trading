// 화면 2: 홈 — 캐릭터 2장 카드(총자산·수익률·자산곡선 스파크라인).
import { useNavigate } from "react-router-dom";
import { Sparkline } from "../components/Sparkline";
import { EmptyState } from "../components/EmptyState";
import { formatMoney, kindLabel, moneyWithPct, signClass } from "../components/format";
import { useSession } from "../session";
import type { AccountSummary } from "../types";

function CharacterCard({ account, onOpen }: { account: AccountSummary; onOpen: () => void }) {
  const c = account.currency;
  return (
    <button type="button" className="char" onClick={onOpen}>
      <div className="char__head">
        <span className="char__kind">{kindLabel(account.kind)}</span>
        <span className={`chip chip--${signClass(account.return_pct)}`}>
          {account.return_pct >= 0 ? "+" : ""}
          {account.return_pct.toFixed(2)}%
        </span>
      </div>

      <div>
        <div className="char__label">지금 가진 돈 전부</div>
        <div className="char__total num">{formatMoney(account.total_asset, c)}</div>
        <div className={`char__pnl ${signClass(account.pnl)}`}>
          처음보다 {moneyWithPct(account.pnl, account.return_pct, c)}
        </div>
      </div>

      <Sparkline
        points={account.equity_spark}
        height={48}
        label={`${kindLabel(account.kind)} 캐릭터 자산 추이`}
      />

      <div className="char__foot">
        <span>
          현금 <b className="num">{formatMoney(account.cash, c)}</b>
        </span>
        <span>
          주식 <b className="num">{formatMoney(account.market_value, c)}</b>
        </span>
        <span>{account.position_count}개 종목</span>
      </div>
    </button>
  );
}

export function Home() {
  const { accounts, me } = useSession();
  const navigate = useNavigate();

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">{me ? `${me.nickname}님의 캐릭터` : "내 캐릭터"}</h1>
      </div>
      <p className="page-sub">
        캐릭터를 골라 종목을 사고, 자동으로 팔 기준을 정해두세요. 진짜 돈은 오가지 않습니다.
      </p>

      {accounts.length === 0 ? (
        <EmptyState
          title="캐릭터를 불러오는 중이거나, 아직 만들어지지 않았습니다"
          desc="가입하면 국내·해외 캐릭터가 각각 1억원으로 자동 생성됩니다."
        />
      ) : (
        <div className="grid-2">
          {accounts.map((a) => (
            <CharacterCard
              key={a.id}
              account={a}
              onOpen={() => navigate(`/accounts/${a.id}/stocks`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default Home;
