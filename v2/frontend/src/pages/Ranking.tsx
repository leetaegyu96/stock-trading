// 랭킹 — 모든 참가자를 **오늘 수익률**(어제 마감 대비) 순으로 줄 세운다.
//
// 설계 의도
// - 상위 3위는 시상대로 크게, 4위부터는 표로. 등수를 한눈에 읽는 게 이 화면의 일이다.
// - 국내는 원, 해외는 달러라 **금액은 서로 비교할 수 없다**. 그래서 순위 기준은 비율(%)이고,
//   그 사실을 화면에 글로 적어 둔다(SPEC §8.2 — 숫자 옆에 항상 의미를 적는다).
// - 색만으로 오름/내림을 말하지 않는다 — ▲/▼ 와 +/− 부호를 늘 함께 쓴다.
import { useEffect, useState } from "react";
import * as api from "../api";
import { DailyReturnBar } from "../components/DailyReturnBar";
import { EmptyState } from "../components/EmptyState";
import { RankPodium } from "../components/RankPodium";
import {
  changeArrow,
  formatMoney,
  formatSignedMoney,
  kindShort,
  signClass,
  signedPct,
} from "../components/format";
import { PODIUM_SIZE, maxAbsDailyReturn, myRowsBelowPodium } from "../components/ranking";
import type { RankingKind, RankingRow } from "../types";

const TABS: Array<{ key: RankingKind; label: string; desc: string }> = [
  { key: "all", label: "전체", desc: "국내·해외 캐릭터를 모두 한 줄에 세웁니다." },
  { key: "KR", label: "국내", desc: "국내 주식 캐릭터끼리만 견줍니다." },
  { key: "US", label: "해외", desc: "해외 주식 캐릭터끼리만 견줍니다." },
];

/** 표 한 줄. 시상대에 못 든 사람과, 아래 '내 순위'에서 같은 모양으로 재사용한다. */
function RankRow({ row, maxAbs }: { row: RankingRow; maxAbs: number }) {
  return (
    <tr className={row.is_me ? "rank-row rank-row--me" : "rank-row"}>
      <th scope="row" className="rank-row__rank num">
        {row.rank}
        <span className="rank-row__rank-unit">위</span>
      </th>

      <td>
        <div className="rank-row__who">
          <span className="rank-row__name">{row.nickname}</span>
          {row.is_me && <span className="chip chip--me">나</span>}
        </div>
        <div className="rank-row__tags">
          <span className={`kindtag kindtag--${row.kind.toLowerCase()}`}>
            {kindShort(row.kind)}
          </span>
          <span className="muted small">{row.position_count}종목</span>
          {row.stale && <span className="stale-badge">시세 지연</span>}
        </div>
      </td>

      <td className="rank-row__bar">
        <DailyReturnBar
          pct={row.daily_return_pct}
          maxAbs={maxAbs}
          label={`${row.nickname} 오늘 수익률`}
        />
      </td>

      <td className="table__num">
        <div className={`rank-row__pct num ${signClass(row.daily_return_pct)}`}>
          <span aria-hidden="true">{changeArrow(row.daily_return_pct)}</span>{" "}
          {signedPct(row.daily_return_pct)}
        </div>
        <div className="muted small num">
          {formatSignedMoney(row.daily_pnl, row.currency)}
        </div>
      </td>

      <td className={`table__num num ${signClass(row.total_return_pct)}`}>
        {signedPct(row.total_return_pct)}
      </td>

      <td className="table__num num">{formatMoney(row.total_asset, row.currency)}</td>
    </tr>
  );
}

