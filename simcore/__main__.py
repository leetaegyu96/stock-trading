"""리플레이 CLI: python -m simcore --start 2025-01-01 --end 2025-12-31"""
from __future__ import annotations
import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path
import pandas as pd

from simcore.config import Config
from simcore import data as datamod, universe, metrics
from simcore.replay import DataBundle, FlowEvent, run_replay
from simcore.engine import DEFAULT_CHARACTERS
from simcore.report import write_outputs


def parse_flows(path: str) -> list[FlowEvent]:
    df = pd.read_csv(path, dtype={"liquidate": str})
    out = []
    for _, r in df.iterrows():
        liq = tuple(str(r.get("liquidate", "")).split(";")) if pd.notna(r.get("liquidate")) and str(r.get("liquidate")) else ()
        out.append(FlowEvent(pd.Timestamp(r["date"]).date(), r["character"],
                             float(r["amount_krw"]), liq))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="simcore 과거 데이터 리플레이")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--flows", default=None, help="입출금 CSV (date,character,amount_krw,liquidate)")
    ap.add_argument("--buy-score", type=int, default=None,
                    help="매수 최소 총점(기본 18)")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--bear-guard", action="store_true",
                     help="하락장 가드 전 캐릭터 강제 on (기본: config bear_guard_characters)")
    grp.add_argument("--no-bear-guard", action="store_true",
                     help="하락장 가드 전체 강제 off")
    ap.add_argument("--kr-top", type=int, default=200, help="코스피200 중 앞 N종목")
    ap.add_argument("--us-top", type=int, default=100, help="S&P500 중 앞 N종목")
    ap.add_argument("--out", default="out")
    ap.add_argument("--cache", default="data/cache")
    args = ap.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    cfg = Config()
    if args.buy_score is not None:
        cfg = replace(cfg, rules=replace(cfg.rules, buy_score_min=args.buy_score))
    if args.bear_guard:
        cfg = replace(cfg, rules=replace(cfg.rules,
                      bear_guard_characters=frozenset(c.name for c in DEFAULT_CHARACTERS)))
    elif args.no_bear_guard:
        cfg = replace(cfg, rules=replace(cfg.rules, bear_guard_characters=frozenset()))

    cache = Path(args.cache)
    kr_syms = universe.kospi200(cache, start)[: args.kr_top]
    us_syms = universe.sp500(cache)[: args.us_top]
    print(f"[universe] KR {len(kr_syms)}종목, US {len(us_syms)}종목 로딩 중...")
    # 지수는 벤치마크(P0-3) 계산에 항상 필요 + 하락장 가드 활성 캐릭터가 있을 때도 사용됨 —
    # 가드 스위치와 무관하게 심볼이 있으면 로드
    kr_index = datamod.load_index("KR", start, end, cache) if kr_syms else None
    us_index = datamod.load_index("US", start, end, cache) if us_syms else None
    bundle = DataBundle(
        kr=datamod.load_kr_daily(kr_syms, start, end, cache),
        us=datamod.load_us_daily(us_syms, start, end, cache),
        fx=datamod.load_fx(start, end, cache),
        kr_index=kr_index,
        us_index=us_index,
    )
    flows = parse_flows(args.flows) if args.flows else []
    result = run_replay(cfg, bundle, start, end, flows=flows)

    # 벤치마크: 매수후보유 (구간 첫 종가 → 마지막 종가)
    benchmarks = {}
    try:
        from pykrx import stock
        k200 = stock.get_index_ohlcv(f"{start:%Y%m%d}", f"{end:%Y%m%d}", "1028")["종가"]
        benchmarks["KOSPI200"] = float(k200.iloc[-1] / k200.iloc[0] - 1)
    except Exception as exc:
        print(f"[benchmark] KOSPI200 실패: {exc}")
    try:
        import yfinance as yf
        spx = yf.download("^GSPC", start=start, end=end, auto_adjust=True,
                          progress=False)["Close"].squeeze()
        benchmarks["S&P500"] = float(spx.iloc[-1] / spx.iloc[0] - 1)
    except Exception as exc:
        print(f"[benchmark] S&P500 실패: {exc}")

    write_outputs(result, cfg, Path(args.out),
                  experiments_dir=Path("docs/experiments"), benchmarks=benchmarks,
                  label=f"replay_{start}_{end}")


if __name__ == "__main__":
    main()
