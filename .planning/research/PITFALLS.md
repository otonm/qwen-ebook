# Pitfalls Research

**Domain:** Self-hosted ebook-to-audiobook narration pipeline (LLM text segmentation + AMD/ROCm TTS + audio joining)
**Researched:** 2026-07-09
**Confidence:** MEDIUM-HIGH (ROCm/Podman and audio joining findings verified against official docs and multiple GitHub issues; Qwen3-TTS-specific findings drawn from GitHub issues/discussions and community write-ups — treat model-quirk specifics as MEDIUM confidence since Qwen3-TTS is a fast-moving project; LLM segmentation-consistency findings are MEDIUM, based on general structured-output research applied to this domain since no source specifically benchmarks "character re-identification across chunks")

## Critical Pitfalls

### Pitfall 1: ROCm device passthrough works in a bare `podman run` test but fails once the app is wrapped in a real container/Quadlet setup

**What goes wrong:**
A dev verifies `podman run --device /dev/kfd --device /dev/dri rocm/... rocminfo` works, then builds the actual app image/Compose file and GPU access silently fails or `rocminfo` can't see the GPU inside the app container — often surfacing as "permission denied" on `/dev/kfd`, or the process starts but never gets GPU utilization.

**Why it happens:**
Podman GPU passthrough has several independently-required pieces that are easy to satisfy individually and miss collectively: (1) host user must be in `render` and `video` groups, (2) rootless Podman needs `--group-add keep-groups` to actually preserve those supplementary groups inside the container, (3) SELinux (default on Fedora-family hosts) blocks device access unless `container_use_devices` boolean is set or labels are handled, and (4) both `/dev/kfd` (compute) and `/dev/dri` (render nodes) must be passed — passing only one "half" is a common mistake. Quadlet/systemd-unit deployments frequently drop one of these flags that was present in the ad-hoc test command.

**How to avoid:**
- Bake device passthrough, group membership, and SELinux boolean into the deployment scripts/Quadlet unit from day one — don't treat it as a "works on my test command" checkbox.
- Explicitly pass `--device /dev/kfd --device /dev/dri --group-add keep-groups` (rootless) in every place the container is launched (dev script, Quadlet unit, docs).
- Run `sudo setsebool -P container_use_devices=true` on the Fedora-based VM and document it as a required host setup step, not an app concern.
- Verify GPU visibility as a first-class startup health check (`rocminfo` / `rocm-smi` inside the running app container), not just at build time.

**Warning signs:**
- `rocminfo` works via manual `podman run` but the app's own container reports no GPU or `HSA_STATUS_ERROR`.
- `ausearch -m avc -ts recent` shows denials around container device access.
- GPU-bound TTS calls silently fall back to (very slow) CPU inference instead of erroring.

**Phase to address:**
Infrastructure/deployment setup phase (before TTS integration work begins) — this should be validated with a minimal "GPU echo" container before any Qwen TTS code is written, so GPU access issues are isolated from model issues.

---

### Pitfall 2: Assuming Qwen TTS ROCm support is uniform across model variants and versions

**What goes wrong:**
Team picks a Qwen TTS variant (e.g. a "Base" checkpoint vs. a "CustomVoice"/instruct checkpoint) based on features alone, then discovers on the actual RX 9070 XT that the chosen variant silently fails to generate on ROCm (process loads onto GPU, utilizes it, then exits with no error/output) — a pattern that has been reported specifically for Base models while sibling CustomVoice checkpoints on the same hardware work fine.

**Why it happens:**
Qwen3-TTS is an actively evolving open-weight family; ROCm compatibility is validated primarily on AMD Instinct (datacenter) GPUs on "day 0" support announcements, not consumer RDNA4 cards. Community reports show model-specific silent failures (no error, no warning) on consumer AMD GPUs, and separately, specific `decode_window_frames` values are known to trigger a CUDA-graph-capture bug path that causes a 5-10x slowdown on ROCm. RDNA (consumer) GPUs also use Wave32 execution while most ROCm kernels are tuned for CDNA's Wave64, which can silently degrade performance or break specific ops (e.g. some Flash Attention kernels).
Also relevant: because the LLM (xAI/Grok) runs in the cloud, VRAM contention isn't a factor here — but it's a common trap in similar projects to assume "if the LLM ran locally too" without budgeting VRAM; worth noting even though this project avoids it by using a cloud LLM.

