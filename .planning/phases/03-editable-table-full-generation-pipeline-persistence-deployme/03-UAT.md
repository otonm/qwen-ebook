---
status: diagnosed
phase: 03-editable-table-full-generation-pipeline-persistence-deployme
source: [03-01-SUMMARY.md, 03-02-SUMMARY.md, 03-03-SUMMARY.md, 03-04-SUMMARY.md, 03-05-SUMMARY.md]
started: 2026-07-12T11:04:11Z
updated: 2026-07-12T12:45:41Z
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running server/service. Clear ephemeral state (temp DBs, caches, lock files). Start the application from scratch. Server boots without errors, any seed/migration completes, and a primary query (health check, homepage load, or basic API call) returns live data.
result: issue
reported: "Ran directly against the production Quadlet deployment on the tts VM (127.0.0.1:8000, systemd-managed). `sudo systemctl restart qwen-ebook-backend.service qwen-ebook-tts.service` took the whole app down and it did NOT come back up on its own: `qwen-ebook-pod.service` was torn down as a side effect (its `ExitPolicy=stop` fires once both member containers stop) and the restart job for backend/tts did not reliably re-triger a start of the pod — systemd logged 'Bound to unit qwen-ebook-pod.service, but unit isn't active' / 'Dependency failed', leaving all three units inactive and the app fully down (curl to /healthz got connection-refused). Recovery required manually starting the units in the correct order (`systemctl start qwen-ebook-pod.service` then `qwen-ebook-tts.service` then `qwen-ebook-backend.service`) — after which /healthz returned 200 and /projects returned normally. Separately, while investigating: `qwen-ebook-backend` runs with Podman AutoRemove=true and has zero volume/bind mounts (`podman inspect` confirms empty Mounts/Binds) — the SQLite DB, uploads, and output all live only in the container's ephemeral overlay writable layer. No real projects existed at the time (list was empty), so no data was actually lost this run, but the NEXT restart that hits any real project data will silently destroy it — there is no persistent volume for `/backend` the way there is for the TTS model cache (`Volume=qwen-ebook-tts-hf-cache:...` on the tts unit has no equivalent on the backend unit)."
severity: blocker

### 2. Editable Table & Generation Pipeline (auto-covered — confirm)
expected: Four deliverables from 03-01 were fully covered by passing automated/real-GPU tests during execution, not by a manual browser session in this UAT: (D1) editable Narrator/Voice Instructions/Text cells persist on blur; (D2) per-row generate+play button synthesizes and plays a single segment's audio; (D3) content-hash cache reuses audio for an unchanged row (no re-synthesis); (D4) editing a row's text busts the cache and regenerates only that row. Confirm you have no reason to doubt these (e.g. you noticed something odd while using the table) — otherwise this passes on the existing test evidence.
result: pass

### 3. Bulk Select & Reassign Toolbar
expected: Check per-row or header select-all checkboxes in the segment table. A toolbar appears above the table showing the selection count. Choosing a character and confirming reassigns the selected rows' narrator in one action. The toolbar disappears when the selection is cleared.
result: issue
reported: "when i open the app, i only get \"Analyzing your book...\" — never reached the segment table to attempt this test. Root cause traced: browser localStorage holds a stale qwen-ebook:projectId for a project that no longer exists server-side (GET /projects returns []). The frontend opens an EventSource to /projects/{id}/analysis-stream, which 404s for a nonexistent project; the browser's native EventSource surfaces this as a generic connection error with no `data` payload, and useAnalysisStream.ts's error handler (line 74-78) treats \"no data\" as a transient network hiccup and does nothing — so the UI is stuck on the Analyzing screen forever with no path back to the project list. This blocks re-testing 3-6 in a browser until the stale localStorage entry is cleared."
severity: blocker

