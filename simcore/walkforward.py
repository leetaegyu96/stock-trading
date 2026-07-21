"""워크포워드(롤링 아웃오브샘플) 검증 하니스.

기존 ``simcore/replay.py::run_replay`` 와 ``simcore/metrics.py::risk_metrics`` 를 재사용해
전체 구간을 롤링 test 폴드로 나누고 각 폴드를 독립적인 아웃오브샘플로 평가한다.

범위 한정(설계 스펙 참조): 폴드별 파라미터 재적합은 하지 않는다(엄밀한 WFO가 아니라
롤링 OOS 평가). ``Config`` 는 전 폴드 공통으로 고정.
"""
from __future__ import annotations
import argparse
import statistics
from dataclasses import dataclass, field
from datetime import date as Date, timedelta
from pathlib import Path

import pandas as pd

from simcore.config import Config
from simcore import metrics
from simcore.replay import DataBundle, run_replay


@dataclass(frozen=True)
class Fold:
    index: int
    test_start: Date
    test_end: Date


@dataclass
class WalkForwardResult:
    folds: list[dict]
    aggregate: dict


def generate_folds(start: Date, end: Date, test_days: int = 63, step_days: int = 63,
                    warmup_days: int = 120) -> list[Fold]:
    """[start, end] 를 워밍업 이후부터 ``step_days`` 간격의 ``test_days`` 길이 창으로 타일링한다.

    - 첫 test_start = start + warmup_days.
    - 마지막 폴드의 test_end 는 end 를 넘지 않게 자른다.
    - 잘려서 test 창 길이가 test_days//2 미만이 되면 그 폴드는 제외한다.
    - 순수 함수(날짜/네트워크 의존 없음), 결정론적.
    """
    min_len = test_days // 2
    folds: list[Fold] = []
    test_start = start + timedelta(days=warmup_days)
    idx = 0
    while test_start < end:
        test_end = min(test_start + timedelta(days=test_days), end)
        window_len = (test_end - test_start).days
        if window_len >= min_len:
            folds.append(Fold(index=idx, test_start=test_start, test_end=test_end))
            idx += 1
        test_start = test_start + timedelta(days=step_days)
    return folds


def _aggregate(folds: list[dict]) -> dict:
    """폴드 dict 리스트(각 {index, test_start, test_end, per_char:{name:{...}}})에서
    캐릭터별 폴드 간 일관성 지표를 계산하는 순수 함수."""
    per_char_metrics: dict[str, list[dict]] = {}
    for f in folds:
        for name, m in f["per_char"].items():
            per_char_metrics.setdefault(name, []).append(m)

    agg: dict[str, dict] = {}
    for name, items in per_char_metrics.items():
        twrs = [it["twr"] for it in items]
        sharpes = [it["sharpe"] for it in items]
        mdds = [it["mdd"] for it in items]
        n = len(items)
        agg[name] = {
            "mean_twr": statistics.mean(twrs) if twrs else 0.0,
            "std_twr": statistics.stdev(twrs) if len(twrs) > 1 else 0.0,
            "pct_profitable_folds": (sum(1 for t in twrs if t > 0) / n) if n else 0.0,
            "mean_sharpe": statistics.mean(sharpes) if sharpes else 0.0,
            "worst_mdd": max((abs(m) for m in mdds), default=0.0),
            "n_folds": n,
        }
    return {"per_char": agg}


