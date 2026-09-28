// 되돌릴 수 없는 행동(매수·매도) 앞의 확인 단계(SPEC §8.2).
// 요약을 다시 한 번 보여주고, 기본 포커스는 "취소"에 둔다 — 엔터 연타로 체결되는
// 사고를 막기 위해서다.
import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

export interface ConfirmModalProps {
  open: boolean;
  title: string;
  desc?: string;
  /** 확인 버튼 문구. 무엇이 일어나는지 동사로 적는다. */
  confirmLabel: string;
  /** 확인 버튼 톤: 매수=빨강, 매도=파랑(한국 증권 관례) */
  tone?: "buy" | "sell" | "neutral";
  warning?: string;
  /** 주문이 나가 있는 중 — 문구가 "처리 중…"으로 바뀐다. */
  busy?: boolean;
  /** 지금은 확정할 수 없음(입력이 유효하지 않음). 문구는 그대로 두고 잠그기만 한다. */
  disabled?: boolean;
  children?: ReactNode;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  open,
  title,
  desc,
  confirmLabel,
  tone = "neutral",
  warning,
  busy = false,
  disabled = false,
  children,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) cancelRef.current?.focus();
  }, [open]);

  // ESC 로 언제든 빠져나갈 수 있어야 한다.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  const toneClass = tone === "buy" ? "btn--buy" : tone === "sell" ? "btn--sell" : "btn--primary";

  return (
    <div className="modal-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="modal__title">{title}</h2>
        {desc && <p className="modal__desc">{desc}</p>}
        {children}
        {warning && <p className="modal__warn">{warning}</p>}
        <div className="modal__actions">
          <button ref={cancelRef} type="button" className="btn btn--outline" onClick={onCancel}>
            취소
          </button>
          <button
            type="button"
            className={`btn ${toneClass}`}
            disabled={busy || disabled}
            onClick={onConfirm}
          >
            {busy ? "처리 중…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ConfirmModal;
