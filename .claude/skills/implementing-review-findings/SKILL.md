---
name: implementing-review-findings
description: Use when the user asks to act on a review or audit report in docs/reviews/ — triggers like "리뷰 내용 보고 진행해", "감사 반영해", "P0부터 진행해", "audit 반영", "review 반영", or names/pastes a docs/reviews report and says to implement it. This repo's Codex counterpart writes those reports (.agents/skills/auditing-trading-product); this skill turns them into implemented, released changes.
---

# Implementing Review Findings

## Overview

Codex audits this product and writes a dated report to `docs/reviews/` with prioritized findings (P0/P1/P2), each carrying **클로드 구현 요구** and **완료 조건**. This skill turns a selected set of those findings into merged, released changes through the project's full superpowers pipeline — not by editing code directly.

**Core principle:** the review report is the requirements source. You scope, plan, implement, review, and release against it — you do not re-derive requirements it already states, and you do not skip the pipeline just because "the fix looks obvious."

## When to Use

- User says "리뷰 내용 보고 진행해", "감사 반영해", "P0부터 진행해", "review/audit 반영", or points at a `docs/reviews/*.md` report and asks to implement it.
- A fresh Codex audit report has landed and the user wants it acted on.

Not for: producing the audit itself (that's Codex's `auditing-trading-product`), or one-off edits unrelated to a report.

## The Pipeline (do these in order — do not skip stages)

1. **Select the report.** Use the file the user named/pasted. Otherwise the **newest dated file in `docs/reviews/`** (`ls docs/reviews/`). State which report you chose in one line. Read it top to bottom — especially the P0/P1/P2 findings and any "구현 로드맵" / "승인 게이트".
2. **Determine scope from the user's trigger.** If they named a tier or items ("P0만", "P0-1·P0-2", "전부"), use exactly that. If they gave no selector, default to **all findings, highest priority tier first**. This bundle is one subproject.
3. **Brainstorm to scope, not to re-derive.** REQUIRED SUB-SKILL: `superpowers:brainstorming`. Use it to decompose the selected bundle, settle shared design decisions, and set what's out of scope — producing a short spec in `docs/superpowers/specs/` that **references the report's findings as requirements** (cite finding IDs like P0-1; don't copy their text). The report's 완료 조건 become the spec's acceptance criteria.
4. **Write the plan.** REQUIRED SUB-SKILL: `superpowers:writing-plans` → `docs/superpowers/plans/`.
5. **Execute.** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` — fresh implementer subagent per task, two-stage task review + fix loop, then the final whole-branch review. Track every task in the ledger `.superpowers/sdd/progress.md`.
6. **Finish & release.** REQUIRED SUB-SKILL: `superpowers:finishing-a-development-branch`, then follow **CLAUDE.md** for git/release: work branch off `dev` → PR to `dev` → merge + delete branch → `dev`→`main` promotion → `vX.Y.Z` tag → `CHANGELOG.md` + `docs/patch-notes/vX.Y.Z.md`.
7. **Confirm 완료 조건.** For each finding implemented, verify its report-stated 완료 조건/재검증 is actually met (drive the behavior, not just tests). Note in the final report that Codex will re-audit; list any finding left `미검증` honestly.

## Autonomy

Run the selected bundle to release **without mid-run check-ins** — scope was already chosen at trigger time. Stop only for: destructive/irreversible actions (force-push, remote branch/tag deletion), a finding whose 완료 조건 you cannot meet, or a genuine scope change the user must decide (per CLAUDE.md). Report results and version at the end.

## Common Mistakes

| Mistake | Correct |
|---|---|
| Editing code directly / manual per-fix TDD | Run the full pipeline; implementation goes through subagent-driven-development |
| Skipping `superpowers:brainstorming` and jumping to plan | Brainstorm to scope the bundle + settle design first |
| Duplicating the report's findings into a new spec | Spec **cites** finding IDs; the report stays the requirements source |
| Guessing which report / guessing scope | Newest in `docs/reviews/` unless named; scope from the trigger message |
| Forgetting the ledger | Append task progress to `.superpowers/sdd/progress.md` |
| Wandering into `AGENTS.md` / `.agents/skills/` | Those are Codex's audit side — leave them; act only on the report |
| "Code written" = done | Done = report's 완료 조건 verified + merged + released |
