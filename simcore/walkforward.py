"""워크포워드(롤링 아웃오브샘플) 검증 하니스.

기존 ``simcore/replay.py::run_replay`` 와 ``simcore/metrics.py::risk_metrics`` 를 재사용해
전체 구간을 롤링 test 폴드로 나누고 각 폴드를 독립적인 아웃오브샘플로 평가한다.

범위 한정(설계 스펙 참조): 폴드별 파라미터 재적합은 하지 않는다(엄밀한 WFO가 아니라
롤링 OOS 평가). ``Config`` 는 전 폴드 공통으로 고정.
"""
from __future__ import annotations
import argparse
import itertools
import math
import statistics
from dataclasses import dataclass, field, replace
from datetime import date as Date, timedelta
from pathlib import Path

import pandas as pd

from simcore.config import Config
from simcore import metrics
from simcore.replay import DataBundle, ReplayResult, run_replay


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


# =============================================================================
# 진짜 워크포워드 최적화(WFO) + 과적합확률(PBO) — 이슈 #30
#
# 위 run_walkforward 는 폴드별 재적합 없이 고정 Config 로 OOS 만 평가하는 "롤링 OOS 검증"이다.
# 아래는 각 폴드의 train 구간에서 파라미터(buy_score_min)를 그리드 탐색하고, 선택된 파라미터를
# test 구간에서 OOS 평가하는 진짜 WFO 를 추가한다. 기존 Fold/generate_folds/run_walkforward/
# _aggregate 는 시그니처·동작 불변(하위호환) — 신규 함수로만 확장한다.
# =============================================================================

@dataclass(frozen=True)
class OptFold:
    index: int
    train_start: Date
    train_end: Date
    test_start: Date
    test_end: Date


def generate_opt_folds(start: Date, end: Date, train_days: int = 252, test_days: int = 63,
                        step_days: int = 63) -> list[OptFold]:
    """[start, end] 를 train(train_days)+test(test_days) 쌍으로 롤링 타일링한다(진짜 WFO용).

    - train 구간 = [test_start - train_days, test_start) — test 직전까지의 학습 구간.
    - 첫 test_start = start + train_days.
    - 마지막 폴드의 test_end 는 end 를 넘지 않게 자른다.
    - 잘려서 test 창 길이가 test_days//2 미만이 되면 그 폴드는 제외한다.
    - 순수 함수(날짜/네트워크 의존 없음), 결정론적. 기존 generate_folds 는 변경하지 않는다.
    """
    min_len = test_days // 2
    folds: list[OptFold] = []
    test_start = start + timedelta(days=train_days)
    idx = 0
    while test_start < end:
        test_end = min(test_start + timedelta(days=test_days), end)
        window_len = (test_end - test_start).days
        if window_len >= min_len:
            train_start = test_start - timedelta(days=train_days)
            folds.append(OptFold(index=idx, train_start=train_start, train_end=test_start,
                                  test_start=test_start, test_end=test_end))
            idx += 1
        test_start = test_start + timedelta(days=step_days)
    return folds


@dataclass
class WfoResult:
    folds: list[dict]
    wfo_efficiency: float
    pbo: float
    grid: list
    objective: str
    character: str


def _objective(res: ReplayResult, character: str, objective: str) -> float:
    """폴드 성과에서 목적함수 값을 뽑아내는 순수 헬퍼.

    character 가 결과에 없으면(엔진 상태에 없는 캐릭터명 등) -inf 를 반환해
    grid-search 에서 자동으로 배제되게 한다.
    """
    if character not in res.summary:
        return float("-inf")
    if objective == "sharpe":
        eq = res.equity[character]
        char_trades = (res.trades[res.trades.character == character]
                       if not res.trades.empty else res.trades)
        rm = metrics.risk_metrics(eq, trades=char_trades,
                                  flows=res.flows_by_char.get(character))
        return rm["sharpe"]
    return res.summary[character]["twr"]


def _wfo_efficiency(fold_dicts: list[dict]) -> float:
    """WFO 효율(mean OOS / mean IS-best)을 폴드 단위로 페어링해서 계산하는 순수 헬퍼.

    ``is_best_perf`` 와 ``oos_perf`` 를 독립적으로 필터링해 평균 내면, 한쪽만 실패한
    폴드(train은 성공했지만 test 구간에서 ValueError 로 -inf가 기록된 경우 등) 때문에
    분자·분모가 서로 다른 폴드 집합을 대표하게 되어 비율이 무의미해진다. 이를 막기 위해
    두 값이 모두 유한(finite)한 폴드만 페어링해서 사용한다.

    페어링된 폴드가 없거나 mean_is == 0 이면(비율 계산 불가) float("nan") 을 반환한다
    (PBO의 "계산 불가 시 nan" 관례와 일관).
    """
    paired = [(f["is_best_perf"], f["oos_perf"]) for f in fold_dicts
              if math.isfinite(f["is_best_perf"]) and math.isfinite(f["oos_perf"])]
    if not paired:
        return float("nan")
    mean_is = statistics.mean(v for v, _ in paired)
    mean_oos = statistics.mean(v for _, v in paired)
    if mean_is == 0:
        return float("nan")
    return mean_oos / mean_is


