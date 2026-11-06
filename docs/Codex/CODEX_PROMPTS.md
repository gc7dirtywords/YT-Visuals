# Phase 9 Codex Prompts

Keep prompts short. Requirements already live in PHASE9.md.

## First turn - 9A audit only

Read Docs/Codex/PHASE9.md, PHASE9_CONTEXT.md, and PHASE9_STATUS.md. Audit only Phase 9A. Identify the exact models/services/routes/templates/tests/migrations that must change, current FK/delete blockers, and the smallest safe revisioning design that fits the existing schema. Do not edit code. Update PHASE9_STATUS.md with the audit result. Response <= 12 lines.

## 9A implementation

Implement Phase 9A exactly as locked in Docs/Codex/PHASE9.md, using the prior audit in PHASE9_STATUS.md. Keep schema/service/UI changes minimal and preserve existing history. Add focused regression tests. Do not touch Phase 9B/9C. Update PHASE9_STATUS.md. Response <= 12 lines.

## 9B implementation

Implement Phase 9B exactly as locked in Docs/Codex/PHASE9.md. Before moving any existing file, verify current DB/path assumptions from PHASE9_CONTEXT.md and code. Migration must be rollback-safe and must not create duplicate authoritative story copies. Add focused tests. Do not touch 9C. Update PHASE9_STATUS.md. Response <= 12 lines.

## 9C implementation

Implement Phase 9C exactly as locked in Docs/Codex/PHASE9.md. UI-only unless a minimal state helper is required. Preserve current behavior outside the listed UX changes. Add/update focused tests. Update PHASE9_STATUS.md. Response <= 12 lines.

## Review turn

Review only the current phase diff against Docs/Codex/PHASE9.md. Look for data-loss risk, broken path assumptions, FK/cascade mistakes, revision-history loss, and missing focused tests. Do not refactor unrelated code. Fix only confirmed issues. Update PHASE9_STATUS.md. Response <= 12 lines.
