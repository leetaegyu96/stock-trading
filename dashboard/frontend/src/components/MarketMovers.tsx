// 오늘의 시장 동향: 시장(국내/해외)별 등락률 상위·하위 종목.
// 데이터는 전체 시장이 아니라 캐릭터들이 추적하는 유니버스 한정.
import type { Dashboard, Mover } from "../types";
import { formatPrice, signClass, signedPct } from "./format";

export interface MarketMoversProps {
  movers: Dashboard["movers"];
}

const MARKET_LABEL: Record<string, string> = { KR: "국내", US: "해외" };

function MoverRow({ mover }: { mover: Mover }) {
  const pct = mover.change_pct * 100;
  return (
    <li className="movers__item">
      <span className="movers__name" title={mover.symbol}>
        {mover.name}
      </span>
      <span className="movers__price">
        {mover.close === null || mover.close === undefined ? "—" : formatPrice(mover.market, mover.close)}
      </span>
      <span className={`chip chip--${signClass(pct)}`}>{signedPct(pct)}</span>
    </li>
  );
}

function MoverGroup({ title, items }: { title: string; items: Mover[] }) {
  return (
    <div className="movers__group">
      <h4 className="movers__group-title">{title}</h4>
      {items.length === 0 ? (
        <p className="movers__empty">데이터 없음</p>
      ) : (
        <ul className="movers__list">
          {items.map((m) => (
            <MoverRow key={`${m.market}:${m.symbol}`} mover={m} />
          ))}
        </ul>
      )}
    </div>
  );
}

export function MarketMovers({ movers }: MarketMoversProps) {
  const marketKeys = Object.keys(movers);

  if (marketKeys.length === 0) {
    return <p className="board__empty">오늘 시장 데이터가 없습니다.</p>;
  }

  return (
    <div className="movers">
      {marketKeys.map((market) => {
        const group = movers[market];
        return (
          <div className="movers__market" key={market}>
            <h3 className="movers__market-title">{MARKET_LABEL[market] ?? market}</h3>
            <div className="movers__cols">
              <MoverGroup title="오늘 많이 오른 종목" items={group.up} />
              <MoverGroup title="오늘 많이 내린 종목" items={group.down} />
            </div>
          </div>
        );
      })}
      <p className="movers__note">* 추적 종목(유니버스) 기준이며 전체 시장 결과가 아니에요.</p>
    </div>
  );
}

export default MarketMovers;