export function Ranking() {
  const [kind, setKind] = useState<RankingKind>("all");
  const [rows, setRows] = useState<RankingRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** '다시 시도' 로 같은 탭을 한 번 더 불러오기 위한 트리거. */
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let alive = true;
    setRows(null);
    setError(null);
    void (async () => {
      try {
        const data = await api.getRanking(kind);
        if (alive) setRows(data);
      } catch (e) {
        // 탭을 빠르게 옮기면 늦게 온 응답이 새 탭 화면을 덮을 수 있어 alive 로 막는다.
        if (alive) setError(e instanceof Error ? e.message : "랭킹을 불러오지 못했습니다.");
      }
    })();
    return () => {
      alive = false;
    };
  }, [kind, reloadKey]);

  const tab = TABS.find((t) => t.key === kind) ?? TABS[0];
  const top = rows ? rows.slice(0, PODIUM_SIZE) : [];
  const rest = rows ? rows.slice(PODIUM_SIZE) : [];
  // 막대 길이는 **표 안에서만** 비교하므로, 정규화 기준도 표에 실린 값들로 잡는다.
  const maxAbs = maxAbsDailyReturn(rest);
  const mine = rows ? myRowsBelowPodium(rows) : [];

  return (
    <div>
      <div className="page-head">
        <h1 className="page-title">랭킹</h1>
        {rows && <span className="muted small">참가자 {rows.length}명</span>}
      </div>
      <p className="page-sub">
        <b>오늘 수익률</b>(어제 마감 대비 오늘 늘어난 비율) 순입니다. 국내는 원, 해외는
        달러라 금액은 서로 비교할 수 없어서, 순위는 금액이 아니라 비율(%)로 매깁니다.
      </p>

      <div className="filters" role="group" aria-label="랭킹 범위 고르기">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`filter-btn${kind === t.key ? " filter-btn--on" : ""}`}
            aria-pressed={kind === t.key}
            onClick={() => setKind(t.key)}
          >
            {t.label}
          </button>
        ))}
        <span className="muted small">{tab.desc}</span>
      </div>

      {error && (
        <div className="page-state page-state--error">
          {error}{" "}
          <button type="button" className="btn btn--ghost" onClick={() => setReloadKey((k) => k + 1)}>
            다시 시도
          </button>
        </div>
      )}
      {!error && rows === null && <div className="page-state">불러오는 중…</div>}

      {rows !== null && rows.length === 0 && (
        <EmptyState
          title="아직 순위에 오를 참가자가 없습니다"
          desc="캐릭터가 하루라도 거래를 하거나 장이 한 번 마감되면 이 자리에 순위가 생깁니다."
        />
      )}

      {rows !== null && rows.length > 0 && (
        <>
          <RankPodium rows={top} />

          {rest.length > 0 && (
            <div className="card rank-card">
              <div className="rank-legend">
                <span className="rank-legend__item">
                  <span className="rank-legend__swatch rank-legend__swatch--down" aria-hidden="true" />
                  왼쪽 · 내림(−)
                </span>
                <span className="rank-legend__item">
                  <span className="rank-legend__swatch rank-legend__swatch--zero" aria-hidden="true" />
                  가운데 · 0%
                </span>
                <span className="rank-legend__item">
                  <span className="rank-legend__swatch rank-legend__swatch--up" aria-hidden="true" />
                  오른쪽 · 오름(+)
                </span>
              </div>

              <div className="table-scroll">
                <table className="table rank-table">
                  <caption className="rank-table__caption">
                    {PODIUM_SIZE + 1}위부터의 순위표. 막대 길이는 이 표 안에서 가장 크게
                    움직인 사람을 기준으로 맞췄습니다.
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col" className="table__num">등수</th>
                      <th scope="col">참가자</th>
                      <th scope="col">오늘 흐름</th>
                      <th scope="col" className="table__num">오늘 수익률</th>
                      <th scope="col" className="table__num">누적 수익률</th>
                      <th scope="col" className="table__num">총자산</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rest.map((row) => (
                      <RankRow key={`${row.account_id}-${row.kind}`} row={row} maxAbs={maxAbs} />
                    ))}
                  </tbody>

                  {mine.length > 0 && (
                    <tfoot className="rank-mine">
                      <tr>
                        <th scope="rowgroup" colSpan={6} className="rank-mine__label">
                          내 순위 — 위에서 찾지 않아도 되게 한 번 더 보여드립니다
                        </th>
                      </tr>
                      {mine.map((row) => (
                        <RankRow
                          key={`mine-${row.account_id}-${row.kind}`}
                          row={row}
                          maxAbs={maxAbs}
                        />
                      ))}
                    </tfoot>
                  )}
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default Ranking;
