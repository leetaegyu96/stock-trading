// 종목 탐색 목록(SPEC §8.1 #3). 카드/표 토글.
// **점수·추천은 표시하지 않는다** — 사실(가격·등락·추이·거래량·52주 위치)만 준다.
import type { AccountKind, Currency, Stock } from "../types";
import { RangeGauge } from "./RangeGauge";
import { Sparkline } from "./Sparkline";
import { changeArrow, compactNumber, formatMoney, signClass, signedPct, volumeText } from "./format";

export type StockListView = "card" | "table";

export interface StockListProps {
  stocks: Stock[];
  kind: AccountKind;
  currency: Currency;
  view: StockListView;
  onSelect: (symbol: string) => void;
}

export function StockList({ stocks, currency, view, onSelect }: StockListProps) {
  if (view === "table") {
    return (
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>종목</th>
              <th className="table__num">지금 가격</th>
              <th className="table__num">어제보다</th>
              <th>최근 7일</th>
              <th className="table__num">7일 동안</th>
              <th className="table__num">거래량</th>
              <th>1년 중 위치</th>
            </tr>
          </thead>
          <tbody>
            {stocks.map((s) => (
              <tr key={s.symbol} onClick={() => onSelect(s.symbol)} tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && onSelect(s.symbol)}>
                <td>
                  <strong>{s.name}</strong>{" "}
                  <span className="stock__code">{s.symbol}</span>
                </td>
                <td className="table__num">{formatMoney(s.price, currency)}</td>
                <td className={`table__num ${signClass(s.change_pct)}`}>
                  {changeArrow(s.change_pct)} {signedPct(s.change_pct, 2)}
                </td>
                <td style={{ width: 90 }}>
                  <Sparkline points={s.spark7} height={26} label={`${s.name} 최근 7일 종가 추이`} />
                </td>
                <td className={`table__num ${signClass(s.week_change_pct)}`}>
                  {signedPct(s.week_change_pct, 1)}
                </td>
                <td className="table__num">{volumeText(s.volume_vs_avg)}</td>
                <td style={{ minWidth: 110 }}>
                  <RangeGauge
                    low={s.low_52w}
                    high={s.high_52w}
                    current={s.price}
                    currency={currency}
                    compact
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="stocklist">
      {stocks.map((s) => (
        <button key={s.symbol} type="button" className="stock" onClick={() => onSelect(s.symbol)}>
          <div className="stock__head">
            <span className="stock__name">{s.name}</span>
            <span className="stock__code">{s.symbol}</span>
          </div>
          <div className="row">
            <span className="stock__price num">{formatMoney(s.price, currency)}</span>
            <span className={`chip chip--${signClass(s.change_pct)}`}>
              {changeArrow(s.change_pct)} {signedPct(s.change_pct, 2)}
            </span>
          </div>
          <Sparkline points={s.spark7} height={40} label={`${s.name} 최근 7일 종가 추이`} />
          <div className="stock__facts">
            <span className={signClass(s.week_change_pct)}>
              최근 7일 {signedPct(s.week_change_pct, 1)}
            </span>
            <span>거래량 {volumeText(s.volume_vs_avg)}</span>
            <span>{compactNumber(s.volume)}주</span>
          </div>
          <RangeGauge low={s.low_52w} high={s.high_52w} current={s.price} currency={currency} />
          {s.stale && <span className="stale-badge">시세 지연</span>}
        </button>
      ))}
    </div>
  );
}

export default StockList;