def run_wfo(config: Config, bundle: DataBundle, folds: list[OptFold], grid: list,
            objective: str = "twr", character: str = "국내형") -> WfoResult:
    """진짜 워크포워드 최적화: 폴드별 train 구간에서 ``grid`` 를 탐색해 최적 ``buy_score_min`` 을
    고르고(IS), 그 파라미터로 test 구간을 평가한다(OOS). ``run_replay``/``risk_metrics`` 재사용.

    반환된 폴드별 dict 에는 PBO 계산에 필요한 전 그리드값의 IS/OOS 성과가 모두 담긴다
    (``is_perf``, ``oos_all``).
    """
    fold_dicts: list[dict] = []
    is_matrix: dict = {v: {} for v in grid}
    oos_matrix: dict = {v: {} for v in grid}

    for fold in folds:
        is_perf: dict = {}
        for v in grid:
            cfg_v = replace(config, rules=replace(config.rules, buy_score_min=v))
            try:
                res_is = run_replay(cfg_v, bundle, fold.train_start, fold.train_end)
                perf = _objective(res_is, character, objective)
            except ValueError as exc:
                print(f"[wfo] fold {fold.index} buy_score_min={v} (train) 스킵: {exc}")
                perf = float("-inf")
            is_perf[v] = perf
            is_matrix[v][fold.index] = perf

        is_best = max(is_perf, key=lambda v: is_perf[v])
        is_best_perf = is_perf[is_best]

        oos_all: dict = {}
        for v in grid:
            cfg_v = replace(config, rules=replace(config.rules, buy_score_min=v))
            try:
                res_oos = run_replay(cfg_v, bundle, fold.test_start, fold.test_end)
                perf = _objective(res_oos, character, objective)
            except ValueError as exc:
                print(f"[wfo] fold {fold.index} buy_score_min={v} (test) 스킵: {exc}")
                perf = float("-inf")
            oos_all[v] = perf
            oos_matrix[v][fold.index] = perf

        fold_dicts.append({
            "index": fold.index,
            "train_start": fold.train_start, "train_end": fold.train_end,
            "test_start": fold.test_start, "test_end": fold.test_end,
            "is_perf": is_perf, "is_best": is_best, "is_best_perf": is_best_perf,
            "oos_perf": oos_all[is_best], "oos_all": oos_all,
        })

    pbo = probability_of_backtest_overfitting(is_matrix, oos_matrix)
    wfo_efficiency = _wfo_efficiency(fold_dicts)

    return WfoResult(folds=fold_dicts, wfo_efficiency=wfo_efficiency, pbo=pbo,
                     grid=list(grid), objective=objective, character=character)


def _to_config_fold_dict(matrix):
    """is_matrix/oos_matrix 입력(dict-of-dict, dict-of-sequence, 2D 시퀀스)을
    (config 키 목록, {config: {fold: value}}, fold 키 목록) 으로 정규화한다."""
    if isinstance(matrix, dict):
        configs = list(matrix.keys())
        if not configs:
            return configs, {}, []
        first = matrix[configs[0]]
        if isinstance(first, dict):
            folds = list(first.keys())
            return configs, matrix, folds
        folds = list(range(len(first)))
        by_cf = {c: {f: v for f, v in enumerate(vals)} for c, vals in matrix.items()}
        return configs, by_cf, folds
    configs = list(range(len(matrix)))
    folds = list(range(len(matrix[0]))) if matrix else []
    by_cf = {c: {f: v for f, v in enumerate(row)} for c, row in enumerate(matrix)}
    return configs, by_cf, folds


