# Pitfalls Research: v1.1 Generation UX & Config Rework

**Domain:** Adding generation-control (immediate cancel, model swap) and config-panel (codec/download) features to an existing FastAPI + SQLModel/SQLite + Qwen3-TTS-on-ROCm app
**Researched:** 2026-07-13
**Confidence:** HIGH (grounded directly in this repo's existing code — `backend/app/generation_worker.py`, `backend/app/main.py`, `backend/tts_service/model.py`, `backend/tts_service/server.py`, `backend/app/audio_join.py`, `backend/app/cache_key.py`, `backend/app/config.py`, `frontend/src/components/{SegmentTable,CharacterCard,ConfigPanel}.tsx`) + targeted web research on ROCm memory behavior, asyncio thread cancellation, and ffmpeg codec handling (MEDIUM confidence, general web sources, cross-checked across multiple results — see Sources)

## Critical Pitfalls

### Pitfall 1: "Cancel" that only stops the queue, not the in-flight call — because that's *already* the batch design today

**What goes wrong:**
The milestone asks for immediate cancellation of an *in-flight* GPU call. The existing batch cancel path (`POST /projects/{id}/generate/cancel` in `main.py`) is explicitly documented as NOT doing this — its own comment says: *"a Python thread can't be forcibly interrupted, so cancelling the segment currently mid-synth only takes effect once that HTTP call returns; this stops progression to the NEXT segment, it does not abort the in-flight one."* `task.cancel()` on the `run_batch_generation` asyncio Task only unblocks the *loop*, because the actual GPU work (`tts_client.synthesize` → `httpx.post` → `run_in_threadpool`) is running on a worker thread that `asyncio.Task.cancel()` cannot touch. This is a well-documented Python/asyncio limitation, not unique to this codebase: `run_in_executor`/`run_in_threadpool` cancellation only marks the *awaiting* task cancelled — the underlying thread keeps running until its blocking call returns naturally.
If this pitfall is not addressed head-on, "immediate cancel" ships as a re-skin of the exact same best-effort behavior already in place, just renamed and made to look instant in the UI while the GPU keeps grinding for up to the full synth duration underneath.

**Why it happens:**
The natural, low-effort implementation path is to reuse the existing `task.cancel()` pattern from batch cancel and assume it generalizes to per-segment/per-character cancel. It does generalize the "stop before next item" semantics — it does NOT generalize to "kill the in-flight call," because there is no next item to stop before at the per-call granularity; the in-flight call *is* the whole job.

**How to avoid:**
Distinguish two real cancellation targets and solve them differently:
1. **Client-side abort of the HTTP round trip** (backend → tts_service): switch `tts_client.synthesize`'s `httpx.post` from the current synchronous call to an `httpx.AsyncClient` request that can be cancelled by `task.cancel()` propagating an `asyncio.CancelledError` through the `await`, which httpx turns into closing the connection. This stops the *backend* from waiting on the result and lets the lock release immediately from the backend's point of view.
2. **Server-side abort of the actual GPU work** (tts_service's own inference call): closing the HTTP connection to `tts_service`'s `/synthesize` does NOT stop `model.generate_custom_voice(...)` mid-execution inside that process's threadpool thread — it just orphans it. If truly killing the GPU-bound call matters (not just the client's wait), `tts_service/server.py` needs its own cancellation mechanism: either (a) a request-scoped cancellation token checked between generation steps via a custom `StoppingCriteria`/callback (only works if `qwen_tts`'s `generate_custom_voice` exposes a hook — verify this against the installed `qwen-tts` version before committing to the design), or (b) accept that a genuinely in-flight single generate call cannot be interrupted mid-kernel on ROCm/PyTorch, and instead make "immediate" mean "the UI transitions to stopped/idle and the orphaned result is discarded when it lands" (fire-and-abandon with a version-guard, same `generation_version` pattern `regenerate_segment` already uses for the last-request-wins race). Decide and document which of these two the milestone actually needs — do not let "immediately-cancellable" quietly become "UI decouples immediately, GPU call still runs to completion in the background" without that being a stated, deliberate tradeoff.

**Warning signs:**
- Stop button turns the row/button state to idle/yellow but GPU utilization (or the mock backend's sleep) keeps running for the original call's full duration.
- A "cancelled" segment's audio silently appears/completes moments after the user already moved on and started a different generation — a sign the old call was never actually aborted, just ignored.
- Test coverage only exercises "cancel then verify the *next* segment doesn't start" (the batch pattern) with no test for "cancel then verify the *current* segment's underlying call actually stops consuming GPU/CPU."

**Phase to address:**
Feature 1 (immediately-cancellable TTS generation) — must be designed before Feature 5 (button rework) makes the "red = stop, kills instantly" promise visible in the UI. Decide the achievable cancellation semantics first; the button state machine and its copy ("Stop Generation") should describe what actually happens.

---

### Pitfall 2: Cancelling releases the global generation lock before the killed call has actually stopped — opens the door to two concurrent `/synthesize` calls racing the same GPU

**What goes wrong:**
`generation_worker._active_generation_label` is a **plain module global**, not an `asyncio.Lock` — the code comment explicitly justifies this as safe *only* because "there is no `await` between the check and the set in `try_claim_generation`." Today, `release_generation()` is only ever called after the in-flight coroutine has actually finished (via `finally:` blocks or a task's `add_done_callback`), so the lock's release always genuinely reflects "the GPU is free." Adding an immediate-cancel path breaks this invariant if the cancel handler calls `release_generation()` as soon as `task.cancel()` is issued, rather than after the underlying call has actually been aborted (Pitfall 1) — because `tts_service/server.py`'s `/synthesize` endpoint has **no concurrency control of its own** (a bare `run_in_threadpool` call, no lock or queue, per its own docstring). If the lock is released while the old call is still physically running against the resident model, a newly-claimed second generation (per-row, per-character, or a fresh batch) can issue a second concurrent `/synthesize` call against the same GPU/model instance while the first is still executing — exactly the race the single-flight lock exists to prevent.

**Why it happens:**
Releasing the lock "as soon as the user clicks Stop" feels correct from a UX-responsiveness standpoint (the button should go idle immediately) but conflates "the user's *intent* to cancel has been registered" with "the GPU resource has actually been freed." These are different events once true in-flight cancellation is on the table; they were the same event in the old best-effort design (nothing to distinguish, since the old design never interrupted anything early).

**How to avoid:**
Keep the global lock held until the underlying call is confirmed stopped (the HTTP request to `tts_service` has actually returned/errored/been aborted at the transport level), not merely until `task.cancel()` has been called. The UI can and should reflect "stopping…" as a transient state distinct from "idle" — the row/button goes red→stopping→yellow, not red→yellow instantly, if the true abort takes any non-zero time. If genuinely instant UI feedback is required regardless of backend cleanup timing, decouple lock ownership from UI state entirely: the frontend can optimistically show idle immediately, but the backend's `/generation-status` (or the SSE stream) must keep reporting `active: true` — and reject new claims — until the old call is verifiably done, exactly as the existing `test_lock_releases_after_batch_cancel` test already asserts for the batch case. Extend that same test pattern to per-segment and per-character cancel paths once they exist.

**Warning signs:**
- `try_claim_generation` succeeds for a *new* request while the *old*, "cancelled" request's log line for completion/error hasn't appeared yet.
- Intermittent, hard-to-reproduce GPU errors or garbled/empty audio that only show up after rapid stop→immediately-generate-again user interactions — a classic symptom of two `/synthesize` calls interleaving against one model instance.
- `GET /generation-status` returns `active: false` while `tts_service`'s own logs show a request still executing.

**Phase to address:**
Feature 1 — must be verified with a concurrency test analogous to `backend/tests/test_generation_lock.py`'s existing `test_lock_releases_after_batch_cancel`, extended to assert the lock stays held across a cancel until the underlying call is truly finished, not just requested-to-cancel.

---

### Pitfall 3: Per-segment and per-character generation have no cancellable task handle today — "add a Stop button" is actually "restructure the call as an addressable background task"

**What goes wrong:**
Only the batch path (`run_batch_generation`) is registered anywhere addressable: `_running_generations[project_id]` (an `asyncio.Task` keyed by project id), which is what `cancel_generation` calls `.cancel()` on. Per-segment generation (`POST /segments/{id}/generate` → `generate_segment`) is **awaited synchronously inline inside the request handler** — the frontend's `generateSegment()` in `api/client.ts` is a plain `await fetch(...)`, and there is no `asyncio.Task` object anywhere for a hypothetical `POST /segments/{id}/generate/cancel` to reach. Per-character preview (`trigger_character_preview` → `_generate_preview`) IS already spawned as a background task via `_spawn_claimed_generation`, but it's dropped into an unkeyed `_background_tasks: set[asyncio.Task]` purely to prevent GC — there is no `character_id → task` lookup either. Naively bolting a cancel endpoint onto either of these without first giving them an addressable, cancellable task handle will either 404/no-op (nothing to cancel) or require the endpoint to guess/globally-cancel "whatever is currently running," which breaks the per-row/per-character precision the milestone calls for.

**Why it happens:**
The existing `try_claim_generation(label)` calls already construct exactly the right keys for this — `f"segment:{segment_id}"`, `f"preview:{character_id}"`, `f"batch:{project_id}"` — but those labels are currently used only as a human-readable string for the single global slot, not as a lookup key into a task registry. It's easy to miss that the labeling scheme already half-solves the addressability problem and instead invent a new, separate registry, or skip registries entirely and only "cancel" the connection-level fetch on the frontend (which, per Pitfall 1, doesn't stop the backend work at all).

**How to avoid:**
Generalize `generation_worker._running_generations` from a `project_id`-keyed dict to a `label`-keyed dict (reusing the exact strings `try_claim_generation` already receives), and convert `generate_segment` and `trigger_character_preview`'s handling to register their spawned task under that same key before awaiting/returning. This also means changing `generate_segment`'s current *synchronous await-then-return-200-with-the-segment* contract to a *fire-and-return-202, poll-or-stream-for-status* contract (matching the batch and character-preview shape) — a bigger structural change than "add a stop button," and one that also changes the frontend's `generateSegment()` call site (no longer a simple await-for-result).

**Warning signs:**
- A cancel endpoint is added for segments/characters but has no way to look up which task to call `.cancel()` on, and falls back to "cancel whatever is in `_background_tasks`" (cancels the wrong thing, or everything).
- The per-row generate button's frontend code uses `AbortController`/`fetch().signal` and assumes that alone cancels backend work (it only drops the client's wait — see Pitfall 1).
- Tests exist for batch cancel (`test_lock_releases_after_batch_cancel`) but none for segment-level or character-level cancel, because there was never a task object to write such a test against.

**Phase to address:**
Feature 1 — this is prerequisite plumbing; sequence it before the button rework (Feature 5) since the button's red "Stop" state at the segment/character row level has nothing to call until this registry exists.

---

### Pitfall 4: Model swap breaks the "load exactly once at process startup, never touch again" invariant baked into `tts_service/model.py`, and the content-hash cache doesn't know a swap happened

**What goes wrong:**
`tts_service/model.py`'s module-level `model = Qwen3TTSModel.from_pretrained(...)` is loaded **once**, at import time, and every call-site (`synthesize_wav`, `keepalive_matmul`) references the module-global `model` by name directly — the file's own docstring states this is deliberate: *"Loaded ONCE at module import time... never reload per request... the documented anti-pattern to avoid."* Introducing on-demand swapping between the 1.7B and 0.6B checkpoints inside this same persistent process means:
1. **Reassigning a module global while a request may be mid-flight.** If a `/synthesize` call is inside `run_in_threadpool(model.generate_custom_voice, ...)` on one thread while a swap operation does `model = Qwen3TTSModel.from_pretrained(other_checkpoint)` on another, the in-flight call may already hold a reference to the *old* Python object (safe-ish, since local binding happened before reassignment) — but if the swap also does `del old_model; torch.cuda.empty_cache()` (the standard ROCm/CUDA VRAM-reclaim pattern) while that old object still has an active kernel running against it, the result is undefined: could be an HIP illegal-memory-access, garbage audio, or a hang, none of which the current code has any guard against.
2. **The content-hash cache (`cache_key.py`) has no live model-identity input.** `TTS_MODEL_VERSION` is a **hardcoded string constant** (`"qwen3-tts-12hz-1.7b-customvoice-v1"`), not a parameter — its own comment says *"Only one model... is in scope for v1, so this is a constant today, not a live 'model version' lookup."* Once two checkpoints can be selected, a segment synthesized under 0.6B and one synthesized under 1.7B with identical (speaker, instructions, text) will compute the **same cache key** and be treated as a cache hit for each other. Switching models and hitting "Generate" again would silently reuse stale audio from the *other* model instead of actually resynthesizing — a correctness bug that looks like nothing happened, not a crash, which makes it the kind of pitfall that ships unnoticed.

**Why it happens:**
Both of these are pre-existing, deliberate simplifications ("only one model," "never reload") that were entirely correct for v1's scope and become silently wrong the moment "swap models" is added — nothing in the code will error; it will just serve wrong-but-plausible results.

**How to avoid:**
- Gate every model (re)load behind the *same* single global generation lock (`try_claim_generation`/`release_generation`) already used for synthesis — a swap-in-progress must block new `/synthesize` calls exactly like an in-flight generation does, and `tts_service`'s own `_ready` flag (already checked by `/healthz` and `/synthesize`) must flip to `False` for the duration of the swap so a client sees a clean `503`, not a call against a half-torn-down model.
- Make the active checkpoint identifier a **live value**, threaded from `tts_service` back through to `compute_cache_key`'s `TTS_MODEL_VERSION` parameter (turn it from a module constant into a real function argument, resolved from whichever checkpoint actually produced — or would produce — the audio). This is a small, mechanical change (`cache_key.py`'s docstring already anticipates it: *"a future model-version bump are all naturally cache-busting with no extra invalidation code path"* — but only if the value is actually wired through, which it isn't yet).
- Confirm VRAM is genuinely reclaimed after unload, not just logically "dereferenced" — see Pitfall 5.

**Warning signs:**
- Switching models and regenerating a previously-generated segment produces byte-identical audio to the old model's output (cache-hit false positive).
- `qwen-ebook-tts` container logs show two `Loading Qwen/Qwen3-TTS-...` lines with no `/healthz` 503 window in between (the swap didn't actually block traffic during the transition).
- A `/synthesize` request completes successfully but the resulting audio's voice characteristics don't match either configured model — a symptom of a request being served mid-swap against a torn-down or partially-loaded model object.

**Phase to address:**
Feature 2 (model swapping) — the cache-key wiring in particular should land in the same phase as the swap mechanism itself, not deferred, since a swap without it is a silent-wrong-audio bug from day one of the feature shipping.

---

### Pitfall 5: Assuming `del model; torch.cuda.empty_cache()` fully reclaims VRAM on ROCm — the 16GB budget has zero headroom for fragmentation

**What goes wrong:**
The standard PyTorch pattern for freeing a loaded model's VRAM (`del model`, `gc.collect()`, `torch.cuda.empty_cache()` — HIP intercepts the same `torch.cuda.*` API on ROCm builds) reliably drops PyTorch's own *reference* to the memory back into its caching allocator, but doesn't guarantee the allocator hands it back to the OS/driver, and doesn't defragment it. Community reports (ROCm/PyTorch GitHub issues, PyTorch forums) describe repeated load/unload cycles under ROCm/HIP producing "out of memory with plenty of memory apparently free" — a symptom of fragmentation, not a genuine leak — and note `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (or equivalent HIP allocator config) as a mitigation, plus warn that calling `empty_cache()` on every swap "disrupts memory reuse" and adds latency. On a 16GB card already earmarked for a single 1.7B-parameter bf16 model plus activation/KV overhead, even a few hundred MB of unreclaimed fragmentation across repeated swaps between the 1.7B and 0.6B checkpoints (a realistic session pattern for a user comparing quality/speed) risks a hard OOM on the *next* load — not on the swap that leaked it, which makes the failure look unrelated to its actual cause and hard to reproduce on demand.

**Why it happens:**
The load-once-per-process design this app shipped with never had to test this: v1 loads the model exactly once and never unloads it, so no fragmentation-under-repeated-cycling behavior has ever been exercised against this app's actual ROCm/gfx1201 target. "Should work, it's the documented PyTorch pattern" is true for CUDA in the common case and *usually* true for ROCm, but "usually" is not a guarantee this app has verified on its own hardware.

**How to avoid:**
- Treat unload-then-reload as needing an explicit **smoke check**, not an assumption: after a swap, log (or expose via `/healthz`) actual free VRAM (`torch.cuda.mem_get_info()` works under ROCm's CUDA-compatible API) before and after, so a slow fragmentation leak across repeated swaps is visible in logs long before it becomes a hard OOM crash.
- Budget conservatively: confirm the 1.7B and 0.6B checkpoints' actual resident VRAM footprint (weights + activation + any KV/attention buffer) leaves real headroom under 16GB even with one full model's worth of allocator fragmentation from the *previous* occupant still uncollected — don't assume `empty_cache()` returns to a clean-slate baseline.
- Consider whether the swap needs a harder reset than in-process `del`+`empty_cache()` for reliability — e.g., if VRAM isn't fully reclaimed after N swaps in testing, the ceiling-and-upgrade-path options are: restart `tts_service`'s Podman container between swaps (fully clean device state, at the cost of paying full load-latency plus the `_ready`-flag-503 window on every swap, not just the first), or accept a documented "restart the TTS container if audio quality/latency degrades after repeated swapping" runbook note as an interim ceiling rather than silently shipping an assumption.

**Warning signs:**
- OOM errors on the *second or later* model load in a session, not the first — a strong fragmentation signal, distinct from a simple "model doesn't fit" sizing error.
- `torch.cuda.mem_get_info()` (or `rocm-smi`) shows steadily shrinking free memory across repeated swap cycles within one long-running `tts_service` process, never returning to the same free-memory baseline it started at.

**Phase to address:**
Feature 2 — should be validated on the actual RX 9070 XT deployment target (not just dev-machine/mock) before the swap feature is considered done; this is exactly the kind of hardware-specific behavior CLAUDE.md's constraints call out as needing real-GPU verification.

---

### Pitfall 6: Adding FLAC/Opus into `audio_join.py`'s existing wav-vs-"else" branch silently mis-encodes instead of erroring

**What goes wrong:**
`join_wavs`'s codec selection today is a two-way branch: `fmt == "wav"` gets `-c copy`; **anything else** (including a typo, or a not-yet-supported format string) falls into the `else` arm and is unconditionally encoded with `-c:a libmp3lame` — there is no explicit `elif fmt == "mp3"`, so this arm currently treats "mp3" and "anything that isn't wav" as identical. `config.py`'s `_ALLOWED_OUTPUT_FORMATS = {"wav", "mp3"}` is the only thing currently preventing a bad value from reaching `join_wavs` at all — that allowlist, the output `Content-Type` selection in `main.py` (currently hardcoded to `audio/wav` for the two GET-audio routes, and presumably needs a matching content-type decision for FLAC/Opus downloads), and `join_wavs`'s branch all have to move together. If FLAC/Opus are added by just widening `_ALLOWED_OUTPUT_FORMATS` and adding one more `elif` without touching every one of these three spots, the most likely failure is: a project configured for `"opus"` output produces a file that ffmpeg happily writes as **MP3 bytes with an `.opus` filename**, or a `Content-Type: audio/mpeg` header on what's actually FLAC data — both play in nothing correctly, and both fail silently at generation time (ffmpeg exits 0; it did successfully encode *something*).

**Why it happens:**
The current code's fallback-to-mp3 `else` arm was a reasonable simplification when only two formats existed ("not wav" could only ever mean "mp3"). Extending the format set without revisiting that assumption is the natural shortcut — "just add flac/opus to the allowed set" reads as a config change, not a control-flow change, even though it is one.

**How to avoid:**
Replace the `if/else` with an explicit mapping from format → `(codec_args, content_type, extension)` covering exactly `{"flac", "mp3", "opus"}` (WAV is being dropped per this milestone, so it should be *removed* from the allowed set, not just left as a third silently-still-working option — see Pitfall 7), with no catch-all `else` branch: an unrecognized format should raise immediately (mirroring `config.py`'s existing fail-fast philosophy: *"fail fast at settings-load time instead of at request time deep inside ffmpeg"*), not degrade to a default. Opus specifically needs the `libopus` encoder (not FFmpeg's experimental native `opus` encoder) — confirm the container's `apt-get install ffmpeg` build actually has `libopus` compiled in (Debian's package normally does, but this project has never verified or pinned that; check with `ffmpeg -codecs | grep opus` during the container build or a startup smoke check rather than assuming). Also confirm FLAC's re-encode (not a stream copy — FLAC is a different container/codec from WAV) handles the sample rate qwen-tts actually emits without complaint.

**Warning signs:**
- A generated `.flac` or `.opus` output file plays back correctly in `ffplay`/`ffmpeg -i` (which is codec-tolerant) but fails or sounds wrong in a strict player/browser `<audio>` tag that trusts the file extension/Content-Type.
- `ffmpeg -codecs` inside the running backend container doesn't list `libopus` as available — a build-time gap, not a runtime bug, that would make every Opus-format project fail the same way in production.
- Config validation accepts `OUTPUT_FORMAT=opus` at startup but the actual join step has no dedicated branch for it (falls through to the old mp3-shaped `else`).

**Phase to address:**
Feature 3 (FLAC/Opus + drop WAV) — the format→encoder mapping and Content-Type wiring should be done as one atomic change across `config.py`, `audio_join.py`, and every response route that sets `media_type`, not staged incrementally (a mid-migration state where some but not all of these three know about the new formats is exactly what produces the mismatch).

---

### Pitfall 7: Dropping WAV as an option without updating `config.py`'s own default leaves fresh deployments silently still producing WAV

**What goes wrong:**
`config.py`'s `load_settings()` reads `OUTPUT_FORMAT` via `os.environ.get("OUTPUT_FORMAT", "wav")` — WAV is not just *an* allowed option today, it is **the fallback default** when the env var is unset. If the milestone's format allowlist is updated to `{"flac", "mp3", "opus"}` but this default string literal is left as `"wav"`, any deployment/dev environment that doesn't explicitly set `OUTPUT_FORMAT` will fail at startup with `load_settings`'s own `ValueError` (since `"wav"` is no longer in `_ALLOWED_OUTPUT_FORMATS`) — which is at least loud and fails fast, so the realistic risk isn't a silent wrong-format bug here, it's an easy-to-miss deploy break: the Podman Quadlet unit (`deploy/qwen-ebook-backend.container`) or `.env`/systemd environment file may also hardcode or omit `OUTPUT_FORMAT=wav` from an earlier v1 setup, and needs an explicit audit alongside the code change, not just a code-side default flip.

**Why it happens:**
"Drop WAV as a format option" reads as a frontend/UI change (remove it from a dropdown) more readily than a backend default-value and deployment-config change — the actual default that matters when nothing is configured is easy to overlook since it's three files removed from the UI dropdown being edited.

**How to avoid:**
Grep every place `"wav"` appears as a *default or fallback* (not as an internal implementation detail like segment-level intermediate audio, which legitimately stays WAV — see Pitfall 8) — `config.py`'s `load_settings` default, any deploy/Quadlet/`.env` files, and test fixtures that assert on `OUTPUT_FORMAT` defaults. Pick a real new default (e.g., `"mp3"`, the safest universally-playable choice) and update all of them together, then re-verify the Quadlet deployment's actual configured value on the production VM, not just the code default.

**Warning signs:**
- Local dev/tests pass (they typically set `OUTPUT_FORMAT` explicitly or don't care), but the production Quadlet unit — deployed once and rarely revisited — still has no `OUTPUT_FORMAT` set and starts failing `load_settings()`'s `ValueError` after the next deploy, taking the whole backend down at boot.

**Phase to address:**
Feature 3 — do this as part of the same change that updates `_ALLOWED_OUTPUT_FORMATS`, and explicitly re-check `deploy/qwen-ebook-backend.container` (or wherever `OUTPUT_FORMAT` is set for the live VM) as a deployment step, not just a code diff.

---

### Pitfall 8: Reusing the user-editable output filename as the *server-side* file path — this app has been careful about exactly this everywhere else

**What goes wrong:**
Every existing file-producing path in this codebase deliberately uses a server-generated UUID as the on-disk filename, never anything derived from user or LLM-sourced text — `_join_project`'s own comment: *"Server-generated uuid filename — never derived from any client string (T-03-06)"*, and `regenerate_segment`'s: *"Server-generated uuid filename — never derived from segment text (T-03-01)."* Adding a user-editable **output filename** creates a real temptation to take a shortcut and use that string to name the file on disk (`out_dir / user_filename` instead of `out_dir / f"{uuid4().hex}.{fmt}"`) since it's now literally the field the user is editing for exactly that purpose. Doing so reopens exactly the class of bug this project has twice explicitly guarded against: a filename containing `../` traversal segments, absolute-path characters, or null bytes could write outside `OUTPUT_DIR`; two projects (or two generations of the same project) choosing the same display name would collide and overwrite each other's file on disk, since nothing today deduplicates against the *display* name — only the UUID scheme guarantees uniqueness.

**Why it happens:**
The feature request itself is phrased in filename terms ("user-editable output filename"), which nudges the implementation toward "the filename *is* the path" — conflating the **display name for a download** (what the browser should call the saved file — a `Content-Disposition` concern) with the **storage path** (an internal, server-owned concern) that has no reason to ever be user-influenced in the first place. Tailscale-only single-user access reduces who could exploit this, but doesn't make the path-construction bug not-a-bug — an accidental self-inflicted overwrite from picking the same name for two projects, or a stray `/` character silently truncating the intended save location, doesn't require an adversary.

**How to avoid:**
Keep the on-disk filename fully server-generated (continue the existing UUID pattern), unconditionally. Store the user's chosen display name as a separate DB column (e.g. `Project.output_filename: str | None`) used **only** for the `Content-Disposition` header on the new download route — never for path construction. Validate/sanitize it at write time regardless (strip path separators, control characters, cap length, and normalize/ensure it carries the correct extension for the currently-configured `OUTPUT_FORMAT` so a user can't rename a `.flac` file to display as `.mp3` and confuse whatever plays it back) — see Pitfall 9 for the header-encoding half of this.

**Warning signs:**
- Grep for `output_filename` (or whatever the new field is named) landing anywhere inside a `Path(...)` construction used for an actual filesystem write, rather than only inside a header-building function.
- Two projects with the same user-chosen name produce one overwriting the other's file (test explicitly for this — it won't show up in a single-project happy-path test).

**Phase to address:**
Feature 4 (download endpoint + editable filename) — this is the single highest-severity item in this milestone precisely because this codebase already has two comments explicitly documenting this exact discipline elsewhere; failing to carry it into the new feature would be a regression against the project's own established pattern, not a novel oversight.

---

### Pitfall 9: Hand-formatting the `Content-Disposition` header instead of using the framework's own filename-quoting support

**What goes wrong:**
A raw user-supplied string dropped directly into a hand-built header value like `f'attachment; filename="{name}"'` breaks on an embedded `"` character (ends the quoted value early, corrupting the header), on CRLF sequences (classic header-injection vector, even in a trusted single-user network — it's still a correctness bug, not just a security one, since it can corrupt the HTTP response), and mishandles non-ASCII filenames (the classic `filename=` parameter is ASCII-only per RFC 6266; Unicode names need the `filename*=UTF-8''...` form, which most browsers expect alongside a plain ASCII fallback for compatibility).

**Why it happens:**
It looks like a one-line f-string, so it's easy to write inline in the download route without reaching for the framework's built-in support, especially since none of this codebase's existing routes serve a `Content-Disposition: attachment` header today (`get_segment_audio`/`get_character_preview` return raw bytes with just a `media_type`, no disposition/filename at all) — there's no existing pattern in-repo to copy correctly, only ones to copy *incorrectly* by extrapolation (e.g. naively pattern-matching the existing `Response(content=..., media_type=...)` calls and just appending a header string).

**How to avoid:**
Use `starlette.responses.FileResponse`'s (or `Response`'s) built-in `filename=` parameter, which already implements RFC-correct quoting/encoding — don't hand-format the header string. Sanitize the stored display name at write time (Pitfall 8) so by the time it reaches the response layer it's already a safe, reasonably-printable string, rather than relying on the header-encoding step alone to save an unsanitized value.

**Warning signs:**
- A filename containing a quote, backslash, or non-ASCII character (e.g. an ebook title copied verbatim into the filename field) breaks the browser's save dialog or downloads with a mangled/blank name.
- The header value is built with an f-string or `.format()` call anywhere in the download route rather than passed as a `filename=` kwarg to a `Response` subclass.

**Phase to address:**
Feature 4 — same phase as Pitfall 8; both are contained in the same new download route and should be reviewed together.

---

### Pitfall 10: Extending 2 (really 4) independently hand-rolled generate/play button implementations to a 3rd state multiplies drift instead of consolidating it

**What goes wrong:**
The 3-state color rework is scoped as "3 call sites" (segment row, character preview, batch) but the codebase today already has **4 near-duplicate implementations** of the underlying generate/play pattern, not 3: `SegmentTable.tsx`'s `GeneratePlayButton`, `CharacterCard.tsx`'s inline generate/play controls (used in the cast wizard), `ConfigPanel.tsx`'s own separate `CharacterPreviewControl` (a *second*, independently-written character-preview button, distinct from `CharacterCard`'s), and `ConfigPanel.tsx`'s batch Generate-All/Stop control. Each keeps its own local `isPlaying` `useState`, its own hidden-`<audio>`-element wiring, and its own ad hoc derivation of "is this thing currently busy" (e.g. `SegmentTable`'s `isRowGenerating = isGenerating || segment.generation_status === "generating"`, a locally-scoped compound condition specific to that file). This split already happened once organically — `CharacterCard` and `ConfigPanel` built two separate character-preview buttons instead of sharing one — which is direct evidence that the natural, low-effort path here is "copy the nearest similar button and hand-tune it," not "extract a shared component." Doing that a 3rd/4th time to bolt on the new red "Stop" state and yellow/red/green semantics means four places to get the *same* three-way state derivation right, and four places that can each independently drift the next time status semantics change (exactly the kind of gap that GEN-03/D-06's cross-path invalidation bug — closed as code-review finding CR-01 — already demonstrated is easy to miss on secondary paths in this codebase).

**Why it happens:**
Each button lives in a different component with a different immediate data shape available to it (a `Segment` row vs. a `Character` vs. project-wide batch state), so copy-and-adapt feels like the path of least resistance for each individually, and no one component change forces a look at the other three.

**How to avoid:**
Extract one shared piece (a hook — e.g. `useGeneratePlayState(status, onGenerate, onStop, hasAudio)` — or a shared `<GenerateStopPlayButton>` component) that owns the yellow/red/green derivation and the click-handler dispatch, and have all four call sites consume it, parameterized only by their own generate/stop/audio-availability callbacks and status source. Do this refactor *before* wiring in the new red "Stop" semantics, not after — adding a 3rd state to 4 separately-maintained implementations first and unifying them later means writing (and testing) the 3-state logic four times, then throwing three of those away.

**Warning signs:**
- A grep for `isPlaying` or `useState` inside button-adjacent code turns up 4 near-identical hook calls rather than 1 shared one.
- The yellow→red→green transition is implemented correctly in 3 of the 4 call sites and the 4th (most likely `CharacterCard.tsx`, since it's the one *not* explicitly named in the milestone's "3 call sites" list, making it the easiest to forget) is left on the old icon-only pattern or a subtly different color mapping.
- "Any edit reverts to yellow" (the GEN-03/D-06 invariant) and "a stopped/cancelled generation reverts to yellow, not stuck on red or falsely green" (the new invariant this milestone adds) are each verified in only one of the four call sites' tests, not all four.

**Phase to address:**
Feature 5 (button rework) — start this phase with the extraction/consolidation of the existing 4 implementations into 1 shared piece, then layer the new 3-state semantics on top of the single shared implementation, rather than editing each of the 4 files in place.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|------------------|
| Release the global generation lock as soon as `task.cancel()` is called, without confirming the underlying `/synthesize` call actually stopped | Simpler cancel handler, instant-feeling UI | Two concurrent `/synthesize` calls can race the single resident model (Pitfall 2) | Never — this is exactly the invariant the existing lock design depends on |
| Restart the whole `tts_service` container to "cancel" or to swap models, instead of in-process interruption/unload | Guarantees a clean device state every time, no fragmentation risk (Pitfall 5) | Full model reload cost (1-2 min per `model.py`'s own log message) on every cancel/swap; defeats "immediate" | Acceptable as an interim/fallback ceiling if in-process cancellation/unload proves unreliable in testing — document it as a known tradeoff, not a silent regression |
| Use the user-editable output filename directly as the on-disk path | Saves adding a separate DB column + sanitization step | Path traversal / cross-project overwrite risk (Pitfall 8) — and a direct regression against this codebase's own established T-03-01/T-03-06 discipline | Never |
| Leave `TTS_MODEL_VERSION` a hardcoded constant and skip wiring it into the swap feature | Smaller diff for Feature 2 | Silent cache-hit false positives serving wrong-model audio after a swap (Pitfall 4) | Never — the cost is a correctness bug that produces no error, so it won't be caught by normal testing unless specifically tested for |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|-----------------|-------------------|
| `tts_service` HTTP boundary (backend ↔ GPU-scoped container) | Assuming closing the backend's HTTP connection to `/synthesize` stops the GPU work in `tts_service` | Treat it as two separate cancellation problems: the backend's wait (fixable with async httpx) and the actual inference call (may not be interruptible at all — decide and document, Pitfall 1) |
| ROCm/HIP VRAM reclaim (`torch.cuda.empty_cache()` after unload) | Assuming `del model; empty_cache()` fully and reliably frees VRAM back to a clean baseline, matching the common CUDA-world expectation | Log/verify actual free VRAM before and after each swap in real deployment testing; don't assume parity with CUDA behavior on ROCm without checking (Pitfall 5) |
| ffmpeg codec selection (`audio_join.py`) | Widening `_ALLOWED_OUTPUT_FORMATS` without adding a matching explicit branch in `join_wavs`, letting new formats fall through the existing mp3-shaped `else` | One explicit mapping from format to `(codec_args, content_type)`, no catch-all fallback branch (Pitfall 6) |
| Content-Disposition / file download (new surface) | Hand-formatting the header string with an unsanitized user-supplied filename | Use the framework's `filename=` support on `Response`/`FileResponse`; sanitize the stored name independently at write time (Pitfall 9) |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Calling `torch.cuda.empty_cache()` (or its ROCm/HIP equivalent) on every model swap "to be safe" | Swap latency creeping up over a session; allocator has to re-grow its cache from scratch after every swap instead of reusing recently-freed blocks | Only call it when actually swapping checkpoints (which this feature does inherently need), not on any other generation path — and measure whether it's even necessary in practice vs. just `del` + `gc.collect()` | Noticeable at swap counts in the tens within one long-running session, per general PyTorch community reports — verify against this app's actual usage pattern rather than assuming |
| Re-encoding every join to FLAC/Opus even for single-segment "preview" style joins where a stream copy would suffice | Slightly higher latency per join than the old WAV stream-copy path | Acceptable, since FLAC/Opus fundamentally require re-encoding from WAV (different container/codec) — not avoidable, just worth knowing it's now unconditionally slower than the old wav-copy default | Immaterial at this project's single-user, batch-not-realtime scale (explicitly out of scope: "Real-time audio streaming/preview during generation") |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Using the user-editable output filename to construct the on-disk save path | Path traversal (`../`) or cross-project file overwrite | Server-generated UUID path always; user's name is display-only via `Content-Disposition` (Pitfall 8) |
| Unescaped filename in a hand-built `Content-Disposition` header | Header corruption/injection (CRLF, embedded quotes) | Use `FileResponse`'s `filename=` parameter; never hand-format the header string (Pitfall 9) |
| New download route resolving `output_path` from anything other than the DB row keyed by `project_id` | A crafted or guessed path parameter could read an arbitrary file if the route ever accepts a path/filename directly instead of only a project id | Mirror `get_segment_audio`/`get_character_preview`'s existing discipline: always resolve the served path from the DB by an opaque id, never from client-supplied path text |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|--------------|-------------------|
| Stop button flips to idle/yellow instantly while the underlying GPU call keeps running (Pitfall 1/2) | User believes generation stopped and starts a new one, unaware the old one is still consuming the single global GPU slot — new action gets rejected/blocked or, worse, races the old one | Show a distinct transient "stopping…" state until the backend confirms the old call is actually done; don't conflate "cancel requested" with "cancel completed" in the UI |
| A stopped/cancelled segment or character preview left in an ambiguous status (not clearly reset to yellow/pending) | User can't tell if a stop actually worked, or thinks stale/partial audio is valid | Reuse the exact reset-to-pending discipline the batch cancel path already applies to `generating` rows; apply it to per-segment/per-character cancel too, don't leave it as a batch-only behavior |
| `GET /generation-status` is poll-based, not push — a faster stop→generate cycle (once truly immediate) makes the poll staleness window relatively more visible than it was under the old slower best-effort design | A control briefly appears available/unavailable out of sync with actual server state | Not a new bug, but worth re-checking the poll interval is still short enough once cancel is genuinely fast — the old design's multi-second synth times masked poll lag that a sub-second stop would expose |

## "Looks Done But Isn't" Checklist

- [ ] **Immediate cancel:** Verify the *GPU-bound call itself* stops (via logs/GPU utilization), not just that the batch loop moves on to the next item — the existing batch cancel already does the latter; confirm the new work does the former.
- [ ] **Model swap:** Verify actual free VRAM (`torch.cuda.mem_get_info()`/`rocm-smi`) before and after a swap on the real RX 9070 XT deployment, not just that the code runs without an exception in mock/dev.
- [ ] **Model swap cache correctness:** Regenerate the *same* segment under both checkpoints and confirm the audio actually differs / a fresh synth call actually happens — don't just confirm the swap endpoint returns 200.
- [ ] **FLAC/Opus output:** Confirm the *installed* ffmpeg binary in the built container actually has `libopus` compiled in (`ffmpeg -codecs`), not just that the code path compiles.
- [ ] **Download endpoint:** Confirm two projects with identical user-chosen filenames don't collide on disk, and that a filename with `../`, quotes, or non-ASCII characters is handled safely end-to-end (path write + header).
- [ ] **Button rework:** Confirm all 4 existing hand-rolled implementations (not just the 3 named in the milestone) were touched — specifically check `CharacterCard.tsx`, the one not explicitly named in the milestone's "3 call sites" list.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|-----------------|-------------------|
| Lock released before an in-flight call truly stopped, causing a race (Pitfall 2) | MEDIUM | Add the "hold lock until confirmed stopped" guard; add a regression test mirroring `test_lock_releases_after_batch_cancel` for the new per-segment/per-character cancel paths; audit logs for any historical garbled-audio reports that match the symptom |
| Model swap serving stale-model-cached audio (Pitfall 4) | LOW | Wire the live model identifier into `compute_cache_key`; bump a version marker once to force-invalidate any audio cached before the fix, since old cache keys can't be trusted post-fix |
| VRAM fragmentation causing intermittent OOM after repeated swaps (Pitfall 5) | HIGH (hardware-dependent, may require redesigning the swap mechanism) | Fall back to full `tts_service` container restart on swap as an interim ceiling; only revisit in-process unload once verified reliable on the real deployment target |
| Filename used as on-disk path already shipped and caused an overwrite/traversal issue (Pitfall 8) | LOW–MEDIUM | Migrate to a server-generated path + separate display-name column; re-point any already-created `Project.output_path` values that were built from user text |
| Four divergent button implementations shipped with inconsistent 3-state logic (Pitfall 10) | MEDIUM | Consolidate into the shared hook/component post-hoc; audit each of the 4 call sites against the GEN-03/D-06 "any edit reverts to yellow" and the new "stopped reverts to yellow" invariants one by one |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase (milestone feature) | Verification |
|---------|----------------------------------------|----------------|
| 1: Cancel doesn't stop in-flight GPU work | Feature 1 | GPU utilization / mock-sleep actually interrupted, not just "next item skipped" |
| 2: Lock released before call truly stopped | Feature 1 | Concurrency test extending `test_lock_releases_after_batch_cancel` to per-segment/per-character cancel |
| 3: No addressable task handle for segment/character cancel | Feature 1 | `_running_generations`-style registry keyed by the existing `try_claim_generation` label strings; cancel endpoint resolves a real task via that key |
| 4: Model swap breaks load-once invariant + cache blindness | Feature 2 | Swap blocks new requests until complete (`_ready` flag + lock); same-input regen after a swap actually re-synthesizes |
| 5: VRAM fragmentation on repeated swap | Feature 2 | Real-hardware VRAM measurement before/after N swaps on the RX 9070 XT deployment |
| 6: FLAC/Opus fall through mp3 `else` branch | Feature 3 | Explicit per-format mapping with no catch-all; `ffmpeg -codecs` confirms `libopus` present in the built image |
| 7: WAV-default not updated when WAV is dropped | Feature 3 | `load_settings()` default + Quadlet/env config both audited and updated together |
| 8: User filename used as server-side path | Feature 4 | Path-traversal/collision test: two same-named projects, a `../`-laden name, both write to distinct safe UUID paths |
| 9: Hand-built Content-Disposition header | Feature 4 | Filename with quote/CRLF/non-ASCII characters round-trips safely through the download response |
| 10: Four divergent button implementations | Feature 5 | Shared hook/component used at all 4 call sites (including `CharacterCard.tsx`); single test suite covering the 3-state + edit-reverts-to-yellow + stop-reverts-to-yellow invariants applies identically everywhere |

## Sources

- **Curated (this repository — HIGH confidence, direct code read):** `backend/app/generation_worker.py`, `backend/app/main.py`, `backend/app/tts_client.py`, `backend/app/cache_key.py`, `backend/app/config.py`, `backend/app/audio_join.py`, `backend/tts_service/model.py`, `backend/tts_service/server.py`, `backend/tests/test_generation_lock.py`, `deploy/qwen-ebook-tts.container`, `frontend/src/components/{SegmentTable,CharacterCard,ConfigPanel}.tsx`, `frontend/src/api/client.ts`, `.planning/PROJECT.md`
- **Web (MEDIUM confidence, cross-checked across multiple results):**
  - [run_in_executor not stopping thread after task cancellation in asyncio (Python 3.11) · Issue #107505 · python/cpython](https://github.com/python/cpython/issues/107505)
  - [AnyIO — Working with threads](https://anyio.readthedocs.io/en/stable/threads.html)
  - [HIP out of memory when there appears to be plenty of memory available · ROCm/ROCm Discussion #2407](https://github.com/ROCm/ROCm/discussions/2407)
  - [OOM with a lot of GPU memory left · Issue #67680 · pytorch/pytorch](https://github.com/pytorch/pytorch/issues/67680)
  - [[bug]: ROCm Out of Memory Errors - Excessive VRAM Allocation · Issue #6301 · invoke-ai/InvokeAI](https://github.com/invoke-ai/InvokeAI/issues/6301)
  - [FFmpeg Concat Guide: Demuxer, Filter, Protocol and API](https://renderio.dev/blogs/ffmpeg-concat-guide/)
  - [FFmpeg-user: Opus — difference between .opus and .ogg file extension](https://ffmpeg.org/pipermail/ffmpeg-user/2017-November/038094.html)
  - [Opus | Codec Wiki](https://wiki.x266.mov/docs/audio/Opus)

---
*Pitfalls research for: Qwen Ebook Narrator v1.1 (Generation UX & Config Rework)*
*Researched: 2026-07-13*