### 4. Config Panel (Generate All screen)
expected: The config/generate panel shows the input file, model, and output format/file; a character list with preview controls; and a live per-segment and overall progress display while generating. Once a batch has completed, the "Generate All" button relabels to "Resume Generation". If the join is blocked (e.g. a row still pending/failed), an error banner explains why.
result: issue
reported: "the preview controls on the character list have no effect. if i press generate all when a segment is beeing generated, nothing happens (no warning, no change on the ui). Traced both: (1) both characters in the live test project have preview_audio_path: null (confirmed via GET /projects/{id}) — the Play button is `disabled={!hasPreview}` in ConfigPanel.tsx's CharacterPreviewRow (line 54), so it's inert with zero explanation; preview audio is only ever generated as a side effect of editing+blurring a character's voice_instructions in the separate CastWizard screen (Review Cast), which this config panel gives no indication of and provides no way to trigger directly. (2) POST /projects/{id}/generate (ConfigPanel's handleGenerateAll) has no in-flight guard at all — generate_project in main.py unconditionally spawns a new run_batch_generation asyncio task every call, and run_batch_generation's own stale-reset step (generation_worker.py:115-124) unconditionally resets ANY row currently 'generating' back to 'pending', assuming it's a crash leftover — it can't distinguish that from a per-row generate_segment call that is genuinely in flight right now. So a second Generate All click while a row is generating (from a per-row action or an earlier batch) races an already-running task instead of being blocked or queued, and the frontend's isRunning guard (ConfigPanel.tsx:94) only reflects generation.status from the batch SSE stream, not any per-row 'generating' segment, so the button isn't even disabled in that case."
severity: major

### 5. Project List Landing & Resume
expected: Opening the app shows a Project List screen as the landing page, listing saved projects (filename, date, status) newest-first. Clicking a project opens it and resumes exactly where it was left (same segments/cast state). "New Project" starts the upload flow. An empty list shows a "No projects yet" empty state.
result: pass

### 6. Auto-Save Confirmation
expected: Editing any segment or character field (text, voice instructions, narrator assignment) commits immediately via PATCH — there is no separate Save button or action anywhere in the app.
result: issue
reported: "yes, this works. however, when i edit the segment text and then leave the field, a new generation is started. expected behavior: remove previous segment audio if present and reset the state. the user has to trigger the generation manually. Confirmed with the user this is an intentional requirement change, not a one-off annoyance: it reverses documented decision D-06 (03-CONTEXT.md) / requirement GEN-03 (REQUIREMENTS.md), which explicitly specified auto-regenerate-on-blur. patch_segment in main.py (line 556-594) currently bumps generation_version, sets generation_status='generating', and immediately fires a background regenerate_segment task on any text/voice_instructions/character_id change. New expected behavior: on edit, bump generation_version and clear the stale audio_path/reset generation_status to 'pending' (invalidate only), but do NOT auto-fire regenerate_segment — leave it pending until the user manually clicks the per-row Generate button or Generate All."
severity: major

### 7. Production Deployment Reachability
expected: Running as systemd-managed Podman Quadlet units on the production RX 9070 XT VM, the app is reachable via its tailscale serve URL from a second device on the tailnet, and NOT reachable from a device off the tailnet. A real generate request through the tailnet URL returns audible, non-silent audio.
result: pass

### 8. [coverage] Editable cells persist on blur
expected: Editable Narrator/Voice Instructions/Text cells persist on blur
result: pass
source: automated
coverage_id: 03-01-D1

### 9. [coverage] Per-row generate + play
expected: Per-row generate + play button synthesizes and plays a single segment's audio
result: pass
source: automated
coverage_id: 03-01-D2

### 10. [coverage] Content-hash cache reuse
expected: Content-hash cache reuses audio for an unchanged row (cache hit, no re-synthesis)
result: pass
source: automated
coverage_id: 03-01-D3

### 11. [coverage] Edit busts cache, regenerates one row
expected: Editing a row's text busts the cache and regenerates only that row via the version-guarded background task
result: pass
source: automated
coverage_id: 03-01-D4

### 12. [coverage] Bulk reassign updates rows + bumps version
expected: POST /segments/bulk-reassign reassigns all listed segments' narrator in one request and bumps generation_version on each
result: pass
source: automated
coverage_id: 03-02-D1

### 13. [coverage] Bulk reassign rejects cross-project target
expected: Bulk-reassign rejects a request whose target character belongs to a different project than the segments, changing nothing
result: pass
source: automated
coverage_id: 03-02-D2

### 14. [coverage] Generate All batch synthesis + join
expected: Generate All synthesizes the whole project's pending segments in order with live per-segment/overall progress, then joins into a single output file
result: pass
source: automated
coverage_id: 03-03-D1

### 15. [coverage] Interrupted batch resumes correctly
expected: An interrupted batch (crash mid-run) resumes correctly: completed rows skipped, stale generating row reset and regenerated, one failure doesn't abort the rest
result: pass
source: automated
coverage_id: 03-03-D2

