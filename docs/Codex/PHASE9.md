# YT-ChannelOps Phase 9 - Locked Implementation Scope

This file is the canonical Phase 9 implementation brief. Do not broaden scope unless a blocker makes a locked requirement impossible.

## Product invariants

- No AI/LLM/embeddings/editorial inference inside YT-ChannelOps.
- Human producer remains authoritative.
- Preserve production history; prefer revision/retirement over destructive overwrite.
- Story ID is identity. Filesystem path is storage location, not identity.
- Unraid is authoritative production storage. Windows is development/testing only.
- Do not blindly move/delete production files. Audit current locations and references before migration.
- Keep changes narrow. No opportunistic refactors.
- Focused tests while implementing; full suite only at phase boundary.

## Phase 9A - Story lifecycle + Visual Plan revisioning

### Story lifecycle
- Add Archive Story for normal abandonment; reversible and hidden from normal production views.
- Allow permanent deletion of non-released stories even when timeline/history exists.
- Permanent delete removes story-owned DB state and story-owned files after explicit confirmation.
- Released stories are protected from destructive deletion or physical reassignment.

### Visual Plan revisions
- Importing an existing story_id is not a duplicate error. Offer/import as a new immutable Visual Plan revision.
- Preserve original imported JSON, revision number, imported_at, source hash, optional change note.
- Show a deterministic diff before commit.
- Unchanged/reordered beats keep selections/history.
- Search/guidance-only changes keep selections; flag review only when materially appropriate.
- Material desired-visual/media/source-requirement changes preserve selections/history but mark affected work for review.
- New beats are added.
- Removed beats are retired, not destroyed.
- Affected Edit Plan guidance is marked needs-review, not deleted.
- Current revision is explicit; prior revisions remain viewable.

### Acceptance
- Existing story_id can receive a new plan revision safely.
- Re-import never silently destroys selected media/history.
- Released story deletion/reassignment is blocked.
- Non-released mistaken story can be permanently deleted including timeline without FK failure.

## Phase 9B - Storage + production files

### Canonical layout

Library/ = reusable channel media
Projects/Unassigned/<story-id>/ = unassigned story workspace
Releases/<release-id>/Stories/<story-id>/ = assigned story workspace
Releases/<release-id>/Presentation/ = title, description, thumbnail
Releases/<release-id>/Captions/ = release transcript/caption artifacts
Releases/<release-id>/Final/ = final renders
Releases/<release-id>/DaVinci/ = DRP/DRA backups
Releases/<release-id>/Audio/ = release-level audio if needed
Releases/<release-id>/Other/ = miscellaneous release artifacts
Temp/ = transient files

### Assignment/storage behavior
- Assigning an unreleased story physically moves its single authoritative workspace under the release.
- Do not keep a second authoritative copy in Projects.
- Reassignment before release moves the workspace and updates DB references atomically/rollback-safe.
- Released assignment is locked so the release remains self-contained.
- Existing production files must be discovered/audited before migration. No blind moves.
- Prefer story/release root + relative artifact paths over hardcoded absolute paths.

### Story documents/audio
- Deprecate new Narration Script uploads. Existing historical files remain readable/downloadable.
- Narrator Copy remains the recording document.
- Keep story Subtitle TXT.
- Add Narration Audio as a story artifact with browser playback/download for supported formats (WAV/MP3/FLAC; M4A/AAC only if current stack supports cleanly).

### Release artifacts
- Materialize/store final title.txt, description.txt, thumbnail, final render, DRP/DRA and other release-level deliverables under the release folder.
- DB provenance/history remains authoritative for metadata/revisions while the files physically live in the canonical release hierarchy.

### Release YouTube transcript
- Generate one release-level plain TXT by concatenating each assigned story's current Subtitle TXT in release story order.
- Exact spoken text only. Never use Narrator Copy markup/headings.
- UTF-8 plain text; clean blank-line separation; avoid duplicate BOMs.
- Refuse final generation if any assigned story is missing a subtitle document.
- Validate readable UTF-8/non-empty sources and obvious narrator markup leakage before presenting as ready.
- Store under Releases/<release-id>/Captions/.

### Browser files
- Replace desktop-centric Open Folder behavior with a Files view opening in a new browser tab.
- Support View / Play / Download / Download Folder as ZIP.
- User should not need local Windows copies merely to retrieve production files.

## Phase 9C - Beat production UX

- Upload is first and expanded/default acquisition method.
- Local Library comes after Upload, collapsed by default, with compact/minimized thumbnails.
- Recommended Searches appear before SFX in beat details.
- Collapsed beat row shows SFX status icon: none when no recommendation; outstanding vs resolved when applicable.
- Auto-collapse only when beat is fully resolved:
  - visual selected, AND
  - SFX selected/skipped, or no SFX recommendation exists.
- Do not collapse while recommended SFX is unresolved.

## Implementation order

9A -> commit + full phase tests -> 9B -> commit + tests -> 9C -> commit + tests.

## Codex operating rules

- Default implementation model: Terra Medium.
- Read this file, PHASE9_CONTEXT.md, and PHASE9_STATUS.md first.
- Inspect only files relevant to the requested subtask. Do not rescan the whole repo unless a blocker requires it.
- Do not rewrite requirements back to the user.
- Do not produce long reports.
- After each task, update PHASE9_STATUS.md with: completed, changed files, checks, blocker/next step. Keep it under 80 lines.
- Response should be <= 12 lines unless a blocker requires detail.
