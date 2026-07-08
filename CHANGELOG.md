# Changelog

이 프로젝트의 모든 주요 변경사항을 기록한다. 형식은 [Keep a Changelog](https://keepachangelog.com/), 버전은 [SemVer](https://semver.org/)를 따른다.

상세 패치노트는 `docs/patch-notes/vX.Y.Z.md` 참조.

## v1.0.0 — 2026-07-08

첫 릴리즈. simcore 백테스트/리플레이 엔진 기준선 확정 + 프로젝트 작업 규칙 정립.

### Added
- `CLAUDE.md` — git 워크플로 규칙 (논리 단위 커밋 / 브랜치 개발 / SemVer 버전업 / PR 자율 처리 / 버전마다 패치노트).
- `.gitattributes` — 전 텍스트 파일 LF 강제 (WSL/Windows CRLF 노이즈 방지).
- `CHANGELOG.md` + `docs/patch-notes/` — 버전별 변경 이력 체계.

### Changed
- 개인 GitHub 신원으로 커밋 히스토리 정규화 (`leetaegyu96 <…noreply.github.com>`), 회사 이메일 제거.

### Baseline (v1.0.0 시점 구성 요소)
- `simcore/` — 백테스트/리플레이 엔진: config, data, indicators, signals, engine, portfolio, costs, metrics, report, universe, replay.
- `tests/` — 단위/통합 테스트.
- `docs/` — 트레이딩 규칙, 실험 기록, 설계 계획.