def run_walkforward(config: Config, bundle: DataBundle, folds: list[Fold]) -> WalkForwardResult:
    fold_dicts: list[dict] = []
    for fold in folds:
        try:
            res = run_replay(config, bundle, fold.test_start, fold.test_end)
        except ValueError as exc:
            print(f"[walkforward] fold {fold.index} ({fold.test_start}~{fold.test_end}) "
                  f"건너뜀: {exc}")
            continue

        per_char: dict[str, dict] = {}
        for name, summ in res.summary.items():
            eq = res.equity[name]
            char_trades = (res.trades[res.trades.character == name]
                           if not res.trades.empty else res.trades)
            rm = metrics.risk_metrics(eq, trades=char_trades,
                                      flows=res.flows_by_char.get(name))
            sells = (char_trades[char_trades.side == "SELL"]
                     if not char_trades.empty else char_trades)
            win_rate = float((sells["realized_pnl"] > 0).mean()) if len(sells) > 0 else 0.0
            per_char[name] = {
                "twr": summ["twr"],
                "mdd": summ["mdd"],
                "sharpe": rm["sharpe"],
                "win_rate": win_rate,
                "n_trades": summ["n_trades"],
            }

        fold_dicts.append({
            "index": fold.index,
            "test_start": fold.test_start,
            "test_end": fold.test_end,
            "per_char": per_char,
        })

    aggregate = _aggregate(fold_dicts)
    return WalkForwardResult(folds=fold_dicts, aggregate=aggregate)


# ---------------------------------------------------------------- CLI

def _format_report(result: WalkForwardResult) -> str:
    lines = ["# 워크포워드(롤링 OOS) 검증 리포트", ""]
    lines.append("## 폴드별")
    lines.append("")
    lines.append("| fold | test_start | test_end | character | twr | mdd | sharpe | win_rate | n_trades |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for fold in result.folds:
        for name, m in fold["per_char"].items():
            lines.append(f"| {fold['index']} | {fold['test_start']} | {fold['test_end']} | "
                         f"{name} | {m['twr']:.4f} | {m['mdd']:.4f} | {m['sharpe']:.3f} | "
                         f"{m['win_rate']:.2f} | {m['n_trades']} |")
    lines.append("")
    lines.append("## 집계 (폴드 간 일관성)")
    lines.append("")
    lines.append("| character | mean_twr | std_twr | pct_profitable_folds | mean_sharpe | worst_mdd | n_folds |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, a in result.aggregate["per_char"].items():
        lines.append(f"| {name} | {a['mean_twr']:.4f} | {a['std_twr']:.4f} | "
                     f"{a['pct_profitable_folds']:.2f} | {a['mean_sharpe']:.3f} | "
                     f"{a['worst_mdd']:.4f} | {a['n_folds']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    from simcore import data as datamod, universe

    ap = argparse.ArgumentParser(description="워크포워드(롤링 OOS) 검증")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--test-days", type=int, default=63)
    ap.add_argument("--step-days", type=int, default=63)
    ap.add_argument("--warmup-days", type=int, default=120)
    ap.add_argument("--kr-top", type=int, default=30)
    ap.add_argument("--us-top", type=int, default=30)
    ap.add_argument("--cache", default="data/cache")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    start, end = Date.fromisoformat(args.start), Date.fromisoformat(args.end)
    cfg = Config()

    cache = Path(args.cache)
    kr_syms = universe.kospi200(cache, start)[: args.kr_top]
    us_syms = universe.sp500(cache)[: args.us_top]
    print(f"[universe] KR {len(kr_syms)}종목, US {len(us_syms)}종목 로딩 중...")
    kr_index = datamod.load_index("KR", start, end, cache) if kr_syms else None
    us_index = datamod.load_index("US", start, end, cache) if us_syms else None
    bundle = DataBundle(
        kr=datamod.load_kr_daily(kr_syms, start, end, cache),
        us=datamod.load_us_daily(us_syms, start, end, cache),
        fx=datamod.load_fx(start, end, cache),
        kr_index=kr_index,
        us_index=us_index,
    )

    folds = generate_folds(start, end, test_days=args.test_days, step_days=args.step_days,
                           warmup_days=args.warmup_days)
    print(f"[walkforward] {len(folds)}개 폴드 생성됨")
    result = run_walkforward(cfg, bundle, folds)

    report = _format_report(result)
    print(report)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"[walkforward] 리포트 저장: {out_path}")


if __name__ == "__main__":
    main()