def probability_of_backtest_overfitting(is_matrix, oos_matrix, max_combos: int = 200) -> float:
    """PBO(과적합확률) — López de Prado CSCV 의 경량판(폴드 이분 조합).

    입력: config(그리드값)×폴드 성과 행렬 2개(IS/OOS). dict-of-dict ``{config: {fold: value}}``
    또는 config 키/폴드 순서가 일치하는 2D 시퀀스([config][fold])를 받는다.

    폴드를 두 동일 크기 그룹(J, J_bar)으로 나누는 모든 조합 C(S, S//2) 에 대해:
      1) J 에서 평균 IS 성과가 가장 높은 config(IS-best)를 고른다.
      2) J_bar 에서 전 config 의 평균 OOS 성과를 오름차순(꼴찌=1등급) 순위 매기고,
         IS-best 의 상대순위 ω = rank/(N_configs+1) ∈ (0,1) 를 구한다.
      3) λ = logit(ω) = ln(ω/(1-ω)).
    PBO = P(λ ≤ 0) = ω ≤ 0.5 인 분할의 비율 — "IS 최적이 OOS 중앙값 이하로 떨어지는 빈도".

    조합 수가 ``max_combos`` 를 넘으면 결정론적으로(itertools.combinations 열거 순서) 앞에서부터
    ``max_combos`` 개만 표본화하고 그 사실을 로그로 남긴다.

    가드: 폴드 수 S<2 또는 config 수<2 면 계산 불가 → float("nan") 반환.
    """
    configs, is_by_cf, folds = _to_config_fold_dict(is_matrix)
    _, oos_by_cf, _ = _to_config_fold_dict(oos_matrix)

    n_configs = len(configs)
    n_folds = len(folds)
    if n_folds < 2 or n_configs < 2:
        return float("nan")

    half = n_folds // 2
    all_combos = list(itertools.combinations(range(n_folds), half))
    total_combos = len(all_combos)
    if total_combos > max_combos:
        print(f"[pbo] 폴드 이분 조합 수 {total_combos}개가 상한 {max_combos}개를 초과해 "
              f"결정론적으로 앞에서부터 {max_combos}개만 표본화합니다.")
        all_combos = all_combos[:max_combos]

    eps = 1e-6
    lam_leq_zero = 0
    n_splits = 0
    for j_idx in all_combos:
        j_set = set(j_idx)
        jbar_idx = [i for i in range(n_folds) if i not in j_set]
        if not jbar_idx:
            continue
        j_folds = [folds[i] for i in j_idx]
        jbar_folds = [folds[i] for i in jbar_idx]

        is_means = {c: statistics.mean(is_by_cf[c][f] for f in j_folds) for c in configs}
        is_best = max(is_means, key=lambda c: is_means[c])

        oos_means = {c: statistics.mean(oos_by_cf[c][f] for f in jbar_folds) for c in configs}
        ranked = sorted(configs, key=lambda c: oos_means[c])  # 오름차순: 꼴찌가 앞
        rank = ranked.index(is_best) + 1  # 1..n_configs
        omega = rank / (n_configs + 1)
        omega = min(max(omega, eps), 1 - eps)
        lam = math.log(omega / (1 - omega))
        if lam <= 0:
            lam_leq_zero += 1
        n_splits += 1

    if n_splits == 0:
        return float("nan")
    return lam_leq_zero / n_splits


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


def _format_wfo_report(result: WfoResult) -> str:
    lines = ["# 워크포워드 최적화(WFO) + 과적합확률(PBO) 리포트", ""]
    lines.append(f"- objective: `{result.objective}` / character: `{result.character}` / "
                 f"grid(buy_score_min): {result.grid}")
    lines.append("- 탐색 축은 `buy_score_min` 단일 파라미터로 한정된다(다축·완전 CPCV·DSR 은 후속 이슈).")
    lines.append("")
    lines.append("## 폴드별 (train → IS 그리드탐색 / test → OOS 평가)")
    lines.append("")
    lines.append("| fold | train_start | train_end | test_start | test_end | "
                 "is_best(buy_score_min) | is_best_perf | oos_perf |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for f in result.folds:
        lines.append(f"| {f['index']} | {f['train_start']} | {f['train_end']} | "
                     f"{f['test_start']} | {f['test_end']} | {f['is_best']} | "
                     f"{f['is_best_perf']:.4f} | {f['oos_perf']:.4f} |")
    lines.append("")
    lines.append("## 요약")
    lines.append("")
    pbo_str = "n/a (폴드 또는 그리드 수 부족)" if math.isnan(result.pbo) else f"{result.pbo:.3f}"
    lines.append(f"- WFO 효율 (mean OOS / mean IS-best): {result.wfo_efficiency:.4f}")
    lines.append(f"- 과적합확률 PBO (CSCV 경량판): {pbo_str}")
    return "\n".join(lines) + "\n"


def main() -> None:
    from simcore import data as datamod, universe

    ap = argparse.ArgumentParser(description="워크포워드(롤링 OOS) 검증 / WFO+PBO")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--test-days", type=int, default=63)
    ap.add_argument("--step-days", type=int, default=63)
    ap.add_argument("--warmup-days", type=int, default=120)
    ap.add_argument("--kr-top", type=int, default=30)
    ap.add_argument("--us-top", type=int, default=30)
    ap.add_argument("--cache", default="data/cache")
    ap.add_argument("--out", default=None)
    ap.add_argument("--wfo", action="store_true",
                    help="진짜 워크포워드 최적화(폴드별 train 그리드탐색 → test OOS) + PBO 모드")
    ap.add_argument("--train-days", type=int, default=252, help="--wfo 모드의 train 구간 길이(일)")
    ap.add_argument("--grid", default="12,14,16,18,20",
                    help="--wfo 모드의 buy_score_min 그리드(콤마구분 정수)")
    ap.add_argument("--objective", default="twr", choices=["twr", "sharpe"],
                    help="--wfo 모드의 목적함수")
    ap.add_argument("--character", default="국내형", help="--wfo 모드의 대상 캐릭터")
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

    if args.wfo:
        opt_folds = generate_opt_folds(start, end, train_days=args.train_days,
                                       test_days=args.test_days, step_days=args.step_days)
        print(f"[wfo] {len(opt_folds)}개 최적화 폴드(train+test) 생성됨")
        grid = [int(x) for x in args.grid.split(",")]
        result = run_wfo(cfg, bundle, opt_folds, grid, objective=args.objective,
                         character=args.character)

        report = _format_wfo_report(result)
        print(report)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(report, encoding="utf-8")
            print(f"[wfo] 리포트 저장: {out_path}")
        return

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