**How to avoid:**
- Pick and pin one specific Qwen TTS checkpoint + revision early, and smoke-test end-to-end generation on the actual RX 9070 XT (not just "loads and shows GPU utilization" — actually confirm audio bytes come out) before building the review UI around it.
- Avoid non-default `decode_window_frames` values unless verified not to hit the ROCm slowdown bug; benchmark generation time per segment early so a 5-10x regression is caught immediately, not after the pipeline is built.
- Track the upstream Qwen3-TTS GitHub issues/discussions for the specific checkpoint in use; ROCm support is a moving target with frequent silent-failure reports.
- Have a CPU-inference fallback path (even if slow) purely for local dev on non-GPU machines, per the project's own constraint that dev should degrade gracefully without the AMD GPU.

**Warning signs:**
- GPU utilization spikes during "generation" but no audio file/short-duration silence is produced.
- Generation time for a short segment is dramatically (5-10x) higher than expected with no error logged.
- Behavior differs between "Base" and "instruct/CustomVoice" variants of the same model size on the same hardware.

**Phase to address:**
TTS integration phase — pin model + do a hardware smoke test before building segment-generation orchestration on top of it.

---

### Pitfall 3: Voice/timbre drift across segments for the same character (segment 3 sounds different from segment 30)

**What goes wrong:**
Because each table row/segment is generated as an independent TTS call, the same character's voice can noticeably drift in timbre, pacing, and prosody between calls — worse than it would be in one continuous generation — since each call is a fresh sampling from the model with no forced continuity. Separately, Qwen3-TTS has a documented tendency for speaking rate to gradually increase over the course of a single long generation once text exceeds roughly 100 characters, and pronunciation/timbre can drift across chunks generally in chunk-based long-form TTS.

**Why it happens:**
This project's design (per-row independent generation, regenerate-single-segment-on-edit) is architecturally well-suited to catching partial edits cheaply, but it inherently maximizes the number of independent sampling boundaries — exactly the condition that causes voice drift in chunk-based TTS systems. Community guidance for other chunk-based systems is "use larger chunks and a fixed seed" to reduce drift — both of which cut against this project's row-level regeneration model.

**How to avoid:**
- Fix and store a per-character/per-voice **seed** (and any other sampling params) so repeated calls for "the same character" reuse the same seed rather than a fresh random one each time — this is the single most impactful, cheapest mitigation and is directly compatible with the row-level regeneration design (store seed alongside voice assignment, not per-row).
- Store the full voice instruction/description text per character (not regenerated per-row) so voice prompts are byte-identical across all of that character's segments — avoid re-deriving or lightly rephrasing voice instructions per row.
- Consider reference-audio voice cloning (if Qwen TTS supports it) using one fixed reference clip per character rather than free-text voice design per call, since free-text "voice design" prompts are more prone to interpretation drift call-to-call than a fixed reference clip.
- Treat "does character X sound the same in segment 3 vs segment 30" as an explicit QA check during the voice-assignment/preview phase, not just spot listening.
- Do not evaluate voice consistency only on short preview clips — the drift is a property of many independent calls over a long work, so it needs to be checked across a real multi-chapter run, not just the wizard preview.

**Warning signs:**
- Preview audio (short, few segments) sounds great; full-book generation sounds inconsistent.
- User notices "narrator sounds different after a while" only on long texts, not short test texts.
- Same character voice instruction text is being silently varied/regenerated by the LLM between chunks (see Pitfall 5).

**Phase to address:**
TTS integration / segment generation phase — seed and voice-prompt persistence should be part of the core data model (character → {voice_instructions, seed, reference_audio}) from the start, not bolted on later.

---

### Pitfall 4: LLM re-identifies the same character with different names/descriptions across chunks of a long novel

**What goes wrong:**
For any novel long enough to exceed a single LLM call's practical working window, the text must be chunked for character-detection/segmentation. Without deliberate cross-chunk continuity, the LLM can introduce a "new" character record for someone already cast in an earlier chunk (e.g. "Tom" in chunk 1 becomes "Thomas" or "the old man" in chunk 4), producing duplicate/fragmented character entries that break voice consistency and bloat the review table.

