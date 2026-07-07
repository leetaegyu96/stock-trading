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
    ap.add_argument("--buy-threshold", type=int, default=None)
    ap.add_argument("--kr-top", type=int, default=200, help="코스피200 중 앞 N종목")
    ap.add_argument("--us-top", type=int, default=100, help="S&P500 중 앞 N종목")
    ap.add_argument("--out", default="out")
    ap.add_argument("--cache", default="data/cache")
    args = ap.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    cfg = Config()
    if args.buy_threshold is not None:
        cfg = replace(cfg, rules=replace(cfg.rules, buy_threshold=args.buy_threshold))

    cache = Path(args.cache)
    kr_syms = universe.kospi200(cache, start)[: args.kr_top]
    us_syms = universe.sp500(cache)[: args.us_top]
    print(f"[universe] KR {len(kr_syms)}종목, US {len(us_syms)}종목 로딩 중...")
    bundle = DataBundle(
        kr=datamod.load_kr_daily(kr_syms, start, end, cache),
        us=datamod.load_us_daily(us_syms, start, end, cache),
        fx=datamod.load_fx(start, end, cache),
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