### 16. [coverage] Per-row edit wins over stale batch write
expected: A per-row edit made mid-batch wins over the stale batch write for that same row (last-request-wins generation_version guard)
result: pass
source: automated
coverage_id: 03-03-D3

### 17. [coverage] GET /projects lists saved projects
expected: GET /projects lists saved projects (filename, date, status) ordered newest-first, over the existing Project table with no schema change
result: pass
source: automated
coverage_id: 03-04-D1

### 18. [coverage] Quadlet unit files translate run-local.sh
expected: Three Quadlet unit files exist under deploy/ and translate run-local.sh's podman pod create + two podman run --pod invocations with no device/port/env flag dropped
result: pass
source: automated
coverage_id: 03-05-D1

### 19. [coverage] README documents Quadlet bring-up
expected: deploy/README.md documents the Quadlet install/daemon-reload/systemctl-start/tailscale-serve bring-up plus verification steps
result: pass
source: automated
coverage_id: 03-05-D2

## Summary

total: 19
passed: 15
issues: 4
pending: 0
skipped: 0
blocked: 0

## Gaps

- truth: "Kill any running server/service, start from scratch, server boots without errors and a primary query returns live data."
  status: failed
  reason: "User reported: restarting qwen-ebook-backend.service + qwen-ebook-tts.service via systemd tore down qwen-ebook-pod.service (ExitPolicy=stop) and did not self-heal — 'Dependency failed', app stayed fully down until units were manually started in the correct order (pod, then tts, then backend). Additionally, qwen-ebook-backend runs with Podman AutoRemove=true and no volume/bind mount for its SQLite DB/uploads/output — any future restart that hits real project data will silently destroy it (no persistent state, unlike the TTS unit's HF-cache volume)."
  severity: blocker
  test: 1
  root_cause: "qwen-ebook-pod.service has ExitPolicy=stop, so it tears itself down once both member containers stop; systemd's restart job for backend+tts doesn't reliably re-trigger a start of the BindsTo-linked pod unit in the same transaction, producing 'Dependency failed'. Separately, qwen-ebook-backend.container has AutoRemove=true and declares no Volume/bind mount (unlike qwen-ebook-tts.container's qwen-ebook-tts-hf-cache volume), so its SQLite DB/uploads/output live only in the container's ephemeral overlay writable layer."
  artifacts:
    - path: "deploy/qwen-ebook.pod"
      issue: "no persistent volume declared for the backend's writable state; pod's default exit-policy tears down on last-container-stop"
    - path: "deploy/qwen-ebook-backend.container"
      issue: "no Volume= entry for /backend (DB/uploads/output), unlike the tts unit's HF-cache volume; AutoRemove implied by Podman Quadlet default"
  missing:
    - "Add a Volume= mount for the backend's persistent state directory (DB/uploads/output) in qwen-ebook-backend.container, matching the tts unit's HF-cache pattern"
    - "Fix (or document) the pod/container restart ordering so `systemctl restart` of the member containers reliably brings the pod back, or document the correct manual restart sequence (pod, then tts, then backend) in deploy/README.md"
  debug_session: ""

- truth: "Opening the app resumes the user's in-progress project or shows the project list — it never gets permanently stuck."
  status: failed
  reason: "User reported: when i open the app, i only get \"Analyzing your book...\" — never reached the segment table. Root cause: stale localStorage qwen-ebook:projectId points at a project that no longer exists server-side (GET /projects returns []); the analysis-stream 404s, but useAnalysisStream.ts's EventSource error handler (line 74-78) treats the resulting no-data error event as a transient network hiccup and silently no-ops, leaving the UI stuck on the Analyzing screen forever with no recovery path."
  severity: blocker
  test: 3
  root_cause: "The backend's /projects/{id}/analysis-stream returns a bare HTTP 404 (via _require_project_exists) for a project id that doesn't exist, which is not a valid text/event-stream response; the browser's native EventSource surfaces this as a generic connection error event with no `data` payload. useAnalysisStream.ts's error handler unconditionally treats an error event with no `data` as a transient, reconnect-eligible network blip and returns early, so the permanent 404 is silently retried forever instead of surfacing stream.status = 'error'."
  artifacts:
    - path: "frontend/src/hooks/useAnalysisStream.ts"
      issue: "error event with no `data` payload is always treated as a transient reconnect-eligible network blip (line 74-78), even when it's actually a permanent 404 for a project that no longer exists"
  missing:
    - "Distinguish a genuine transient connection drop from a permanent failure (e.g. check response status via a pre-flight fetch, or have the backend serve a proper SSE 'error' event with a JSON detail for a 404 project instead of a bare HTTP 404), and fall back to clearing the stored projectId / returning to the project list instead of retrying forever."
  debug_session: ""

