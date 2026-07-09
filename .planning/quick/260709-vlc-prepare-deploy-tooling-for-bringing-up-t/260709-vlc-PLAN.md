---
phase: quick-260709-vlc
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - deploy/run-local.sh
  - deploy/bootstrap-vm.sh
  - deploy/README.md
autonomous: true
requirements: [D-09]
must_haves:
  truths:
    - "run-local.sh runs on a from-scratch Debian 13 VM with no dev-host-specific GPU flags applied by default"
    - "Dev host can still opt back into the old flags via env vars"
    - "A fresh Debian 13 host can be bootstrapped (Podman + Tailscale install, render/video groups, repo clone) by running one idempotent script"
    - "deploy/README.md documents Tailscale SSH access, the bootstrap step, and the D-09 re-verification checklist"
  artifacts:
    - path: "deploy/bootstrap-vm.sh"
      provides: "Idempotent one-time host setup for a fresh Debian 13 VM"
      contains: "set -euo pipefail"
    - path: "deploy/run-local.sh"
      provides: "GPU flags gated behind empty-default env vars"
    - path: "deploy/README.md"
      provides: "VM bring-up section"
  key_links:
    - from: "deploy/run-local.sh"
      to: "GPU_SECURITY_OPT / HSA_OVERRIDE_GFX_VERSION env vars"
      via: "conditional flag construction"
      pattern: "GPU_SECURITY_OPT"
---

<objective>
Prepare deploy tooling so moving dev/testing onto the production RX 9070 XT
(gfx1201) Debian 13 VM is fast once that VM exists. The VM does not exist yet —
this is static preparation, verified by syntax/grep checks only, not against a
live host.

Two gaps to close:
1. `run-local.sh` hardcodes GPU-passthrough workarounds proven only on the dev
   host's unsupported gfx1103 iGPU. Make them env-overridable with empty
   defaults so the script is correct on a from-scratch gfx1201 VM, while the dev
   host can opt back in.
2. Nothing automates one-time host setup. Add an idempotent `bootstrap-vm.sh`.

Plus a short VM bring-up section in `deploy/README.md`.

Purpose: De-risk and speed up production VM bring-up (D-09 follow-up).
Output: Edited `run-local.sh`, new `bootstrap-vm.sh`, extended `README.md`.
</objective>

<execution_context>
@/home/oton/.claude/plugins/cache/gsd-plugin/gsd/4.0.4/workflows/execute-plan.md
@/home/oton/.claude/plugins/cache/gsd-plugin/gsd/4.0.4/templates/summary.md
</execution_context>

<context>
@deploy/run-local.sh
@deploy/README.md

# backend/GPU-ENABLEMENT.md — READ for context on why the gfx1103 dev host needs
# --security-opt label=disable (SELinux container_use_devices gap) and
# HSA_OVERRIDE_GFX_VERSION=11.0.0 (spoofs gfx1103->gfx1100). DO NOT MODIFY it.
@backend/GPU-ENABLEMENT.md

<constraints>
- No live VM exists. All <verify> steps are static: `bash -n`, grep, doc-consistency.
- Do NOT auto-run `tailscale up` (needs interactive auth) — print the command instead.
- Do NOT modify backend/GPU-ENABLEMENT.md. A forward-pointer from README is fine.
- run-local.sh change is surgical, not a rewrite.
</constraints>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Gate run-local.sh GPU workaround flags behind empty-default env vars</name>
  <files>deploy/run-local.sh</files>
  <action>
Make the two dev-host-specific GPU workarounds opt-in via env vars with EMPTY
defaults, so a from-scratch gfx1201 Debian 13 VM gets neither by default (D-09:
gfx1201 is officially ROCm-supported, so neither should be needed), while the
dev host can re-enable them by exporting the vars.

In the config block near the top (alongside POD_NAME etc.), add:
  - `GPU_SECURITY_OPT="${GPU_SECURITY_OPT:-}"` — empty default. When set, its
    value is passed as `--security-opt <value>` (dev host sets it to
    `label=disable`).
  - `HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION:-}"` — empty default.
    When set, passed as `-e HSA_OVERRIDE_GFX_VERSION=<value>` (dev host sets it
    to `11.0.0`).

