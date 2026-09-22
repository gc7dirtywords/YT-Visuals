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
- New head: `0014_phase9a_story_lifecycle`; focused migration/database coverage passed; Phase 9A commit: `7f05de9`.
## Phase-boundary full suite
- `.venv\\Scripts\\pytest.exe -q`
- Result: `170 passed in 73.71s (0:01:13)`.
## Focused checks
- `.venv\Scripts\pytest.exe -q tests/test_producer_workflow.py::test_phase9a_plan_revision_archive_and_released_locks tests/test_producer_web.py tests/test_database.py`
- Result: `38 passed in 23.26s`.
## Phase 9B foundation completed
- Canonical workspace resolver added: unassigned roots are `Projects/Unassigned/<story-id>/`; assigned roots are `Releases/<release-id>/Stories/<story-id>/`.
- Assignment, reassignment, and unassignment move one authoritative workspace directory. Existing legacy `Projects/<story-id>/` locations remain readable until an explicit assignment move; a legacy/canonical collision or occupied destination is an audit blocker, so no blind migration occurs.
- Filesystem moves occur before the assignment DB commit and are reversed on commit failure. Released-release lifecycle locks remain enforced; edit folders, storyboards, documents, handoff reads, and workspace deletion now resolve the workspace location rather than assuming `Projects/<story-id>`.
- Deliberately deferred: narration audio, release transcript aggregation, and Files UI.

## Changed files
- `src/yt_visuals/producer/service.py`
- `tests/test_producer_workflow.py`
- `docs/codex/PHASE9_STATUS.md`

## Migration state / focused checks
- No database migration: placement is derived from existing story/release identity, so existing production records are preserved without a bulk path rewrite.
- `.venv\Scripts\pytest.exe -q tests/test_producer_workflow.py::test_phase9b_moves_single_workspace_between_canonical_story_roots tests/test_producer_workflow.py::test_phase9b_move_failure_keeps_assignment_and_workspace_in_place tests/test_producer_workflow.py::test_phase9b_database_failure_restores_moved_workspace`
- Result: `3 passed in 2.26s`.

## Phase 9B production artifacts completed
- Added migration `0015_story_narration_audio`, preserving existing Narration Script history while rejecting new script uploads. Narration Audio is versioned story storage for WAV/MP3/FLAC with existing browser view/play and download routes.
- New release production artifacts use canonical folders: `DaVinci/` for resolve projects, `Final/` for final renders, and `Other/` for other artifacts. Existing root-level artifact files remain readable without an unaudited move.
- Added release YouTube transcript generation and download. It uses current Subtitle TXT files in release order; requires every assigned story; rejects unreadable/empty/obviously marked-up input; writes BOM-free UTF-8 with blank-line separation to `Captions/<release-id>_YouTube_Transcript.txt`.
- Deliberately deferred: broader Files/browser UI and presentation-file materialization.

## Changed files
- `migrations/versions/0015_story_narration_audio.py`, `src/yt_visuals/models.py`
- `src/yt_visuals/producer/service.py`, `src/yt_visuals/producer/web.py`
- `src/yt_visuals/producer/templates/workspace.html`, `src/yt_visuals/producer/templates/release.html`
- `tests/test_producer_workflow.py`, `docs/codex/PHASE9_STATUS.md`

## Migration state / focused checks
- New head: `0015_story_narration_audio`; migration only expands the document-type check constraint and preserves existing rows.
- `.venv\Scripts\pytest.exe -q tests/test_producer_workflow.py::test_phase9b_audio_release_artifacts_and_transcript tests/test_producer_workflow.py::test_phase9b_transcript_requires_valid_subtitles`
- Result: `2 passed in 1.79s`.

## Blockers / next action
- Phase 9B commit: `fc80154` (`feat: close Phase 9B storage and browser files`).
- Migration head: `0015_story_narration_audio`.
- Final full suite: `.venv\Scripts\pytest.exe -q` → `176 passed in 82.07s (0:01:22)`.
- No blockers. Phase 9B is closed; next action is Phase 9C (Beat production UX).

## Phase 9B Files/browser access completed
- Added browser-based Files views from story and release pages, opened in a new tab.
- Files views list the canonical story/release hierarchy and support inline View/Play, Download, and Download Folder as ZIP.
- Reused canonical workspace resolution, including readable legacy story paths; guarded file access against traversal and symlink escapes.

## Changed files
- `src/yt_visuals/producer/service.py`, `src/yt_visuals/producer/web.py`
- `src/yt_visuals/producer/templates/files.html`, `src/yt_visuals/producer/templates/workspace.html`, `src/yt_visuals/producer/templates/release.html`
- `tests/test_producer_web.py`

## Files/browser focused check
- `.venv\Scripts\pytest.exe -q tests/test_producer_web.py::test_browser_files_view_supports_story_release_view_download_and_zip`
- Result: `1 passed in 1.52s`.

## Phase 9C completed
- Upload is now the first, expanded acquisition panel. Local Library follows as a collapsed, compact-thumbnail panel; existing acquisition routes/components are unchanged.
- Recommended Searches now appear before SFX. Collapsed beat headers show `SFX —`, `SFX !`, or `SFX ✓` for no recommendation, outstanding work, or selected/skipped resolution.
- Added explicit producer SFX skip state. A beat auto-collapses only when a visual is selected and SFX is selected/skipped or not recommended; unresolved recommended SFX remains open. The toolbar collapse control follows the same rule.

## Changed files
- `migrations/versions/0016_beat_sfx_skip.py`, `src/yt_visuals/models.py`
- `src/yt_visuals/producer/service.py`, `src/yt_visuals/producer/web.py`
- `src/yt_visuals/producer/templates/workspace.html`, `src/yt_visuals/producer/static/producer.js`, `src/yt_visuals/producer/static/producer.css`
- `tests/test_producer_web.py`, `docs/codex/PHASE9_STATUS.md`

## Migration state / focused checks
- New head: `0016_beat_sfx_skip`; it adds nullable `producer_beats.sfx_skipped_at` and preserves all existing selections/history.
- `.venv\Scripts\pytest.exe -q tests/test_producer_web.py::test_phase9c_upload_first_and_sfx_resolution_controls tests/test_producer_web.py::test_completed_beats_default_collapsed_and_focus_expands tests/test_producer_web.py::test_workspace_renders_sticky_progress_navigation_and_external_import`
- Result: `3 passed in 3.10s`.

## Blockers / next action
- Phase 9C commit: `e14641e` (`feat: close Phase 9C beat production UX`).
- Migration head: `0016_beat_sfx_skip`.
- Final full suite: `.venv\Scripts\pytest.exe -q` → `177 passed in 82.78s (0:01:22)`.
- No blockers. Phase 9 is complete; next action is outside Phase 9 scope.
