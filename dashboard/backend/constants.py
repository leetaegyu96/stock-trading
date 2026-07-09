"""대시보드 백엔드/시딩 스크립트가 공유하는 전역 상수.

fx_rate 는 카드 요약(summary.card_summary)과 리플레이 시딩(seed_from_replay)이
반드시 같은 값을 써야 총자산 정합(§6.3)이 성립한다 — 별도로 하드코딩하면
두 값이 갈라져 카드 총자산과 자산곡선 마지막 값이 어긋난다(과거 실제 발생).
"""
from __future__ import annotations

FALLBACK_FX_RATE = 1300.0