Rewrite the `podman run ... ${POD_NAME}-tts` invocation (currently lines ~54-60)
to build the optional flags into a bash array before the call, e.g. a
`tts_gpu_flags=()` array that appends `--security-opt "${GPU_SECURITY_OPT}"`
only when non-empty and `-e "HSA_OVERRIDE_GFX_VERSION=${HSA_OVERRIDE_GFX_VERSION}"`
only when non-empty, then expand `"${tts_gpu_flags[@]}"` in the podman run. Keep
`--device /dev/kfd --device /dev/dri` and `--group-add keep-groups` unconditional
(those are universal, per GPU-ENABLEMENT.md). Preserve the HF cache volume mount.

Update the adjacent comment block: replace the "proven rung-2 fallback-ladder"
note with one line stating the two workaround flags are now empty by default and
opt-in via `GPU_SECURITY_OPT` / `HSA_OVERRIDE_GFX_VERSION` for the gfx1103 dev
host, and are expected to be unneeded on the gfx1201 VM (D-09).

Note the array is only used when non-empty, so `set -u` is safe (guard the
expansion or initialize the array — an empty-array `"${arr[@]}"` under `set -u`
is fine on modern bash but initialize it explicitly to be safe).
  </action>
  <verify>
    <automated>bash -n deploy/run-local.sh && grep -q 'GPU_SECURITY_OPT:-}' deploy/run-local.sh && grep -q 'HSA_OVERRIDE_GFX_VERSION:-}' deploy/run-local.sh && ! grep -Eq 'label=disable[^"]*\\\\$' deploy/run-local.sh && ! grep -q 'HSA_OVERRIDE_GFX_VERSION=11.0.0' deploy/run-local.sh</automated>
  </verify>
  <done>run-local.sh passes `bash -n`; both flags are gated behind empty-default env vars; no hardcoded `label=disable` line or `HSA_OVERRIDE_GFX_VERSION=11.0.0` remains in the podman run.</done>
</task>

<task type="auto">
  <name>Task 2: Add idempotent deploy/bootstrap-vm.sh for a fresh Debian 13 host</name>
  <files>deploy/bootstrap-vm.sh</files>
  <action>
Create `deploy/bootstrap-vm.sh` matching run-local.sh style: `#!/usr/bin/env bash`,
`set -euo pipefail`, a `log() { echo "[bootstrap-vm] $*"; }` helper, and a short
header comment explaining it is one-time idempotent setup for a fresh Debian 13
(trixie) host targeting the RX 9070 XT (gfx1201) VM.

Steps, each idempotent (safe to re-run):
1. Install Podman via apt: only run `sudo apt-get update && sudo apt-get install -y podman`
   if `command -v podman` is missing. Log whether it was already present.
2. Install Tailscale via the official install script only if `command -v tailscale`
   is missing: `curl -fsSL https://tailscale.com/install.sh | sh`. Then log — do
   NOT run — the exact next command for the user: `sudo tailscale up --ssh`
   (mention `--ssh` enables Tailscale SSH; it requires interactive auth).
3. Add the invoking user to the `render` and `video` groups (needed for
   /dev/kfd + /dev/dri access without root, per GPU-ENABLEMENT.md). Use
   `sudo usermod -aG render,video "$USER"` guarded by an `id -nG` check so it is a
   no-op if already a member; log that the user must re-login (or `newgrp`) for
   group membership to take effect.
4. Clone the repo if not already present: if the target dir (default
   `${CLONE_DIR:-$HOME/qwen-ebook}`) does not contain a `.git`, run
   `git clone https://github.com/otonm/qwen-ebook "${CLONE_DIR}"`; otherwise log
   that it already exists and skip. Ensure `git` is installed (apt-get install -y
   git guarded by `command -v git`).

