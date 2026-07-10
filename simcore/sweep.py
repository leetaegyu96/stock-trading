"""하락장 가드 튜닝 스윕: KR×US MA 기간 그리드(가드 전체 on) + OFF 기준 리플레이.

  python -m simcore.sweep --start 2026-01-09 --end 2026-07-09              # 그리드 16+1회
  python -m simcore.sweep --start 2025-07-10 --end 2026-07-09 \
      --validate --kr-period 60 --us-period 20 --chars 해외형,범용형        # OFF vs 후보 2회

채택 규칙: TWR ≥ OFF−1.0%p AND |MDD| 개선 → |MDD| 최소, 동률 시 TWR 최대. 없으면 off.
(스펙: docs/superpowers/specs/2026-07-10-bear-guard-tuning-design.md §1·§6)
"""
from __future__ import annotations
import argparse
import itertools
from dataclasses import replace
from datetime import date
from pathlib import Path

from simcore.config import Config
from simcore import data as datamod, universe
from simcore.engine import DEFAULT_CHARACTERS
from simcore.replay import DataBundle, run_replay

PERIODS = (20, 40, 60, 120)
ALL_CHARS = frozenset(c.name for c in DEFAULT_CHARACTERS)
TWR_TOL = 0.01      # 채택: TWR ≥ OFF − 1.0%p


def improves(off: dict, on: dict, twr_tol: float = TWR_TOL) -> bool:
    """채택 규칙: TWR 손해가 tol 이내 AND |MDD| 개선(감소)."""
    return on["twr"] >= off["twr"] - twr_tol and abs(on["mdd"]) < abs(off["mdd"])


def pick_single(char: str, off_summary: dict, runs: list[dict], key: str) -> dict | None:
    """단일시장 캐릭터 최적 기간. key='kr'|'us' — 같은 기간이면 결과 동일하므로 첫 run만 본다."""
    seen, cands = set(), []
    for r in runs:
        p = r[key]
        if p in seen:
            continue
        seen.add(p)
        summ = r["summary"][char]
        if improves(off_summary[char], summ):
            cands.append((abs(summ["mdd"]), -summ["twr"], p, summ))
    if not cands:
        return None
    cands.sort()
    _, _, p, summ = cands[0]
    return {"period": p, **summ}


def pick_universal(off_summary: dict, runs: list[dict],
                   kr_p: int | None, us_p: int | None) -> dict | None:
    """범용형: 단일시장 캐릭터가 확정한 기간(kr_p/us_p)에 고정. None 축은 자유 탐색."""
    cands = []
    for r in runs:
        if kr_p is not None and r["kr"] != kr_p:
            continue
        if us_p is not None and r["us"] != us_p:
            continue
        summ = r["summary"]["범용형"]
        if improves(off_summary["범용형"], summ):
            cands.append((abs(summ["mdd"]), -summ["twr"], r["kr"], r["us"], summ))
    if not cands:
        return None
    cands.sort()
    _, _, kr, us, summ = cands[0]
    return {"kr": kr, "us": us, **summ}


def _load_bundle(start: date, end: date, kr_top: int, us_top: int, cache: Path) -> DataBundle:
    kr_syms = universe.kospi200(cache, start)[:kr_top]
    us_syms = universe.sp500(cache)[:us_top]
    print(f"[sweep] universe KR {len(kr_syms)} / US {len(us_syms)}, 데이터 로딩...")
    return DataBundle(
        kr=datamod.load_kr_daily(kr_syms, start, end, cache),
        us=datamod.load_us_daily(us_syms, start, end, cache),
        fx=datamod.load_fx(start, end, cache),
        kr_index=datamod.load_index("KR", start, end, cache),
        us_index=datamod.load_index("US", start, end, cache),
    )


def _cfg(kr_p: int, us_p: int, chars: frozenset) -> Config:
    base = Config()
    return replace(base,
                   signals=replace(base.signals,
                                   market_trend_period_kr=kr_p, market_trend_period_us=us_p),
                   rules=replace(base.rules, bear_guard_characters=chars))


def _md_rows(label: str, summary: dict) -> list[str]:
    return [f"| {label} | {name} | {s['twr'] * 100:.2f} | {s['mdd'] * 100:.2f} | {s['n_trades']} |"
            for name, s in summary.items()]


def main() -> None:
    ap = argparse.ArgumentParser(prog="simcore.sweep", description="하락장 가드 튜닝 스윕")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--kr-top", type=int, default=200)
    ap.add_argument("--us-top", type=int, default=100)
    ap.add_argument("--cache", default="data/cache")
    ap.add_argument("--out", default=None, help="markdown 표 저장 경로(기본 stdout)")
    ap.add_argument("--validate", action="store_true", help="그리드 대신 OFF vs 단일 후보 2회")
    ap.add_argument("--kr-period", type=int, default=20)
    ap.add_argument("--us-period", type=int, default=20)
    ap.add_argument("--chars", default=",".join(sorted(ALL_CHARS)),
                    help="가드 적용 캐릭터(쉼표구분, validate 모드용)")
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    bundle = _load_bundle(start, end, args.kr_top, args.us_top, Path(args.cache))

    lines = [f"# 가드 스윕 {start}~{end} (kr_top={args.kr_top}, us_top={args.us_top})", "",
             "| 설정 | 캐릭터 | TWR % | MDD % | 거래수 |", "|---|---|---|---|---|"]
    off = run_replay(_cfg(20, 20, frozenset()), bundle, start, end)
    lines += _md_rows("OFF", off.summary)
    print("[sweep] OFF 기준 완료")

    if args.validate:
        chars = frozenset(c for c in args.chars.split(",") if c)
        res = run_replay(_cfg(args.kr_period, args.us_period, chars), bundle, start, end)
        lines += _md_rows(f"ON kr={args.kr_period} us={args.us_period} chars={','.join(sorted(chars))}",
                          res.summary)
    else:
        runs = []
        for kr_p, us_p in itertools.product(PERIODS, PERIODS):
            res = run_replay(_cfg(kr_p, us_p, ALL_CHARS), bundle, start, end)
            runs.append({"kr": kr_p, "us": us_p, "summary": res.summary})
            lines += _md_rows(f"ON kr={kr_p} us={us_p}", res.summary)
            print(f"[sweep] kr={kr_p} us={us_p} 완료")
        kr_pick = pick_single("국내형", off.summary, runs, "kr")
        us_pick = pick_single("해외형", off.summary, runs, "us")
        uni_pick = pick_universal(off.summary, runs,
                                  kr_pick["period"] if kr_pick else None,
                                  us_pick["period"] if us_pick else None)
        lines += ["", "## 채택 규칙 자동 적용 (TWR≥OFF−1%p AND |MDD|개선 → |MDD|최소)",
                  f"- 국내형: {kr_pick or 'off (후보 없음)'}",
                  f"- 해외형: {us_pick or 'off (후보 없음)'}",
                  f"- 범용형: {uni_pick or 'off (후보 없음)'}"]

    text = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"[sweep] 저장: {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