**Why it happens:**
LLMs process each call largely independently of prior calls unless the full cast list is explicitly re-supplied as context; retrieval/attention research shows information "far from the start and end" of a long context is retrieved less reliably even in current large-context models, and structured-output research shows schema *compliance* (valid JSON) is much more reliable than semantic *correctness* (the right entity, consistently named) — models can emit perfectly valid JSON that is subtly wrong or inconsistent. For a personal library of full novels, this is not an edge case — it's the default failure mode for any naive "split into N chunks, analyze each independently" approach.

**How to avoid:**
- Always pass the **already-established cast list** (name, brief description, ID) as part of the prompt/context for every subsequent chunk's analysis call — never analyze chunk N without chunk 1..N-1's resolved character list in context. This is the single highest-leverage fix.
- Use structured output (JSON schema / function calling) constraining each detected character to either match an existing character ID or explicitly be flagged "new character" — do not let the model freely emit names as unconstrained strings.
- Keep the persistent cast list compact (name + 1-2 line description) rather than full context, since re-supplying full prior text for every chunk is expensive and unnecessary — the goal is entity continuity, not text continuity.
- Because this project explicitly has a human review/edit wizard for the cast before segments are generated, treat that wizard as the safety net: design it to make merging duplicate/renamed characters fast (the pitfall isn't "avoid it 100%" — it's "make correcting it cheap"), since perfect automatic resolution isn't realistic.
- Prefer fewer, larger chunks where the model's context window allows it — reduces the number of cross-chunk boundaries where drift can occur. Grok's larger context windows (128K+ tokens on recent models) may allow many novels to be analyzed in one or few passes rather than many small chunks — verify actual chunking need against real book lengths before assuming heavy chunking is necessary.

**Warning signs:**
- Character list grows suspiciously large relative to the book's actual cast (a 5-character novel producing 12 "characters").
- Same character has near-duplicate entries with slightly different descriptions.
- Character count that grows roughly linearly with chunk count (not with actual story cast size) is a smoking gun.

**Phase to address:**
LLM analysis/segmentation phase — the cast-continuity-passing mechanism must be designed into the chunking strategy itself, not added after the review UI is built. The review/merge wizard (already planned) is the second line of defense and should explicitly support "merge two characters into one."

---

### Pitfall 5: Text chunking for LLM analysis splits mid-scene/mid-dialogue, breaking speaker attribution

**What goes wrong:**
If the raw ebook text is chunked purely by token/character count (for LLM context-window reasons) without respecting paragraph/dialogue boundaries, a chunk boundary can fall in the middle of a conversation, causing the LLM to lose track of who's speaking (dialogue attribution relies on nearby narrative cues like "said Tom" that may be split into the next chunk).

**Why it happens:**
Naive fixed-size chunking (common default in RAG-style pipelines) optimizes for token budgets, not narrative structure. For dialogue-heavy fiction, mid-scene splits are especially damaging because speaker attribution often depends on context several sentences away.

**How to avoid:**
- Chunk on structural boundaries (paragraph breaks, chapter breaks, or scene breaks) rather than raw token counts; only fall back to hard token-count splitting within an oversized single paragraph.
- Use small overlap between chunks (a paragraph or two of trailing context repeated at the start of the next chunk) purely to give the LLM speaker-attribution context, discarding the overlapping analysis output to avoid duplicate segments.
- EPUB structure (chapter files) gives natural, safe split points — chunk at chapter boundaries first, and only sub-chunk within a chapter if it exceeds the context budget.

**Warning signs:**
- Segments near a chunk boundary have wrong/uncertain speaker assignment more often than segments mid-chunk.
- Dialogue attributed to "Narrator" right after a chunk boundary when it should be a character.

**Phase to address:**
Text ingestion/chunking phase (part of LLM analysis phase) — chunking strategy should be chapter/paragraph-aware from the first implementation, not retrofitted.

---

### Pitfall 6: Joining independently-generated TTS segments produces audible clicks, pops, or pacing seams

