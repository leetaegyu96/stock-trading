// 매도벽 시각화(SPEC §8.2). 목표 그림:
//
//   이만큼 떨어지면 팔기 9,500 ┃━━━━━●━━━━━━┃ 이만큼 오르면 팔기 11,500
//                            평단 10,000 · 현재 10,240 (+2.4%)
//
// 위치 계산은 sellwall.ts(순수 함수)가 하고, 여기서는 그리기만 한다.
import type { Currency } from "../types";
import { formatMoney, signClass, signedPct } from "./format";
import { STOP_LABEL, TAKE_LABEL, sellWallGauge } from "./sellwall";

export interface SellWallGaugeProps {
  avgPrice: number;
  currentPrice: number;
  stopPrice: number | null;
  takePrice: number | null;
  currency: Currency;
}

export function SellWallGauge({
  avgPrice,
  currentPrice,
  stopPrice,
  takePrice,
  currency,
}: SellWallGaugeProps) {
  const g = sellWallGauge({ avgPrice, currentPrice, stopPrice, takePrice });
  const changePct = avgPrice > 0 ? (currentPrice / avgPrice - 1) * 100 : 0;

  if (stopPrice === null && takePrice === null) {
    return (
      <p className="wall__none">
        자동으로 팔 기준이 없습니다. 지금은 직접 팔지 않는 한 계속 가지고 있습니다.
      </p>
    );
  }

  return (
    <div className="wall">
      <div
        className="wall__track"
        role="img"
        aria-label={
          `평균 산 가격 ${formatMoney(avgPrice, currency)}, ` +
          `현재 가격 ${formatMoney(currentPrice, currency)} (${signedPct(changePct, 1)})` +
          (stopPrice !== null ? `, 떨어지면 팔 가격 ${formatMoney(stopPrice, currency)}` : "") +
          (takePrice !== null ? `, 오르면 팔 가격 ${formatMoney(takePrice, currency)}` : "")
        }
      >
        {g.stopPos !== null && (
          <>
            <span className="wall__zone wall__zone--stop" style={{ width: `${g.stopPos}%` }} />
            <span className="wall__edge wall__edge--stop" style={{ left: `${g.stopPos}%` }} />
          </>
        )}
        {g.takePos !== null && (
          <>
            <span className="wall__zone wall__zone--take" style={{ width: `${100 - g.takePos}%` }} />
            <span className="wall__edge wall__edge--take" style={{ left: `${g.takePos}%` }} />
          </>
        )}
        <span className="wall__avg" style={{ left: `${g.avgPos}%` }} />
        <span className="wall__now" style={{ left: `${g.currentPos}%` }} data-testid="wall-now" />
      </div>

      <div className="wall__legend">
        <span>
          {stopPrice !== null ? (
            <>
              {STOP_LABEL} <b>{formatMoney(stopPrice, currency)}</b>
            </>
          ) : (
            <span className="muted">떨어지면 팔 기준 없음</span>
          )}
        </span>
        <span>
          {takePrice !== null ? (
            <>
              {TAKE_LABEL} <b>{formatMoney(takePrice, currency)}</b>
            </>
          ) : (
            <span className="muted">오르면 팔 기준 없음</span>
          )}
        </span>
      </div>

      <p className="wall__caption">
        평균 산 가격 {formatMoney(avgPrice, currency)} · 지금 {formatMoney(currentPrice, currency)}{" "}
        <span className={signClass(changePct)}>({signedPct(changePct, 1)})</span>
      </p>

      {g.triggered && (
        <p className="wall__fired">
          지금 가격이 {g.triggered === "stop" ? "떨어지면 팔 기준" : "오르면 팔 기준"}에
          닿았습니다. 다음 감시(장중 1분 간격)에서 자동으로 팔립니다.
        </p>
      )}
    </div>
  );
}

export default SellWallGauge;
