# AGENTS.md

이 저장소에서 Codex가 지켜야 할 작업 규칙. **사용자는 git 운영에 신경 쓰지 않는다.** 아래 워크플로를 Codex가 스스로 끝까지 처리한다.

---

## Git 신원 (자동)

- 이 리포는 **개인 GitHub** (`git@github.com:leetaegyu96/stock-trading.git`).
- 커밋 신원은 상위 `~/.gitconfig`의 `includeIf`로 자동 적용됨 → `leetaegyu96 <leetaegyu96@users.noreply.github.com>`.
- **회사 이메일(`ltk@agencygo.net`)이 커밋/히스토리에 절대 들어가지 않도록** 항상 확인한다.

---

## 핵심 원칙

> Codex가 **스스로** 작업 브랜치 생성 → 개발 → 논리 단위 커밋 → PR → `dev` 병합 → 브랜치 삭제, 그리고 릴리즈 시 `dev`→`main` 승격 → 버전 태그 → 패치노트까지 전 과정을 수행하고 이력을 남긴다. 사용자에게 git 관련 승인을 매번 요청하지 않는다.

---

## 1. 커밋 — 논리적 단위로

- 하나의 논리적 변경 = 하나의 커밋. 여러 관심사를 한 커밋에 섞지 않는다.
- 커밋 메시지는 기존 컨벤션(한국어 + 타입 접두어) 유지:
  - `feat:` 기능 추가 / `fix:` 버그 수정 / `docs:` 문서 / `chore:` 잡무 / `refactor:` / `test:`
  - 예) `feat: 손절 임계값 파라미터화`
- 작업하면서 논리 단위가 완성될 때마다 커밋한다.

## 2. 푸시 — 모아서

- 커밋마다 푸시하지 않는다. 논리적으로 완결된 묶음(또는 PR/머지 시점)에 모아서 푸시한다.

## 3. 브랜치 모델 — Git Flow (main / dev)

두 개의 영속 브랜치를 둔다:

- **`main`** — 안정 릴리즈 라인. **버전 태그(`vX.Y.Z`)는 여기에만** 찍힌다. `dev`에서 안정화된 것만 승격(merge)된다.
- **`dev`** — 통합/개발 브랜치. 일상 작업은 전부 여기로 모인다. 최신 작업본.

작업 규칙:

- **`main`·`dev`에 직접 커밋하지 않는다.** 항상 작업 브랜치를 만들어 개발한다.
- 작업 브랜치는 **`dev`에서 분기**하고, 완료되면 **`dev`로 병합**한다.
  - `feature/<요약>` — 기능
  - `fix/<요약>` — 버그 수정
  - `chore/<요약>` — 잡무/설정
- **머지가 끝난 작업 브랜치는 항상 즉시 삭제한다 (로컬 + 원격 모두).** 브랜치를 남겨두지 않는다. (`dev`·`main`은 영속이므로 삭제 대상 아님)

```
feature/* , fix/* , chore/*   ─(분기/병합)─▶  dev  ─(안정화 시 승격)─▶  main ──● vX.Y.Z 태그
```

## 4. 버전 체계 — dev에서 개발, main 승격 시 버전업

- 버전은 **SemVer** 형식 `vMAJOR.MINOR.PATCH` (예: `v1.0.0`, `v1.2.0`, `v2.0.0`).
  - **MAJOR** — 호환성 깨지는 큰 변경
  - **MINOR** — 기능 추가 (하위 호환)
  - **PATCH** — 버그 수정 / 소규모
- 개발/누적은 `dev`에서 진행한다.
- **`dev`가 릴리즈 가능한 상태가 되면 `dev` → `main`으로 승격(merge)하고, 그 시점에 `main`에서 버전을 올려 태그를 찍는다.** `main`은 항상 태그된 안정 릴리즈만 담는다.

## 5. 태그 & 이슈

- 각 버전 릴리즈마다 **git tag** (`vX.Y.Z`)를 생성하고 원격에 푸시한다.
- 작업 중 문제/버그/할 일이 생기면 **GitHub Issue를 생성**하고, 그 이슈를 참조하는 브랜치·커밋·PR로 처리한다. (`gh issue create ...`, 커밋/PR 본문에 `#<이슈번호>` 참조)

## 6. PR(=MR) 전 과정 자율 처리

- Codex가 `gh` CLI로 스스로 처리한다:
  1. `dev`에서 작업 브랜치 생성 & 개발
  2. 논리 단위 커밋
  3. `gh pr create --base dev` — PR 생성 (제목/본문에 변경 요약 + 관련 이슈 참조)
  4. `gh pr merge` — `dev`로 머지
  5. **머지된 작업 브랜치 삭제 (로컬 + 원격)**
  6. 릴리즈 시점: `dev` → `main` 승격(PR/merge) → 버전 태그 생성·푸시 → 패치노트 작성 (아래 7)
- 사용자에게 매 단계 승인을 구하지 않는다. **완료 후 결과와 버전만 보고**한다.
- 되돌리기 어렵거나 위험한 작업(강제 푸시로 원격 히스토리 덮어쓰기, 브랜치/태그 원격 삭제 등)만 사전에 확인한다.

## 7. 버전업마다 패치노트

- 버전을 올릴 때마다 패치노트를 작성한다.
- 위치: 루트 `CHANGELOG.md` (역순 누적) + 상세는 `docs/patch-notes/vX.Y.Z.md`.
- 각 항목 형식:
  ```
  ## vX.Y.Z — YYYY-MM-DD
  ### Added / Changed / Fixed / Removed
  - 변경 내용 (관련 PR #.. / 이슈 #..)
  ```
- git tag 메시지에도 핵심 요약을 넣는다.

---

## 표준 흐름 (요약)

**① 일상 개발 — dev로 모으기**
```
git switch dev && git pull
git switch -c feature/xxx           # 3. dev에서 작업 브랜치 분기
# ... 작업 ...
git commit                          # 1. 논리 단위 커밋 (여러 번)
gh pr create --base dev ...         # 6. PR 생성 (base=dev)
gh pr merge --merge ...             # 6. dev로 병합
git branch -d feature/xxx           # 작업 브랜치 삭제 (로컬)
git push origin --delete feature/xxx  # 작업 브랜치 삭제 (원격)
```

**② 릴리즈 — dev를 main으로 승격 + 버전 태그**
```
gh pr create --base main --head dev # dev → main 승격 PR
gh pr merge --merge ...             # main 병합
# CHANGELOG.md + docs/patch-notes/  # 7. 패치노트
git tag -a vX.Y.Z -m "..."          # 4,5. main에서 버전 태그
git push origin main --tags         # 2. 모아서 푸시
```