**What goes wrong:**
Concatenating many independently-generated audio files (via ffmpeg) can produce clicks/pops at boundaries, dead silence gaps that feel unnatural, or — if any segment's format (sample rate, channel count, codec) doesn't exactly match the others — outright broken/desynced output or a hard failure with a non-obvious error message.

**Why it happens:**
ffmpeg's fast `concat` demuxer (stream copy, `-c copy`) requires all inputs to share identical codec/sample-rate/channel-layout; if the TTS engine's output ever varies (e.g. a difference between the "Base" and a differently-configured checkpoint, or WAV vs a resampled MP3 step), the demuxer either fails outright or silently produces a broken/desynced file — sometimes without a clear error. Also, waveform discontinuity exactly at the cut point (non-zero-crossing splice) is what produces audible clicks even when formats match perfectly.

**How to avoid:**
- Standardize TTS output format (fixed sample rate, channel count, bit depth) at the generation step, and verify every segment matches before attempting a fast concat — don't discover a mismatch at join time.
- Prefer the `concat` **filter** (`-filter_complex ... concat=n=N:v=0:a=1`) over the concat demuxer for joining, since it re-encodes and normalizes rather than requiring byte-identical formats — accept the extra CPU cost for correctness given this is a personal/low-volume tool, not a hot path needing stream-copy speed.
- Add a small silence padding or crossfade (a few tens of milliseconds) between segments rather than a hard cut, to avoid audible clicks from waveform discontinuities at splice points — especially important given many segments come from independent TTS calls with no shared trailing/leading silence budget.
- Since editing one row only regenerates that segment then rejoins, the join step runs frequently (not just once at the end) — it must be fast and robust enough to run on every single-row edit, not just treated as a one-time final step. Test the join path under "edit row 50 of 200, rejoin" as a first-class scenario, not just "generate all, join once."

**Warning signs:**
- Occasional segments produce a "pop" on playback at their start/end.
- ffmpeg concat silently produces a shorter/longer output duration than the sum of segment durations.
- Join works fine in dev (few short test segments) but fails/sounds bad on a full book (hundreds of segments, some from re-generation with different params).

**Phase to address:**
Audio generation + joining phase — should be validated with segments deliberately generated at different times/settings (simulating the "edit and regenerate one row" flow) to catch format-mismatch edge cases early, not just tested with a fresh, uniform batch.

---

### Pitfall 7: Long-running generation jobs have no resumable/partial-failure model, so one bad segment kills the whole run

**What goes wrong:**
A full-book generation run can involve hundreds of individual TTS calls over many minutes; if generation is implemented as one big synchronous/in-memory loop, a single segment failure (GPU hiccup, ROCm hang — see Pitfall 2, or a text edge case that hangs the model — e.g. reported mixed-script hangs), a container restart, or the user closing the browser tab can force the entire job to restart from segment 1, wasting significant GPU time and user patience.

**Why it happens:**
It's tempting to implement "generate all segments, then join" as a simple sequential loop for a first version, especially since the row-level architecture already implies per-segment granularity — but without persisting per-segment status (pending/done/failed) and generated audio to disk/DB as each one completes, the system has no way to resume or retry selectively.

**How to avoid:**
- Persist per-segment state (`pending` / `generating` / `done` / `failed`) and the resulting audio file path in the project's saved state as each segment completes — not just at the end of a full run. This is also required anyway by the "edit one row, regenerate only that segment" requirement already in the project, so building it as a first-class per-segment status model (not just a special case) serves both needs.
- Make the generation job idempotent and resumable: on restart/retry, skip segments already marked `done`, and only reprocess `pending`/`failed` ones.
- Surface partial-failure state in the UI ("197/200 segments generated, 3 failed — retry?") rather than a binary success/fail for the whole run, given the project already has a table UI that maps naturally to per-row status.
- Set a timeout per segment generation call so a single hung ROCm/TTS call (known failure mode, see Pitfall 2) doesn't block the whole job indefinitely — fail that segment and move on, rather than hanging the batch.

