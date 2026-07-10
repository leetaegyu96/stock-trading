---
name: auditing-trading-product
description: Use when reviewing this repository after trading-engine or dashboard changes, especially requests to inspect Chrome, UI/UX, 16:9 layouts, trade journals, green/red signals, backtest credibility, paper trading, or readiness for real-money automation.
---

# Auditing the Trading Product

## Overview

Audit the repository as one product: code behavior, visible evidence, trading validity, beginner comprehension, and future live-trading safety. Connect every material claim to code, data, or an observed screen.

## Audit workflow

1. Read `AGENTS.md`, `README.md`, trading rules, recent commits, experiment reports, and changed files. State the operating contract: replay, paper/shadow, or live order execution.
2. Trace important values from signal calculation through engine decision, persistence, API schema, and UI wording. Compare the recorded decision with the action actually taken.
3. Use `chrome:control-chrome` when Chrome is requested. Inspect the running main page, character detail, and changed routes. Check loaded, loading, empty, error, stale-data, and disconnected states. Record URL, viewport, timestamp, and evidence.
4. Read [references/audit-checklist.md](references/audit-checklist.md) completely. Cover every required domain; report untestable items as `미검증`, never as passed.
5. Reproduce high-impact findings and run proportionate tests. Do not mutate product code unless the user separately asks for implementation.
6. Write or update a dated report using [references/report-template.md](references/report-template.md). Give Claude P0/P1/P2 tasks with evidence, impact, completion criteria, and re-verification steps.
7. Re-run the same evidence after Claude changes. Separate fixed, partially fixed, regressed, and unverified items.

## Required decision rules

- Treat impressive returns as unverified until benchmark, costs, holdout, and data integrity are established.
- Call OHLCV-derived indicators `기술적 신호` until independent news, filing, flow, or macro data is wired.
- Distinguish missing data from neutral signals, socket connectivity from quote freshness, and paper/shadow from real orders.
- Require engine actions and UI explanations to agree for partial, full, and every forced exit.
- Judge premium design by decision clarity, density, hierarchy, accessibility, and failure handling—not decorative imitation.

## Output contract

Lead with `GO`, `CONDITIONAL`, or `RED`. Provide observed evidence, strengths worth preserving, prioritized findings, Claude-ready tasks, and a re-test checklist. Include a compact 16:9 assessment and symbol-level trade-journey assessment on every dashboard audit.

## Common mistakes

- Reviewing screenshots without tracing code, or strategy math without opening the UI.
- Calling the product real-time because the socket is connected.
- Mixing selected-period return with total TWR or realized with unrealized P&L.
- Recommending more indicators without testing independence, contribution, and overfitting.
- Declaring live readiness without broker order state, reconciliation, limits, and kill switches.
