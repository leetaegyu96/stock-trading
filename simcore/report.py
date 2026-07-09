"""리플레이 결과 출력: CSV + 콘솔 요약 + docs/experiments 실험 기록."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import pandas as pd

from simcore.config import Config
from simcore.replay import ReplayResult


def write_outputs(result: ReplayResult, config: Config, out_dir: Path,
                  experiments_dir: Path | None = None,
                  benchmarks: dict[str, float] | None = None,
                  label: str = "replay") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result.trades.to_csv(out / "trades.csv", index=False, encoding="utf-8-sig")
    result.equity.to_csv(out / "equity_curve.csv", encoding="utf-8-sig")
    result.green_hist.rename("green_score").to_csv(out / "signal_distribution.csv",
                                                    encoding="utf-8-sig")
    lines = [f"# {label} 결과", "", "| 캐릭터 | TWR | MDD | 손익(KRW) | 거래수 |",
             "|---|---|---|---|---|"]
    for name, s in result.summary.items():
        lines.append(f"| {name} | {s['twr']:+.2%} | {s['mdd']:.2%} "
                     f"| {s['pnl_krw']:+,.0f} | {s['n_trades']} |")
    if benchmarks:
        lines += ["", "## 벤치마크 (매수후보유)", ""]
        lines += [f"- {k}: {v:+.2%}" for k, v in benchmarks.items()]
    lines += ["", "## 신호 점수 분포 (청신호 총점별 종목-일 수)", "",
              "", result.green_hist.to_string(), "", "## 설정 스냅샷", "",
              "```python", repr(asdict(config)), "```"]
    text = "\n".join(lines)
    print(text)
    if experiments_dir is not None:
        exp = Path(experiments_dir)
        exp.mkdir(parents=True, exist_ok=True)
        seq = len(list(exp.glob(f"{label}_*.md"))) + 1
        (exp / f"{label}_{seq:03d}.md").write_text(text, encoding="utf-8")
