// 수량 입력. 직접 타이핑도 되지만 +/- 로도 조절된다 — 초보가 0 을 더 붙여
// 실수하는 것을 줄이려는 장치다.
export interface QuantityStepperProps {
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  label?: string;
}

export function QuantityStepper({
  value,
  onChange,
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
  label = "수량",
}: QuantityStepperProps) {
  const clamp = (n: number) => Math.min(max, Math.max(min, n));

  return (
    <div className="stepper">
      <button
        type="button"
        className="stepper__btn"
        aria-label={`${label} 1 줄이기`}
        disabled={value <= min}
        onClick={() => onChange(clamp(value - 1))}
      >
        −
      </button>
      <input
        className="stepper__input num"
        type="number"
        inputMode="numeric"
        aria-label={label}
        value={Number.isFinite(value) ? value : 0}
        min={min}
        max={max}
        onChange={(e) => {
          const parsed = Number.parseInt(e.target.value, 10);
          onChange(Number.isNaN(parsed) ? 0 : clamp(parsed));
        }}
      />
      <button
        type="button"
        className="stepper__btn"
        aria-label={`${label} 1 늘리기`}
        disabled={value >= max}
        onClick={() => onChange(clamp(value + 1))}
      >
        +
      </button>
    </div>
  );
}

export default QuantityStepper;
