// 입출금 모달: 캐릭터 상세 헤더의 입금/출금 버튼에서 연다. 금액 입력 + (출금 시)
// 보유종목 중 청산할 종목 선택 → postDeposit/postWithdraw 호출. 성공 시 "다음 개장에
// 반영" 안내 후 자동 닫힘, 실패 시 인라인 에러 표시. Esc/배경 클릭으로 닫을 수 있다.
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, postDeposit, postWithdraw } from "../api";
import type { PositionOut } from "../types";
import { formatKrw } from "./format";
import { isPositiveAmount, parseAmountInput } from "./flow";
import "./flow.css";

export type FlowMode = "deposit" | "withdraw";

export interface FlowModalProps {
  name: string;
  mode: FlowMode;
  positions: PositionOut[];
  onClose: () => void;
}

const AUTO_CLOSE_MS = 1800;

export function FlowModal({ name, mode, positions, onClose }: FlowModalProps) {
  const [amount, setAmount] = useState("");
  const [liquidate, setLiquidate] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const title = mode === "deposit" ? "입금" : "출금";
  const parsedAmount = parseAmountInput(amount);
  const amountValid = isPositiveAmount(parsedAmount);
  const showAmountError = amount.trim() !== "" && !amountValid;

  // 모달이 열리면 금액 입력에 포커스.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // 성공 후 잠시 안내를 보여주고 자동으로 닫는다.
  useEffect(() => {
    if (!success) return undefined;
    const timer = window.setTimeout(onClose, AUTO_CLOSE_MS);
    return () => window.clearTimeout(timer);
  }, [success, onClose]);

  // Esc 키로 닫기 (제출 중에는 무시).
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && !submitting) onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, submitting]);

  function toggleSymbol(symbol: string) {
    setLiquidate((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!amountValid || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      if (mode === "deposit") {
        await postDeposit(name, parsedAmount);
      } else {
        await postWithdraw(name, parsedAmount, Array.from(liquidate));
      }
      setSuccess(true);
    } catch (err) {
      setSubmitError(
        err instanceof ApiError ? err.message : "요청 처리 중 오류가 발생했습니다."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="flow-modal__backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div
        className="flow-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="flow-modal-title"
      >
        <div className="flow-modal__header">
          <h2 id="flow-modal-title" className="flow-modal__title">
            {name} {title}
          </h2>
          <button
            type="button"
            className="flow-modal__close"
            onClick={onClose}
            disabled={submitting}
            aria-label="닫기"
          >
            ×
          </button>
        </div>

        {success ? (
          <div className="flow-modal__success">
            <p>{title} 요청이 접수되었습니다.</p>
            <p className="flow-modal__hint">다음 개장에 반영됩니다.</p>
            <div className="flow-modal__actions">
              <button type="button" className="flow-modal__submit" onClick={onClose}>
                닫기
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <label className="flow-modal__field">
              <span>금액 (₩)</span>
              <input
                ref={inputRef}
                type="text"
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="예: 1000000"
                disabled={submitting}
                aria-invalid={showAmountError}
              />
            </label>
            {showAmountError && (
              <p className="flow-modal__error">금액은 0보다 큰 숫자여야 합니다.</p>
            )}
            {amountValid && (
              <p className="flow-modal__hint">{formatKrw(parsedAmount)}</p>
            )}

            {mode === "withdraw" && (
              <div className="flow-modal__liquidate">
                <span className="flow-modal__field-label">청산할 보유종목 (선택)</span>
                {positions.length === 0 ? (
                  <p className="flow-modal__hint">보유 종목이 없습니다.</p>
                ) : (
                  <ul className="flow-modal__liquidate-list">
                    {positions.map((pos) => (
                      <li key={`${pos.market}:${pos.symbol}`}>
                        <label className="flow-modal__liquidate-item">
                          <input
                            type="checkbox"
                            checked={liquidate.has(pos.symbol)}
                            onChange={() => toggleSymbol(pos.symbol)}
                            disabled={submitting}
                          />
                          <span className="detail-table__symbol">{pos.symbol}</span>
                          <span className="detail-table__market">{pos.market}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {submitError && <p className="flow-modal__error">{submitError}</p>}

            <div className="flow-modal__actions">
              <button type="button" onClick={onClose} disabled={submitting}>
                취소
              </button>
              <button
                type="submit"
                className="flow-modal__submit"
                disabled={!amountValid || submitting}
              >
                {submitting ? "처리 중…" : title}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export default FlowModal;
