// 장중 자동매매 스캔 상태 스트립. "실시간 연결"(소켓)과 별개로, 스캔이 실제로 돌고 있는지·
// 언제(시장 벽시계 + KST/ET)·몇 분 전인지·몇 종목을 봤는지·게이트 통과 몇·매수/매도 몇 건인지를
// 보여준다. 매매가 없어도 하트비트가 있으면 데몬이 살아있음을 알 수 있다(조용한 실패 방지).
// 카드 스냅샷(asOf) 갱신 시 재조회하고, "N분 전"은 30초마다 갱신한다.
import { useEffect, useState } from "react";
import { getScanStatus } from "../api";
import type { ScanStatus } from "../types";
import "./theme.css";

/** ts 는 시장 벽시계(naive ISO). 타임존 변환 없이 HH:MM 만 취한다. */
function hhmm(iso: string): string {
  return iso.length >= 16 ? iso.slice(11, 16) : iso;
}

/** 절대 시각 차이(ms)를 "방금 전"/"N분 전"/"N시간 전" 상대 표기로. */
function relative(ageMs: number): string {
  if (ageMs < 60_000) return "방금 전";
  const min = Math.floor(ageMs / 60_000);
  if (min < 60) return `${min}분 전`;
  return `${Math.floor(min / 60)}시간 전`;
}

function line(s: ScanStatus, nowMs: number): string {
  const failed = s.failed > 0 ? `(실패 ${s.failed})` : "";
  return (
    `${s.market} ${hhmm(s.ts)} ${s.tz} · ${relative(nowMs - s.ts_epoch_ms)}` +
    ` · ${s.evaluated}/${s.universe_size}종목${failed}` +
    ` · 게이트통과 ${s.gate_pass} · 매수 ${s.buys}/매도 ${s.sells}` +
    ` · 다음 ~${s.scan_minutes}분`
  );
}

export interface ScanStatusStripProps {
  /** 카드 스냅샷 수신 시각 — 값이 바뀌면 스캔 상태를 재조회한다. */
  asOf?: Date | null;
  /** 초기값(테스트/SSR 렌더 검증용). 실제 앱에서는 마운트 시 조회로 대체된다. */
  initialStatuses?: ScanStatus[];
  /** 고정 now(ms) — 테스트 결정성용. 미지정 시 현재시각으로 30초마다 갱신. */
  nowMs?: number;
}

export function ScanStatusStrip({ asOf = null, initialStatuses = [], nowMs }: ScanStatusStripProps) {
  const [statuses, setStatuses] = useState<ScanStatus[]>(initialStatuses);
  const [now, setNow] = useState<number>(() => nowMs ?? Date.now());

  useEffect(() => {
    let cancelled = false;
    getScanStatus()
      .then((rows) => {
        if (!cancelled) setStatuses(rows);
      })
      .catch(() => {
        // 조회 실패 시 마지막으로 알던 값을 유지한다(다른 표시는 계속 정상 동작).
      });
    return () => {
      cancelled = true;
    };
  }, [asOf]);

  useEffect(() => {
    if (nowMs !== undefined) return; // 테스트: now 고정
    const id = setInterval(() => setNow(Date.now()), 30_000); // "N분 전" 갱신
    return () => clearInterval(id);
  }, [nowMs]);

  return (
    <div className="scan-strip">
      <span className="scan-strip__label">장중 스캔</span>
      {statuses.length === 0 ? (
        <span className="scan-strip__empty">대기 중 (가동 전이거나 INTRADAY OFF)</span>
      ) : (
        statuses.map((s) => (
          <span key={s.market} className="scan-strip__market">
            {line(s, now)}
          </span>
        ))
      )}
    </div>
  );
}

export default ScanStatusStrip;
