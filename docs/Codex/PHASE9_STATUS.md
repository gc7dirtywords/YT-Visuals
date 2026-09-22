# Phase 9 Status

## Baseline
- Scope: locked in `PHASE9.md`; Phase 9A implemented.
- Production authority: Unraid; development root: `D:\YT-Visuals`.

## Phase 9A completed
- Added migration `0014_phase9a_story_lifecycle`: reversible archive timestamp; immutable `producer_visual_plan_revisions`; explicit current revision pointer; beat retirement/review flags; active-only beat sequence uniqueness; revision-1 backfill from each existing workspace; immutable-revision update trigger.
- Existing Story IDs now return a deterministic revision preview instead of a duplicate error. Confirmed revisions persist the original plan/hash/note, retain prior revisions, preserve beat IDs and selections/history, add/reactivate/retire beats, and flag material visual/media/source changes for review.
- Added archive/restore and normal-view archived filtering. Non-released stories may be permanently deleted after typed confirmation, including documents/timeline-bearing workspaces; shared media and append-only events are retained. Workspace files are staged before DB deletion and restored if DB deletion fails.
- Released releases now lock unassignment, reassignment, story ordering, and story deletion.
- Producer UI now renders revision preview/confirmation, revision history/current marker, archived dashboard filter, archive action, and material plan-review notices.

## Changed files
- `migrations/versions/0014_phase9a_story_lifecycle.py`
- `src/yt_visuals/models.py`, `src/yt_visuals/producer/service.py`, `src/yt_visuals/producer/web.py`
- `src/yt_visuals/producer/templates/index.html`, `src/yt_visuals/producer/templates/workspace.html`
- `tests/test_producer_workflow.py`, `tests/test_producer_web.py`, `tests/test_database.py`

## Migration state
- New head: `0014_phase9a_story_lifecycle`; focused migration/database coverage passed.
- Phase 9A commit: `7f05de9` (`feat: close Phase 9A story lifecycle`).

## Phase-boundary full suite
- `.venv\\Scripts\\pytest.exe -q`
- Result: `170 passed in 73.71s (0:01:13)`.

## Focused checks
- `.venv\Scripts\pytest.exe -q tests/test_producer_workflow.py::test_phase9a_plan_revision_archive_and_released_locks tests/test_producer_web.py tests/test_database.py`
- Result: `38 passed in 23.26s`.

## Blockers / next action
- No blockers. Phase 9A is closed; next action is Phase 9B (Storage + production files).
