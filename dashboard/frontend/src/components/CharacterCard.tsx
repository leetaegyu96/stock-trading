// 메인 화면 캐릭터 카드: 총자산을 히어로 숫자로, 오늘 등락은 칩으로,
// 30일 자산 추이는 영역 스파크라인으로. 상승=빨강, 하락=파랑.
import type { CardSummary } from "../types";
import { Avatar } from "./Avatar";
import { moodFromPnl } from "./mood";
import { Sparkline } from "./Sparkline";
import {
  BENCHMARK_UNAVAILABLE_LABEL,
  benchmarkDeltaLabel,
  formatKrw,
  formatSignedKrw,
  signClass,
  signedPct,
} from "./format";
import "./theme.css";

export interface CharacterCardProps {
  summary: CardSummary;
  onClick?: (name: string) => void;
}

export function CharacterCard({ summary, onClick }: CharacterCardProps) {
  // CardSummary.today_pnl_pct/twr 는 비율(ratio) — 표기 직전에 한 번만 % 변환.
  const todayPct = summary.today_pnl_pct * 100;
  const twrPct = summary.twr * 100;
  const mood = moodFromPnl(todayPct);
  const todaySign = signClass(todayPct);

  return (
    <article
      className="char-card"
      role="button"
      tabIndex={0}
      aria-label={`${summary.name} 상세 보기`}
      onClick={() => onClick?.(summary.name)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onClick?.(summary.name);
      }}
    >
      <header className="char-card__head">
        <Avatar character={summary.name} mood={mood} size={44} />
        <div className="char-card__identity">
          <span className="char-card__name">{summary.name}</span>
          <span className="char-card__meta">
            {summary.markets.join(" · ")} · {summary.base_currency}
          </span>
        </div>
        <span className={`chip chip--${todaySign}`}>
          <span aria-hidden="true">
            {todayPct > 0 ? "▲" : todayPct < 0 ? "▼" : "–"}
          </span>
          {signedPct(todayPct)}
        </span>
      </header>

      <div className="char-card__hero">
        <span className="char-card__hero-label">총자산</span>
        <strong className="char-card__hero-value num">
          {formatKrw(summary.total_asset_krw)}
        </strong>
      </div>

      <dl className="char-card__stats">
        <div>
          <dt>수익률 (TWR)</dt>
          <dd className={`num ${signClass(twrPct)}`}>{signedPct(twrPct)}</dd>
        </div>
        <div>
          <dt>누적손익</dt>
          <dd className={`num ${signClass(summary.pnl_krw)}`}>
            {formatSignedKrw(summary.pnl_krw)}
          </dd>
        </div>
      </dl>

      <div className="char-card__spark">
        <Sparkline points={summary.equity_spark} />
      </div>

      <footer className="char-card__foot">
        <span>
          보유 <span className="num">{summary.n_positions}</span>종목
        </span>
        {summary.benchmark_available && summary.benchmark_delta !== null ? (
          <span className={signClass(summary.benchmark_delta)}>
            벤치 <span className="num">{benchmarkDeltaLabel(summary.benchmark_delta).replace("초과수익 ", "")}</span>
          </span>
        ) : (
          <span className="char-card__benchmark-warn" title="벤치마크 데이터가 아직 집계되지 않았습니다.">
            ⚠ {BENCHMARK_UNAVAILABLE_LABEL}
          </span>
        )}
        <span>
          현금 <span className="num">{formatKrw(summary.cash_krw)}</span>
        </span>
      </footer>
    </article>
  );
}

export default CharacterCard;