- truth: "Preview controls on the Config Panel's character list let the user hear a character's assigned voice."
  status: failed
  reason: "User reported: the preview controls on the character list have no effect. Root cause: preview_audio_path is null for both characters in the live test project (never set) — CharacterPreviewRow's Play button is disabled whenever hasPreview is false (ConfigPanel.tsx:54) with no tooltip/explanation, and preview audio is only ever generated as a side effect of editing a character's voice_instructions in the separate CastWizard (Review Cast) screen, which the Config Panel gives no hint of and no way to trigger from."
  severity: major
  test: 4
  root_cause: "preview_audio_path is only ever populated as a side effect of PATCHing a character's voice_instructions in the CastWizard (Review Cast) screen — it's never eagerly generated when analysis/casting completes. ConfigPanel's CharacterPreviewRow unconditionally disables its Play button when preview_audio_path is null, with no tooltip or alternate trigger, so a character whose voice was never explicitly re-saved in the wizard has a permanently inert preview control on this screen."
  artifacts:
    - path: "frontend/src/components/ConfigPanel.tsx"
      issue: "CharacterPreviewRow's Play button silently disables with no explanation when preview_audio_path is null, and there is no way to generate a preview from this screen"
  missing:
    - "Either auto-generate previews for all cast characters once analysis completes, or give the disabled Play button an explanatory tooltip/label and/or a way to trigger preview generation on demand from the Config Panel itself"
  debug_session: ""

- truth: "Pressing Generate All while a segment is already generating is safely handled — either blocked with a warning, or queued without corrupting state."
  status: failed
  reason: "User reported: if i press generate all when a segment is beeing generated, nothing happens (no warning, no change on the ui). Root cause: POST /projects/{id}/generate (generate_project in main.py) has no in-flight guard — it unconditionally spawns a new run_batch_generation task every call. run_batch_generation's own stale-reset step (generation_worker.py:115-124) unconditionally resets any 'generating' row back to 'pending', assuming a crash leftover; it cannot distinguish that from a genuinely in-flight per-row generate_segment call, so a second Generate All click races the already-running work instead of being blocked. The frontend's isRunning guard (ConfigPanel.tsx:94) only reflects the batch SSE stream's status, not any per-row 'generating' segment, so the button isn't even disabled in that case."
  severity: major
  test: 4
  root_cause: "generate_project (POST /projects/{id}/generate) has no in-flight/lock check and unconditionally spawns a new run_batch_generation asyncio task on every call. run_batch_generation's own startup step unconditionally resets any row currently 'generating' back to 'pending' assuming it's a crash leftover — it has no way to tell that apart from a task that's genuinely still running (from an earlier click or a per-row generate), so a second invocation stomps on the first's in-flight work instead of being rejected."
  artifacts:
    - path: "backend/app/main.py"
      issue: "generate_project has no lock/in-flight check before spawning run_batch_generation (around line 774)"
    - path: "backend/app/generation_worker.py"
      issue: "run_batch_generation's stale-'generating'-row reset (line 115-124) cannot distinguish a crash leftover from a currently in-flight per-row generation"
    - path: "frontend/src/components/ConfigPanel.tsx"
      issue: "isRunning (line 94) only checks generation.status/isStarting, not per-row generation_status, so Generate All stays clickable while a per-row generate is in flight"
  missing:
    - "A project-level in-flight guard (e.g. an asyncio lock or a project.status check) that rejects or no-ops a second /generate call while one is already running for that project, plus a frontend disabled-state/error surface that reflects per-row 'generating' status, not just the batch stream"
    - "User-confirmed reproduction with exact expected behavior: disable Generate All whenever any segment is generation_status == 'generating'; disable each row's own Play/Generate button whenever that row is generation_status == 'generating'; add a way to cancel/stop an in-flight generation (single-row or batch) that fully stops the underlying process/thread, not just detaches the UI from it."
  debug_session: ""

