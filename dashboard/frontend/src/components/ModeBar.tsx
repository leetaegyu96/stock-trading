// 앱 셸 상단 운영모드 바: 모든 화면에서 항상 보인다(audit §4/§5).
// - 운영 모드(PAPER) 배지: 이 제품은 모의투자/리플레이 전용, KIS는 시세조회만, 실주문 없음.
// - 데이터 as-of: WebSocket "연결" 여부와 별개 신호. 연결돼 있어도 마지막 스냅샷이
//   오래됐을 수 있으므로 두 표시를 분리한다.
// - 시장별 데이터 기준(P0): 전역 as-of는 "WS 스냅샷을 언제 받았는지"일 뿐, 시장별로
//   실제 데이터가 어느 날짜까지 채워져 있는지는 별개 신호다. /api/status 를 마운트 시
//   조회하고, 새 카드 스냅샷이 도착할 때(asOf 갱신)마다 다시 조회해 최신화한다.
import { useEffect, useState } from "react";
import { getMarketStatus } from "../api";
import type { MarketStatus } from "../types";
import { OPERATING_MODE, OPERATING_MODE_DESC, formatAsOf, formatMarketStatusLine } from "./mode";
import "./theme.css";

export interface ModeBarProps {
  /** WebSocket 연결 여부. */
  connected: boolean;
  /** 마지막으로 데이터 스냅샷을 받은 시각(연결 여부와 무관). */
  asOf: Date | null;
  /** 현재 화면에 걸린 시장 목록(참고 표시용). */
  markets: string[];
  /** 시장별 데이터 기준 초기값. 테스트/SSR 환경(effect가 돌지 않는 렌더)에서 렌더 결과를
   * 검증하기 위한 시드값이며, 실제 앱에서는 마운트 시 /api/status 조회로 곧 대체된다. */
  initialMarketStatuses?: MarketStatus[];
}

export function ModeBar({ connected, asOf, markets, initialMarketStatuses = [] }: ModeBarProps) {
  const [marketStatuses, setMarketStatuses] = useState<MarketStatus[]>(initialMarketStatuses);

  // 마운트 시 1회 + 새 카드 스냅샷이 도착할 때(asOf 갱신)마다 재조회.
  // 연결 상태 표시(mode-bar__conn)와는 독립적으로 동작한다 — 조회 실패는 조용히 무시하고
  // 기존 표시를 유지한다(전역 as-of/연결 표시는 이 로딩과 무관하게 그대로 렌더됨).
  useEffect(() => {
    let cancelled = false;
    getMarketStatus()
      .then((rows) => {
        if (!cancelled) setMarketStatuses(rows);
      })
      .catch(() => {
        // 조회 실패 시 마지막으로 알던 값을 유지 — 다른 표시는 계속 정상 동작해야 한다.
      });
    return () => {
      cancelled = true;
    };
  }, [asOf]);

  return (
    <div className="mode-bar">
      <span className="mode-bar__badge" title={OPERATING_MODE_DESC}>
        {OPERATING_MODE}
      </span>
      <span className="mode-bar__desc">{OPERATING_MODE_DESC}</span>
      {markets.length > 0 && <span className="mode-bar__markets">{markets.join(" · ")}</span>}
      <span className="mode-bar__asof">{formatAsOf(asOf)}</span>
      {marketStatuses.length > 0 && (
        <span className="mode-bar__market-status">{formatMarketStatusLine(marketStatuses)}</span>
      )}
      <span className={`mode-bar__conn${connected ? " mode-bar__conn--on" : ""}`}>
        {connected ? "실시간 연결" : "연결 끊김"}
      </span>
    </div>
  );
}

export default ModeBar;