**Warning signs:**
- No way to tell, from the UI, which specific rows succeeded/failed after a run that "mostly worked."
- Killing/restarting the app mid-generation loses all progress, not just the in-flight segment.
- A single problematic sentence/character (e.g. unusual unicode, mixed scripts, very long row text) hangs the entire batch rather than failing just that row.

**Phase to address:**
Core pipeline/orchestration phase — per-segment status persistence should be designed in from the start since the project's own "regenerate one row" feature already requires this data model; extending it to full-batch resumability is a natural, low-cost extension if done at the same time, but expensive to retrofit later.

---

### Pitfall 8: Container image bloat and disk-space exhaustion from ROCm base images

**What goes wrong:**
ROCm-enabled base images (e.g. `rocm/pytorch`) are commonly tens of gigabytes uncompressed (reports of ~30-54GB), and Podman builds/pulls can fail with "no space left on device" — sometimes due to inode exhaustion rather than raw byte capacity, which is a confusing error to debug — especially on a VM sized primarily around GPU/RAM budget rather than disk.

**Why it happens:**
ROCm images bundle the full compute stack (HIP, MIOpen, rocBLAS, etc.) for broad hardware/framework compatibility; multi-stage builds and layer overhead during the build process consume noticeably more transient disk space than the final image size, and this is easy to underestimate when only the target VM's steady-state disk usage was planned for.

