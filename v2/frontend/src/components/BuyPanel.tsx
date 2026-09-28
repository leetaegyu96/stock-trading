// 매수 패널(SPEC §8.1 #4). 수량을 바꾸면 예상 금액이 즉시 다시 계산되고,
// 잔고를 넘으면 버튼이 잠긴다. 확정 전에는 반드시 요약 모달을 거친다.
import { useMemo, useState } from "react";
import type { AccountSummary, Stock } from "../types";
import { ConfirmModal } from "./ConfirmModal";
import { QuantityStepper } from "./QuantityStepper";
import { formatMoney } from "./format";
import { buyBlockReason, estimateBuy, maxAffordableQuantity } from "./money";

export interface BuyPanelProps {
  account: AccountSummary;
  stock: Stock;
  /** 실제 주문. 페이지가 api.buy 를 물려준다 — 패널 자체는 네트워크를 모른다. */
  onBuy: (quantity: number) => Promise<void>;
}

export function BuyPanel({ account, stock, onBuy }: BuyPanelProps) {
  const [quantity, setQuantity] = useState(1);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const est = useMemo(
    () => estimateBuy(stock.price, quantity, account.kind, account.currency),
    [stock.price, quantity, account.kind, account.currency]
  );
  const maxQty = useMemo(
    () => maxAffordableQuantity(account.cash, stock.price, account.kind, account.currency),
    [account.cash, stock.price, account.kind, account.currency]
  );
  const block = buyBlockReason(quantity, account.cash, stock.price, account.kind, account.currency);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onBuy(quantity);
      setConfirming(false);
      setQuantity(1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "주문을 넣지 못했습니다.");
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h3 className="card__title">사기</h3>

      <div className="row" style={{ marginBottom: 10 }}>
        <QuantityStepper value={quantity} onChange={setQuantity} min={0} label="살 수량" />
        <span className="small muted">주</span>
        <button
          type="button"
          className="btn btn--outline"
          disabled={maxQty <= 0}
          onClick={() => setQuantity(maxQty)}
        >
          가진 현금 전부 ({maxQty.toLocaleString("ko-KR")}주)
        </button>
      </div>

      <ul className="summary">
        <li>
          <span className="summary__k">지금 가격</span>
          <span className="summary__v">{formatMoney(stock.price, account.currency)}</span>
        </li>
        <li>
          <span className="summary__k">주식값 ({quantity.toLocaleString("ko-KR")}주)</span>
          <span className="summary__v">{formatMoney(est.gross, account.currency)}</span>
        </li>
        <li>
          <span className="summary__k">수수료</span>
          <span className="summary__v">{formatMoney(est.fee, account.currency)}</span>
        </li>
        <li className="summary__total">
          <span className="summary__k">빠져나갈 돈</span>
          <span className="summary__v" data-testid="buy-total">
            {formatMoney(est.total, account.currency)}
          </span>
        </li>
        <li>
          <span className="summary__k">사고 나면 남는 현금</span>
          <span className="summary__v">
            {formatMoney(Math.max(0, account.cash - est.total), account.currency)}
          </span>
        </li>
      </ul>

      {block && <p className="form-error">{block}</p>}
      {error && <p className="form-error">{error}</p>}

      <button
        type="button"
        className="btn btn--buy btn--block"
        style={{ marginTop: 12 }}
        disabled={block !== null}
        onClick={() => setConfirming(true)}
      >
        {quantity.toLocaleString("ko-KR")}주 사기
      </button>

      {stock.stale && (
        <p className="small muted" style={{ marginTop: 8 }}>
          지금은 장이 열려 있지 않거나 시세를 새로 받지 못했습니다. 마지막으로 확인된
          가격으로 체결됩니다.
        </p>
      )}

      <ConfirmModal
        open={confirming}
        title="이대로 살까요?"
        desc="확정하면 되돌릴 수 없습니다."
        confirmLabel="네, 삽니다"
        tone="buy"
        busy={busy}
        warning="모의투자입니다. 실제 돈이 오가지는 않습니다."
        onCancel={() => setConfirming(false)}
        onConfirm={confirm}
      >
        <ul className="summary">
          <li>
            <span className="summary__k">종목</span>
            <span className="summary__v">
              {stock.name} ({stock.symbol})
            </span>
          </li>
          <li>
            <span className="summary__k">수량</span>
            <span className="summary__v">{quantity.toLocaleString("ko-KR")}주</span>
          </li>
          <li>
            <span className="summary__k">1주 가격</span>
            <span className="summary__v">{formatMoney(stock.price, account.currency)}</span>
          </li>
          <li>
            <span className="summary__k">수수료</span>
            <span className="summary__v">{formatMoney(est.fee, account.currency)}</span>
          </li>
          <li className="summary__total">
            <span className="summary__k">모두 합쳐</span>
            <span className="summary__v">{formatMoney(est.total, account.currency)}</span>
          </li>
        </ul>
      </ConfirmModal>
    </div>
  );
}

export default BuyPanel;
