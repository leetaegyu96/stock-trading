// 수동 매도 패널(모달). 수량을 정하면 손에 들어올 돈과 이번에 확정될 손익을
// 미리 보여준다 — 세금·수수료가 빠진 "실제로 받는 돈"을 숨기지 않기 위해서다.
import { useMemo, useState } from "react";
import type { AccountSummary, Position } from "../types";
import { ConfirmModal } from "./ConfirmModal";
import { QuantityStepper } from "./QuantityStepper";
import { formatMoney, formatSignedMoney, signClass } from "./format";
import { estimateRealizedPnl, estimateSell, sellBlockReason } from "./money";

export interface SellPanelProps {
  open: boolean;
  account: AccountSummary;
  position: Position;
  onSell: (quantity: number) => Promise<void>;
  onClose: () => void;
}

export function SellPanel({ open, account, position, onSell, onClose }: SellPanelProps) {
  const [quantity, setQuantity] = useState(position.quantity);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const est = useMemo(
    () => estimateSell(position.current_price, quantity, account.kind, account.currency),
    [position.current_price, quantity, account.kind, account.currency]
  );
  const pnl = useMemo(
    () =>
      estimateRealizedPnl(
        position.current_price,
        position.avg_price,
        quantity,
        account.kind,
        account.currency
      ),
    [position, quantity, account.kind, account.currency]
  );
  const block = sellBlockReason(quantity, position.quantity, position.current_price);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSell(quantity);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "주문을 넣지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <ConfirmModal
      open={open}
      title={`${position.name} 팔기`}
      desc="확정하면 되돌릴 수 없습니다."
      confirmLabel={block ? "팔 수 없음" : `${quantity.toLocaleString("ko-KR")}주 팔기`}
      tone="sell"
      busy={busy}
      disabled={block !== null}
      warning={
        quantity === position.quantity
          ? "전부 팔면 이 종목에 걸어둔 자동 매도 기준도 함께 사라집니다."
          : undefined
      }
      onCancel={onClose}
      onConfirm={confirm}
    >
      <div className="row" style={{ margin: "12px 0" }}>
        <QuantityStepper
          value={quantity}
          onChange={setQuantity}
          min={0}
          max={position.quantity}
          label="팔 수량"
        />
        <span className="small muted">/ 가진 {position.quantity.toLocaleString("ko-KR")}주</span>
        <button
          type="button"
          className="btn btn--outline"
          onClick={() => setQuantity(position.quantity)}
        >
          전부
        </button>
      </div>

      <ul className="summary">
        <li>
          <span className="summary__k">지금 가격</span>
          <span className="summary__v">{formatMoney(position.current_price, account.currency)}</span>
        </li>
        <li>
          <span className="summary__k">주식값</span>
          <span className="summary__v">{formatMoney(est.gross, account.currency)}</span>
        </li>
        <li>
          <span className="summary__k">수수료</span>
          <span className="summary__v">-{formatMoney(est.fee, account.currency)}</span>
        </li>
        {account.kind === "KR" && (
          <li>
            <span className="summary__k">세금</span>
            <span className="summary__v">-{formatMoney(est.tax, account.currency)}</span>
          </li>
        )}
        <li className="summary__total">
          <span className="summary__k">손에 들어올 돈</span>
          <span className="summary__v" data-testid="sell-net">
            {formatMoney(est.net, account.currency)}
          </span>
        </li>
        <li>
          <span className="summary__k">이번에 확정되는 손익</span>
          <span className={`summary__v ${signClass(pnl)}`}>
            {formatSignedMoney(pnl, account.currency)}
          </span>
        </li>
      </ul>

      {block && <p className="form-error">{block}</p>}
      {error && <p className="form-error">{error}</p>}
    </ConfirmModal>
  );
}

export default SellPanel;