**How to avoid:**
- Provision the VM's storage with explicit headroom for: base ROCm image (~30-50GB class), plus build-time transient layer overhead, plus model weights (Qwen TTS checkpoint(s)), plus generated audio files for saved projects — not just "the app."
- Use `overlay2` storage driver (AMD's documented recommendation) rather than defaults that may be less efficient with large layered images.
- Prefer a slimmer/targeted ROCm base (only the runtime components actually needed for inference, not a full dev/build image) where available, rather than the largest "complete" tag, to reduce both pull time and disk footprint.
- Monitor inode usage (`df -i`), not just byte usage, when diagnosing "no space left on device" during image pulls/builds.

**Warning signs:**
- Podman build/pull fails partway through with disk-space errors despite `df` showing free bytes (check inodes).
- VM disk fills up primarily from container image layers rather than from generated audiobook files.

**Phase to address:**
Deployment/infrastructure setup phase — size the VM's storage budget explicitly before choosing base images, and re-check after the first full ROCm image build.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|------------------|
| Fixed-size (token-count) chunking for LLM text analysis instead of structure-aware chunking | Simple to implement first | Mid-scene splits break dialogue attribution and character continuity (Pitfall 5) | Never for the primary book-analysis path; maybe acceptable as a one-off fallback for malformed/plain .txt with no paragraph structure |
| Re-analyzing each chunk without passing prior cast list as context | Fewer tokens per call, simpler prompt | Duplicate/renamed characters across a long book (Pitfall 4) | Never — cost of passing a compact cast list is small relative to the correctness gain |
| Random/unfixed sampling seed per TTS call | No extra state to manage | Voice drift across segments for the same character (Pitfall 3) | Never for production generation; acceptable only for early prototyping/throwaway tests |
| ffmpeg concat demuxer with `-c copy` instead of the concat filter | Faster joins, less CPU | Silent failures/desync if any segment's format ever diverges (Pitfall 6) | Acceptable only if format uniformity is enforced and verified at generation time; otherwise use the filter |
| Whole-job-in-memory generation loop with no per-segment persistence | Fastest to build a v1 "generate all" flow | Any failure loses all progress; blocks required "regenerate one row" feature anyway (Pitfall 7) | Never — the project's own requirements already demand per-segment state, so there's no scenario where skipping it is actually faster overall |
| Using the largest "complete" ROCm image tag without checking size | One less decision during setup | Wasted disk, slower pulls/rebuilds, harder VM sizing (Pitfall 8) | Acceptable for the very first prototype iteration; revisit before "deployed" milestone |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|-----------------|-------------------|
| Podman + AMD GPU (ROCm) | Assuming a working manual `podman run --device ...` test means the deployed app config will also have GPU access | Bake device flags, `--group-add keep-groups`, and the SELinux `container_use_devices` boolean into the actual deployment unit/Compose file, and re-verify GPU visibility from inside that exact deployment, not just an ad hoc test container |
| Qwen TTS model selection | Picking a checkpoint/variant based on published features without testing it specifically on the RX 9070 XT (RDNA4/gfx1201) | Smoke-test the exact checkpoint + revision on the target GPU before building pipeline code around it; watch for silent (no-error) generation failures reported for some Base-model variants on consumer AMD GPUs |
| xAI/Grok API for text analysis | Sending the full raw novel text in one call and assuming perfect long-context recall, or chunking blindly without re-supplying the resolved cast list each time | Chunk on structural boundaries, always include the running cast list as context, and use structured/schema-constrained output so characters must map to existing IDs or be explicitly flagged new |
| ffmpeg segment joining | Using the concat demuxer (`-c copy`) without verifying every segment shares identical sample rate/channels/codec | Standardize TTS output format at generation time and/or use the concat filter (re-encoding) for robustness, especially since re-joins happen repeatedly as rows are edited |
| Podman image registry / ROCm base images | Not accounting for large transient build-time disk usage on the target VM | Provision disk with explicit headroom beyond the final image size; use overlay2 storage driver |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Sequential, unbatched per-segment TTS generation with no concurrency limit awareness of 16GB VRAM budget | Generation time balloons on long books; possible VRAM exhaustion if any concurrency is attempted naively | Generate segments sequentially (safe default for 16GB VRAM) or with a small, explicitly-tested concurrency cap; measure VRAM headroom before enabling any parallelism | Becomes noticeable on full-length novels (hundreds of segments) even if invisible on short test texts |
| Wrong `decode_window_frames` (or similarly mistuned inference params) hitting a known ROCm CUDA-graph-capture slowdown bug | Generation 5-10x slower than expected on AMD GPU specifically (not reproducible on CUDA references) | Use default/known-good inference parameters for the target ROCm version; benchmark per-segment generation time early and treat major regressions as a red flag, not "just slow hardware" | Present from the first real generation run on the target hardware, not scale-dependent — but easy to misdiagnose as "the GPU is just slow" without a CUDA baseline to compare against |
| ffmpeg concat filter (re-encode) run synchronously on every single-row edit for a long book | UI feels sluggish after every small edit as the whole file re-encodes on each regenerate-one-row action | Consider incremental/segment-cached joining, or accept the re-encode cost but run it async with clear progress feedback rather than blocking the UI | Becomes noticeable as segment count grows into the hundreds (full novel) |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Running the container with excessive/broad device or capability grants "to make GPU passthrough easier" (e.g. `--privileged`) | Wider host attack surface than necessary for a Tailscale-only personal tool | Grant only the specific devices needed (`/dev/kfd`, `/dev/dri`) plus `--group-add keep-groups`; avoid `--privileged` as a shortcut for passthrough troubleshooting |
| Storing the xAI/Grok API key in a Dockerfile/image layer or committed config instead of runtime secret/env injection | API key leakage if the image is ever shared, backed up, or the repo becomes non-private | Inject the API key via Podman secrets or environment variable at runtime, never bake into the image or commit to version control |
| Assuming Tailscale-only exposure means no input validation is needed (e.g. trusting uploaded EPUB/TXT content blindly) | Malformed/malicious EPUB (which is a zip+XML/HTML bundle) could still trigger parser vulnerabilities or resource exhaustion (zip bombs) even in a single-user trusted-network app | Use a well-maintained EPUB parsing library, cap upload file size, and treat parsing as a boundary worth basic validation even though auth is handled by the network layer |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| Full-book generation shown as a single opaque progress bar/spinner with no per-row detail | User can't tell if it's stuck, how much longer, or which segments (if any) failed, for a job that can run many minutes | Surface per-row status directly in the existing table UI (pending/generating/done/failed) since the table already exists as the natural home for this |
| No indication of *why* voice quality/consistency might vary across a long book (e.g. drift issue from Pitfall 3) until the user listens to the full output | Frustrating discovery late in the flow, after significant GPU time already spent | Let users preview/spot-check a few segments spread across the book (not just the first row) before committing to full generation, and mention the seed/voice-consistency mechanism as a working feature, not a silent variable |
| Regenerating a single row silently re-joins the entire output file synchronously, blocking the UI with no feedback | Editing feels laggy/unresponsive on long books as every small tweak triggers a full-file rejoin | Show a lightweight "rejoining..." indicator distinct from "generating audio," and consider whether the rejoin can be visibly fast (format-uniform, cheap concat) vs. must re-encode (slower, needs feedback) |
| Cast auto-detection wizard presents duplicate/near-duplicate characters (from cross-chunk drift, Pitfall 4) without an easy merge action | User has to manually reconcile confusing duplicate entries with no clear tool to fix it | Since a review/merge wizard is already planned, explicitly design "merge two characters" as a first-class, low-friction action, not an afterthought |

## "Looks Done But Isn't" Checklist

- [ ] **GPU passthrough:** Often verified only with a bare `podman run --device ...` test — verify GPU is actually visible from *inside the real deployed app container/Quadlet unit*, not just an ad hoc test.
- [ ] **Voice consistency:** Often verified only on short preview clips in the wizard — verify by listening to segments spread across a full, long real book (not just the first few rows).
- [ ] **Character cast detection:** Often looks correct on short test texts — verify against an actual full-length novel where chunking is required, checking specifically for duplicate/renamed characters.
- [ ] **Audio joining:** Often tested only with a fresh, uniformly-generated batch — verify joining still works cleanly after several individual row regenerations (mixed generation times/params), which is the actual common-case usage pattern given the row-edit-regenerate feature.
- [ ] **Long-running job resilience:** Often only tested with the happy path (short text, no failures) — verify behavior when killing the app mid-generation and restarting: does it resume, or does the user lose all progress?
- [ ] **Disk space on target VM:** Often only checked after initial setup — re-verify after model weights, ROCm image, and a full generated audiobook project are all present simultaneously.
- [ ] **EPUB parsing:** Often tested only on one "clean" EPUB — verify against EPUB2 vs EPUB3 differences, embedded images/footnotes, and unusual chapter/HTML structures from a real personal library, not just one test file.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|----------------|------------------|
| Voice drift discovered after a full-book generation (Pitfall 3) | MEDIUM | Retroactively assign a fixed seed to the character, regenerate only the drifted segments (already supported by the row-level regenerate feature), rejoin |
| Duplicate/renamed characters found late in a long book's cast (Pitfall 4) | LOW-MEDIUM | Use the cast review/merge wizard to merge duplicate entries and reassign affected rows; regenerate only rows whose speaker changed |
| Full generation run fails partway with no per-segment persistence (Pitfall 7, if not prevented) | HIGH | Requires re-running the entire batch from scratch, re-spending all GPU time already used — this is exactly why per-segment persistence should be built in from the start rather than treated as a nice-to-have |
| Audio join produces clicks/desync discovered post-generation (Pitfall 6) | LOW-MEDIUM | Re-run the join step with the concat filter (re-encode) instead of demuxer copy; no need to regenerate any TTS audio, only the join step |
| ROCm image/disk space exhaustion mid-deployment (Pitfall 8) | LOW | Prune unused images/layers (`podman system prune`), switch to a slimmer base image tag, resize VM disk if using a VM with resizable storage |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| ROCm/Podman GPU passthrough fails in real deployment (P1) | Infrastructure/deployment setup phase | GPU visible (`rocm-smi`/`rocminfo`) from inside the actual deployed app container/Quadlet unit, not just a manual test container |
| Qwen TTS ROCm compatibility surprises on RX 9070 XT (P2) | TTS integration phase, before pipeline built around it | End-to-end smoke test: real text in, real audio bytes out, on the actual target GPU, with generation time benchmarked as a sanity check |
| Voice drift across segments (P3) | TTS integration / segment generation phase (data model) | Listen-test spread across a full long book; confirm same character sounds consistent from segment 3 to segment 30+ |
| Character re-identification drift across LLM chunks (P4) | LLM analysis/segmentation phase (chunking + prompting strategy) | Run against a real full-length novel; cast size should roughly match the book's actual character count, not scale with chunk count |
| Chunking splits mid-scene, breaking speaker attribution (P5) | Text ingestion/chunking phase | Spot-check segments near chunk boundaries specifically for speaker-assignment accuracy |
| Audio join produces clicks/format mismatches (P6) | Audio generation + joining phase | Join a set of segments generated at different times/settings (simulating edit-and-regenerate) and listen for boundary artifacts |
| No resumable/partial-failure handling for long generation jobs (P7) | Core pipeline/orchestration phase (same time as per-segment data model for row regeneration) | Kill and restart the app mid-generation; confirm completed segments are preserved and only remaining ones are (re)processed |
| ROCm container image bloat / disk exhaustion (P8) | Deployment/infrastructure setup phase | Confirm VM disk headroom after base image + model weights + a full generated project are all present |

## Sources

- [How to configure AMD GPU for using in Podman containers on RHEL9? - Red Hat Customer Portal](https://access.redhat.com/solutions/7073764)
- [Run ROCm Docker containers — ROCm installation (Linux)](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/how-to/docker.html)
- [AMD GPU subset selection does not work · Issue #21454 · containers/podman](https://github.com/containers/podman/issues/21454)
- [SELinux prevents rootless container from using passed device · Issue #15930 · containers/podman](https://github.com/containers/podman/issues/15930)
- [Qwen3-TTS Technical Report](https://arxiv.org/html/2601.15621v1)
- [Inconsistent speaking rate in long text generation with Qwen3-TTS-12Hz-1.7B-Base · Issue #239 · QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS/issues/239)
- [Qwen3-TTS-12Hz-0.6B-Base not generating with AMD on Linux · Issue #93 · QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS/issues/93)
- [Support for AMD GPUs (ROCm) in Qwen3-TTS Voice Cloning · Discussion #308 · QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS/discussions/308)
- [[Bug] generate_voice_clone() hangs indefinitely on mixed-script Thai inputs · Issue #318 · QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS/issues/318)
- [[Issue]: Windows PyTorch ROCm: MIOpen ... Qwen3-TTS decoder very slow · Issue #3077 · ROCm/TheRock](https://github.com/ROCm/TheRock/issues/3077)
- [Running Qwen TTS on AMD Strix Halo: A Complete Guide - TinyComputers.io](https://tinycomputers.io/posts/qwen-tts-on-amd-strix-halo.html)
- [state of ROCm on Radeon RX 9000 series · Issue #4443 · ROCm/ROCm](https://github.com/ROCm/ROCm/issues/4443)
- [Compatibility matrix - ROCm Documentation - AMD](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html)
- [Qwen3-TTS truncates slow emotional speech because effective max_tokens is capped by text length · Issue #843 · jundot/omlx](https://github.com/jundot/omlx/issues/843)
- [Voice Design - Alibaba Cloud Model Studio Documentation](https://www.alibabacloud.com/help/en/model-studio/qwen-tts-voice-design)
- [Merge Videos with FFmpeg: Concat Demuxer, Filter & Protocol - FFmpeg Micro Blog](https://www.ffmpeg-micro.com/blog/ffmpeg-concat-merge-videos)
- [ROCm pytorch images size · Issue #120 · ROCm/ROCm-docker](https://github.com/ROCm/ROCm-docker/issues/120)
- [Pulling docker image uses too many inodes (no space left on device) · Issue #92 · ROCm/ROCm-docker](https://github.com/ROCm/ROCm-docker/issues/92)
- [The Structured Output Benchmark: A Multi-Source Benchmark for Evaluating Structured Output Quality in Large Language Models](https://arxiv.org/html/2604.25359v1)
- [xAI Grok 4.1 Fast: How the 128k context window and 8k output limit work - datastudios.org](https://www.datastudios.org/post/xai-grok-4-1-fast-how-the-128k-context-window-and-8k-output-limit-work-for-large-chats-documents)
- [Background tasks with progress updates: UI patterns that work - AppMaster](https://appmaster.io/blog/background-tasks-progress-ui)
- [Restart a Job on Failure and Continue in Spring Batch - Baeldung](https://www.baeldung.com/spring-batch-restart-job-failure-continue)

---
*Pitfalls research for: self-hosted ebook-to-audiobook narration app (LLM segmentation + AMD ROCm TTS + audio joining)*
*Researched: 2026-07-09*
