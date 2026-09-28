// 보유 종목 카드(SPEC §8.1 #5). 평단·현재가·평가손익 + 매도벽 그림 + 행동 버튼.
import type { AccountSummary, Position } from "../types";
import { SellWallGauge } from "./SellWallGauge";
import { formatMoney, moneyWithPct, signClass } from "./format";

export interface PositionCardProps {
  account: AccountSummary;
  position: Position;
  onSell: () => void;
  onEditWall: () => void;
}

export function PositionCard({ account, position, onSell, onEditWall }: PositionCardProps) {
  const c = account.currency;
  const rule = position.sell_rule;

  return (
    <div className="card pos">
      <div className="pos__head">
        <span className="pos__name">{position.name}</span>
        <span className="pos__qty">
          {position.symbol} · {position.quantity.toLocaleString("ko-KR")}주
        </span>
        {position.stale && <span className="stale-badge">시세 지연</span>}
      </div>

      <dl className="pos__figures">
        <div className="pos__fig">
          <dt>평균 산 가격</dt>
          <dd>{formatMoney(position.avg_price, c)}</dd>
        </div>
        <div className="pos__fig">
          <dt>지금 가격</dt>
          <dd>{formatMoney(position.current_price, c)}</dd>
        </div>
        <div className="pos__fig">
          <dt>지금 가치</dt>
          <dd>{formatMoney(position.market_value, c)}</dd>
        </div>
        <div className="pos__fig">
          <dt>아직 팔지 않은 손익</dt>
          <dd className={signClass(position.unrealized_pnl)} data-testid="pos-pnl">
            {moneyWithPct(position.unrealized_pnl, position.unrealized_pnl_pct, c)}
          </dd>
        </div>
      </dl>

      <SellWallGauge
        avgPrice={position.avg_price}
        currentPrice={position.current_price}
        stopPrice={rule?.active ? rule.stop_price : null}
        takePrice={rule?.active ? rule.take_price : null}
        currency={c}
      />

      <div className="pos__actions">
        <button type="button" className="btn btn--sell" onClick={onSell}>
          지금 팔기
        </button>
        <button type="button" className="btn btn--outline" onClick={onEditWall}>
          {rule?.active ? "자동 매도 기준 바꾸기" : "자동으로 팔 기준 정하기"}
        </button>
      </div>
    </div>
  );
}

export default PositionCard;
