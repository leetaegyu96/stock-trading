// 메인 화면의 리치 캐릭터 카드 (설계 스펙 §6 "메인").
// 아바타 · 캐릭터명 · 유니버스/통화 · 총자산 · TWR · 누적손익 · 오늘 등락 ·
// 30일 자산곡선 스파크라인 · 보유종목수·현금 · 벤치마크 대비.
import type { CardSummary } from "../types";
import { Avatar } from "./Avatar";
import { moodFromPnl } from "./mood";
import { Sparkline } from "./Sparkline";
import "./theme.css";

export interface CharacterCardProps {
  summary: CardSummary;
  onClick?: (name: string) => void;
}

function formatKrw(value: number): string {
  return `₩${Math.round(value).toLocaleString("ko-KR")}`;
}

/** 부호에 따른 클래스명 (상승=up=빨강, 하락=down=파랑, 0=neutral). */
function signClass(value: number): "up" | "down" | "neutral" {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "neutral";
}

function signedPct(value: number, digits = 2): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function CharacterCard({ summary, onClick }: CharacterCardProps) {
  // CardSummary.today_pnl_pct는 비율(ratio, 예: 0.012 = +1.2%) 단위로 내려온다.
  // moodFromPnl/화면 표기는 퍼센트(%) 단위를 쓰므로 카드 경계에서 한 번만 변환한다.
  const todayPct = summary.today_pnl_pct * 100;
  const mood = moodFromPnl(todayPct);
  const todaySign = signClass(todayPct);
  const twrPct = summary.twr * 100;
  const pnlSign = signClass(summary.pnl_krw);

  return (
    <div
      className="char-card"
      role="button"
      tabIndex={0}
      onClick={() => onClick?.(summary.name)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onClick?.(summary.name);
      }}
    >
      <div className="char-card__header">
        <Avatar character={summary.name} mood={mood} size={56} />
        <div className="char-card__identity">
          <span className="char-card__name">{summary.name}</span>
          <span className="char-card__meta">
            {summary.markets.join("/")} · {summary.base_currency}
          </span>
        </div>
      </div>

      <div className="char-card__row">
        <span className="char-card__row-label">총자산</span>
        <span className="char-card__row-value">{formatKrw(summary.total_asset_krw)}</span>
      </div>

      <div className="char-card__row">
        <span className="char-card__row-label">TWR</span>
        <span className={`char-card__row-value ${signClass(twrPct)}`}>{signedPct(twrPct)}</span>
      </div>

      <div className="char-card__row">
        <span className="char-card__row-label">누적손익</span>
        <span className={`char-card__row-value ${pnlSign}`}>{formatKrw(summary.pnl_krw)}</span>
      </div>

      <div className={`char-card__today ${todaySign}`}>
        <span aria-hidden="true">{todayPct > 0 ? "▲" : todayPct < 0 ? "▼" : "—"}</span>
        <span>오늘 {signedPct(todayPct)}</span>
      </div>

      <div className="char-card__spark">
        <Sparkline points={summary.equity_spark} />
      </div>

      <div className="char-card__footer">
        <span>보유 {summary.n_positions}종목</span>
        <span>현금 {formatKrw(summary.cash_krw)}</span>
      </div>

      <div className="char-card__footer">
        <span>벤치대비</span>
        <span className={summary.benchmark_delta === null ? "neutral" : signClass(summary.benchmark_delta)}>
          {summary.benchmark_delta === null ? "—" : `${signedPct(summary.benchmark_delta * 100)}p`}
        </span>
      </div>
    </div>
  );
}

export default CharacterCard;