- truth: "The per-row Play/Generate button never fires a second generate call for a segment that is already generating."
  status: failed
  reason: "User reported (continuation of test 4): the play button next to the generating... message is enabled and clicking it starts a spinner. Root cause: SegmentTable.tsx's GeneratePlayButton tracks its own local isGenerating state (line 95), set true only for the duration of ITS OWN await generateSegment() call — it never reads segment.generation_status at all. So when a row is already 'generating' via a batch run (or any other source), hasAudio is still false (audio_path not set yet), the button is NOT disabled, and clicking it calls POST /segments/{id}/generate a second time for the same segment that's already being synthesized — a second concurrent write racing the first."
  severity: major
  test: 4
  root_cause: "GeneratePlayButton's isGenerating is component-local React state set true only for the duration of its own await generateSegment() call — it is never derived from the segment's actual server-side generation_status. So a row that's 'generating' for any other reason (a batch run, another trigger) still shows an enabled button with hasAudio=false, and a click fires a second, independent POST /segments/{id}/generate for the same row."
  artifacts:
    - path: "frontend/src/components/SegmentTable.tsx"
      issue: "GeneratePlayButton's disabled={isGenerating} (line 140) only reflects this button instance's own local click-in-flight state, never segment.generation_status, so it doesn't disable for a row that's generating via a batch run or any other trigger"
  missing:
    - "Derive the button's disabled/generating-spinner state from segment.generation_status === 'generating' (the row's live server-driven status, already plumbed through ProjectScreen's liveSegments), not just local isGenerating, so the button can't fire a duplicate generate call for a row that's already in flight"
  debug_session: ""

- truth: "A running generation (single-row or batch) can be cancelled by the user, stopping the underlying work rather than just detaching the UI."
  status: failed
  reason: "User requested (continuation of test 4): allow canceling/stopping the generation at any point which completely stops any processes/threads. This is a new capability — no cancel/stop endpoint or UI control exists anywhere in the current implementation (checked main.py and generation_worker.py: generate_segment and run_batch_generation both run to completion once started, with no cancellation token or abort path)."
  severity: minor
  test: 4
  root_cause: "Not a defect — a missing feature. Neither generate_segment nor run_batch_generation accept or check any cancellation signal; once awaited/scheduled, both run to completion with no abort path exposed to the API or UI."
  artifacts: []
  missing:
    - "A cancel endpoint (e.g. DELETE/POST /projects/{id}/generate/cancel and/or /segments/{id}/generate/cancel) that actually cancels the underlying asyncio task (not just marks a DB flag while the task keeps running), plus a Stop/Cancel control in the UI wherever a generating spinner is shown"
  debug_session: ""

- truth: "Editing a segment's text/voice-instructions/narrator invalidates its stale audio but does NOT auto-start a new generation — generation is user-triggered only."
  status: failed
  reason: "User requested (confirmed as an intentional requirement change, not a one-off annoyance): when i edit the segment text and then leave the field, a new generation is started. expected behavior: remove previous segment audio if present and reset the state. the user has to trigger the generation manually. This reverses documented decision D-06 (03-CONTEXT.md 'Auto-regenerate on blur') and requirement GEN-03 (REQUIREMENTS.md) — patch_segment (main.py:556-594) currently bumps generation_version, sets generation_status='generating', and immediately fires a background regenerate_segment task on any edit. Needs to instead just invalidate (clear audio_path, reset to 'pending') and leave regeneration to the existing manual Generate controls."
  severity: major
  test: 6
  root_cause: "Not a defect — the current code correctly implements documented decision D-06/requirement GEN-03 (auto-regenerate-on-blur). The user has now reversed that decision during UAT; patch_segment's any_changed branch needs to stop auto-firing regenerate_segment and instead only invalidate the row (clear audio_path, reset to 'pending')."
  artifacts:
    - path: "backend/app/main.py"
      issue: "patch_segment (line 578-592) auto-fires asyncio.create_task(regenerate_segment(...)) on any_changed instead of just invalidating the row"
    - path: ".planning/REQUIREMENTS.md"
      issue: "GEN-03 (line 39) currently reads 'regenerates only that segment' — needs rewording to 'invalidates only that segment; user triggers regeneration manually'"
    - path: ".planning/phases/03-editable-table-full-generation-pipeline-persistence-deployme/03-CONTEXT.md"
      issue: "D-06 (line 31) documents the auto-regenerate-on-blur decision being reversed here"
  missing:
    - "Change patch_segment to clear audio_path and set generation_status='pending' (not 'generating') on edit, without spawning a regenerate_segment task; update REQUIREMENTS.md GEN-03 wording and 03-CONTEXT.md D-06 to record the reversal so the spec and code stay in sync"
  debug_session: ""
