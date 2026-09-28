// 매도벽 설정(SPEC §8.1 #6). 슬라이더로 퍼센트를 잡으면 **발동가를 즉시 금액으로**
// 환산해 보여준다 — "-5%"만으로는 초보가 얼마인지 감을 못 잡기 때문이다.
import { useId, useMemo, useState } from "react";
import type { AccountSummary, Position, SellRuleRequest } from "../types";
import { SellWallGauge } from "./SellWallGauge";
import { formatMoney, formatSignedMoney, signClass } from "./format";
import { estimateRealizedPnl } from "./money";
import { STOP_LABEL, TAKE_LABEL, triggerPrice, validateSellRule } from "./sellwall";

export interface SellWallEditorProps {
  account: AccountSummary;
  position: Position;
  onSave: (rule: SellRuleRequest) => Promise<void>;
  onRemove: () => Promise<void>;
  onClose: () => void;
}

export function SellWallEditor({
  account,
  position,
  onSave,
  onRemove,
  onClose,
}: SellWallEditorProps) {
  const existing = position.sell_rule;
  // 아직 규칙이 없으면 -5% / +15% 를 켜둔 채로 시작한다. 빈 화면에서 숫자를 처음부터
  // 짜내게 하는 것보다, 흔한 기준을 보여주고 고치게 하는 편이 초보에게 쉽다.
  const [stopOn, setStopOn] = useState(existing ? existing.stop_loss_pct != null : true);
  const [takeOn, setTakeOn] = useState(existing ? existing.take_profit_pct != null : true);
  const [stopPct, setStopPct] = useState(existing?.stop_loss_pct ?? -5);
  const [takePct, setTakePct] = useState(existing?.take_profit_pct ?? 15);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 체크박스를 <label> 로 감싸면 jsdom 에서 클릭이 두 번 전달돼 토글이 상쇄된다.
  // id/htmlFor 로 묶어 그 함정을 피한다.
  const stopId = useId();
  const takeId = useId();

  const currency = account.currency;
  const stopPrice = useMemo(
    () => (stopOn ? triggerPrice(position.avg_price, stopPct, currency) : null),
    [stopOn, stopPct, position.avg_price, currency]
  );
  const takePrice = useMemo(
    () => (takeOn ? triggerPrice(position.avg_price, takePct, currency) : null),
    [takeOn, takePct, position.avg_price, currency]
  );

  // 발동되면 실제로 얼마를 벌거나 잃는지까지 미리 보여준다(수수료·세금 포함).
  const stopPnl =
    stopPrice === null
      ? null
      : estimateRealizedPnl(stopPrice, position.avg_price, position.quantity, account.kind, currency);
  const takePnl =
    takePrice === null
      ? null
      : estimateRealizedPnl(takePrice, position.avg_price, position.quantity, account.kind, currency);

  const invalid = validateSellRule(stopOn ? stopPct : null, takeOn ? takePct : null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave({
        stop_loss_pct: stopOn ? stopPct : null,
        take_profit_pct: takeOn ? takePct : null,
        quantity: position.quantity,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "저장하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await onRemove();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "해제하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="자동으로 팔 기준 정하기"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="modal__title">자동으로 팔 기준 정하기</h2>
        <p className="modal__desc">
          {position.name} · 평균 산 가격 {formatMoney(position.avg_price, currency)} 기준으로
          계산합니다. 정해두면 장이 열린 동안 1분마다 확인해 조건에 닿으면 자동으로 팝니다.
        </p>

        <div style={{ margin: "14px 0" }}>
          <SellWallGauge
            avgPrice={position.avg_price}
            currentPrice={position.current_price}
            stopPrice={stopPrice}
            takePrice={takePrice}
            currency={currency}
          />
        </div>

        <div className="slider-block">
          <div className="row" style={{ gap: 6 }}>
            <input
              id={stopId}
              type="checkbox"
              checked={stopOn}
              onChange={(e) => setStopOn(e.target.checked)}
              aria-label={STOP_LABEL}
            />
            <label className="slider-block__title" htmlFor={stopId}>
              {STOP_LABEL}
            </label>
          </div>
          <p className="slider-block__desc">더 크게 잃기 전에 멈추고 싶을 때 씁니다.</p>
          <div className="slider-row">
            <input
              className="slider"
              type="range"
              min={-50}
              max={-1}
              step={1}
              value={stopPct}
              disabled={!stopOn}
              aria-label={`${STOP_LABEL} 퍼센트`}
              onChange={(e) => setStopPct(Number(e.target.value))}
            />
            <span className="slider-row__value">{stopPct}%</span>
          </div>
          {stopPrice !== null && (
            <p className="slider-block__price" data-testid="stop-price">
              1주 {formatMoney(stopPrice, currency)}에 닿으면 {position.quantity.toLocaleString("ko-KR")}주를 팝니다 ·{" "}
              <span className={signClass(stopPnl ?? 0)}>
                그때 손익 {formatSignedMoney(stopPnl ?? 0, currency)}
              </span>
            </p>
          )}
        </div>

        <div className="slider-block">
          <div className="row" style={{ gap: 6 }}>
            <input
              id={takeId}
              type="checkbox"
              checked={takeOn}
              onChange={(e) => setTakeOn(e.target.checked)}
              aria-label={TAKE_LABEL}
            />
            <label className="slider-block__title" htmlFor={takeId}>
              {TAKE_LABEL}
            </label>
          </div>
          <p className="slider-block__desc">목표만큼 올랐을 때 욕심내지 않고 챙기고 싶을 때 씁니다.</p>
          <div className="slider-row">
            <input
              className="slider"
              type="range"
              min={1}
              max={100}
              step={1}
              value={takePct}
              disabled={!takeOn}
              aria-label={`${TAKE_LABEL} 퍼센트`}
              onChange={(e) => setTakePct(Number(e.target.value))}
            />
            <span className="slider-row__value">+{takePct}%</span>
          </div>
          {takePrice !== null && (
            <p className="slider-block__price" data-testid="take-price">
              1주 {formatMoney(takePrice, currency)}에 닿으면 {position.quantity.toLocaleString("ko-KR")}주를 팝니다 ·{" "}
              <span className={signClass(takePnl ?? 0)}>
                그때 손익 {formatSignedMoney(takePnl ?? 0, currency)}
              </span>
            </p>
          )}
        </div>

        <p className="modal__warn">
          실제로는 정한 가격에 딱 맞춰 팔리지 않을 수 있습니다. 조건에 닿은 것을 확인한
          순간의 가격으로 팔리며, 그 차이는 거래 내역에 그대로 남습니다.
        </p>

        {invalid && <p className="form-error">{invalid}</p>}
        {error && <p className="form-error">{error}</p>}

        <div className="modal__actions">
          {existing && (
            <button
              type="button"
              className="btn btn--ghost"
              disabled={busy}
              onClick={remove}
              style={{ marginRight: "auto" }}
            >
              기준 없애기
            </button>
          )}
          <button type="button" className="btn btn--outline" onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy || invalid !== null}
            onClick={save}
          >
            저장
          </button>
        </div>
      </div>
    </div>
  );
}

export default SellWallEditor;