End with a `log` summary listing the two manual follow-ups the script deliberately
does NOT do: run `sudo tailscale up --ssh`, and re-login for group changes. Make
the file executable-friendly (the executor may `chmod +x`, but invocation via
`bash deploy/bootstrap-vm.sh` must work).
  </action>
  <verify>
    <automated>bash -n deploy/bootstrap-vm.sh && grep -q 'set -euo pipefail' deploy/bootstrap-vm.sh && grep -q 'usermod -aG render,video' deploy/bootstrap-vm.sh && grep -q 'github.com/otonm/qwen-ebook' deploy/bootstrap-vm.sh && grep -q 'tailscale up' deploy/bootstrap-vm.sh && ! grep -Eq '^[^#]*sudo tailscale up' deploy/bootstrap-vm.sh</automated>
  </verify>
  <done>bootstrap-vm.sh passes `bash -n`; installs Podman/Tailscale/git idempotently; adds render+video groups; clones the public repo; prints but never executes `tailscale up`.</done>
</task>

<task type="auto">
  <name>Task 3: Add VM bring-up section to deploy/README.md</name>
  <files>deploy/README.md</files>
  <action>
Add a new section (place it before the existing "Follow-up: re-verify on the
production RX 9070 XT VM (D-09)" section, or fold into a "Production VM bring-up"
section just above it) covering:

1. **Reaching the VM** — the VM joins the user's tailnet and is reached via
   Tailscale SSH at its Tailscale hostname (`ssh <user>@<tailscale-hostname>`).
   Note it has no public internet exposure (matches the project's Tailscale-only
   access model).
2. **One-time bootstrap** — run `bash deploy/bootstrap-vm.sh` once on the fresh
   Debian 13 host. State what it does (Podman + Tailscale + git install, render/
   video groups, repo clone) and the two manual follow-ups it leaves to the user
   (`sudo tailscale up --ssh`, then re-login for group membership).
3. **D-09 GPU re-verification checklist** — a concise numbered checklist:
   run `bash deploy/run-local.sh` with NO GPU-flag env vars set; confirm a real
   `POST /projects` (or `/synthesize`) request returns audible, intelligible
   audio; only if a genuine failure is reproduced, fall back by exporting
   `HSA_OVERRIDE_GFX_VERSION` and/or `GPU_SECURITY_OPT` — do NOT pre-emptively
   carry the dev-host workarounds over. Add a one-line forward-pointer to
   `backend/GPU-ENABLEMENT.md` as the historical gfx1103 investigation log.

Keep the existing D-09 section's content coherent (avoid duplicating it — either
merge or cross-reference). Do not modify backend/GPU-ENABLEMENT.md.
  </action>
  <verify>
    <automated>grep -qi 'tailscale' deploy/README.md && grep -q 'bootstrap-vm.sh' deploy/README.md && grep -q 'GPU_SECURITY_OPT' deploy/README.md && grep -q 'HSA_OVERRIDE_GFX_VERSION' deploy/README.md</automated>
  </verify>
  <done>README.md documents Tailscale SSH access, the bootstrap step, and the D-09 re-verification checklist referencing the new env vars; env-var names match those introduced in run-local.sh.</done>
</task>

</tasks>

<verification>
- `bash -n` passes for both `deploy/run-local.sh` and `deploy/bootstrap-vm.sh`.
- No hardcoded `label=disable` / `HSA_OVERRIDE_GFX_VERSION=11.0.0` remains in run-local.sh's podman run.
- README references the same env var names introduced in run-local.sh (consistency check).
- `tailscale up` appears only as printed guidance, never executed unconditionally.
</verification>

<success_criteria>
- run-local.sh: GPU workaround flags empty by default, opt-in via env vars, dev host can re-enable.
- bootstrap-vm.sh: idempotent Debian 13 setup — Podman, Tailscale (install only), render+video groups, repo clone.
- README: VM bring-up section (Tailscale SSH, bootstrap, D-09 checklist) consistent with the new env vars.
</success_criteria>

<output>
Create `.planning/quick/260709-vlc-prepare-deploy-tooling-for-bringing-up-t/260709-vlc-SUMMARY.md` when done.
</output>
