#!/usr/bin/env bash
# One-command local full-stack bring-up: builds both container images,
# starts the two-container Podman pod (DEPL-01: GPU devices on the `tts`
# container only), waits for the TTS service to report ready, and prints a
# ready-to-use curl command against the backend.
#
# Runs rootful (`sudo podman`) throughout. D-09 hardware verification on the
# production gfx1201 VM found rootless `--group-add keep-groups` does not
# grant real /dev/kfd access on this host/Podman/crun combination — the
# render/video host GIDs get lost in the rootless user-namespace mapping
# even with correct group membership. Root avoids that mapping entirely.
#
# See deploy/README.md for the two-container isolation rationale.
set -euo pipefail

PODMAN="sudo podman"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"

POD_NAME="${POD_NAME:-qwen-ebook}"
BACKEND_IMAGE="localhost/qwen-ebook-backend:dev"
TTS_IMAGE="localhost/qwen-ebook-tts:dev"
BACKEND_HOST_PORT="${BACKEND_HOST_PORT:-8000}"
# Model load includes a multi-GB Hugging Face download on a cold cache —
# 180s is not enough for a first run. A named volume (below) makes every
# run after the first one fast, but the default timeout still needs enough
# headroom for that first download.
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-900}"
HF_CACHE_VOLUME="${HF_CACHE_VOLUME:-qwen-ebook-tts-hf-cache}"
# gfx1103-dev-host-only GPU workarounds (see backend/GPU-ENABLEMENT.md).
# Empty by default so a from-scratch gfx1201 production VM (D-09, officially
# ROCm-supported) gets neither; the dev host opts back in by exporting these.
GPU_SECURITY_OPT="${GPU_SECURITY_OPT:-}"
HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION:-}"

log() { echo "[run-local] $*"; }

cleanup_existing_pod() {
  if ${PODMAN} pod exists "${POD_NAME}" 2>/dev/null; then
    log "Removing existing pod '${POD_NAME}'..."
    ${PODMAN} pod rm -f "${POD_NAME}" >/dev/null
  fi
}

log "Building backend image (${BACKEND_IMAGE})..."
# Context is the repo root (not backend/) so the Containerfile's frontend
# build stage can COPY frontend/ — the backend now serves the built React
# app itself (StaticFiles mount in app.main), no separate frontend
# container/nginx.
${PODMAN} build -f "${BACKEND_DIR}/Containerfile.backend" -t "${BACKEND_IMAGE}" "${REPO_ROOT}"

log "Building TTS image (${TTS_IMAGE})..."
${PODMAN} build -f "${BACKEND_DIR}/Containerfile.tts" -t "${TTS_IMAGE}" "${BACKEND_DIR}"

cleanup_existing_pod

log "Creating pod '${POD_NAME}' (only port ${BACKEND_HOST_PORT} published to the host; TTS port 8001 stays internal, T-03-01)..."
${PODMAN} pod create --name "${POD_NAME}" -p "${BACKEND_HOST_PORT}:8000"

log "Starting TTS container (GPU devices /dev/kfd + /dev/dri passed ONLY here, per DEPL-01)..."
# GPU_SECURITY_OPT / HSA_OVERRIDE_GFX_VERSION are empty by default (unneeded
# on the gfx1201 production VM, D-09) and only opt-in on the gfx1103 dev host
# via env vars (set GPU_SECURITY_OPT to "label=disable" and
# HSA_OVERRIDE_GFX_VERSION to "11.0.0" to restore the old dev-host behavior)
# — see backend/GPU-ENABLEMENT.md for why the dev host needs them.
# --user 0:0 (root inside the container) is what actually grants /dev/kfd
# access under rootful Podman — the image's baked-in non-root USER has no
# path to the host's render/video GIDs otherwise. --device x2 stays
# unconditional (universal). The named volume persists the Hugging Face
# model download across pod restarts (several GB; without this every
# restart re-downloads it).
tts_gpu_flags=()
[ -n "${GPU_SECURITY_OPT}" ] && tts_gpu_flags+=(--security-opt "${GPU_SECURITY_OPT}")
[ -n "${HSA_OVERRIDE_GFX_VERSION}" ] && tts_gpu_flags+=(-e "HSA_OVERRIDE_GFX_VERSION=${HSA_OVERRIDE_GFX_VERSION}")
${PODMAN} run -d --pod "${POD_NAME}" --name "${POD_NAME}-tts" \
  --user 0:0 \
  --device /dev/kfd --device /dev/dri \
  "${tts_gpu_flags[@]}" \
  -v "${HF_CACHE_VOLUME}:/home/ubuntu/.cache/huggingface" \
  "${TTS_IMAGE}"

log "Starting backend container (no GPU devices; TTS_BACKEND=http, TTS_SERVICE_URL=http://localhost:8001)..."
${PODMAN} run -d --pod "${POD_NAME}" --name "${POD_NAME}-backend" \
  -e TTS_BACKEND=http \
  -e TTS_SERVICE_URL=http://localhost:8001 \
  "${BACKEND_IMAGE}"

log "Waiting up to ${HEALTH_TIMEOUT_SECONDS}s for TTS /healthz (model load can take a few minutes)..."
elapsed=0
until ${PODMAN} exec "${POD_NAME}-tts" python3 -c \
  "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/healthz', timeout=3).status == 200 else 1)" \
  >/dev/null 2>&1; do
  if [ "${elapsed}" -ge "${HEALTH_TIMEOUT_SECONDS}" ]; then
    log "ERROR: TTS /healthz did not become ready within ${HEALTH_TIMEOUT_SECONDS}s."
    log "Inspect logs with: sudo podman logs ${POD_NAME}-tts"
    exit 1
  fi
  sleep 3
  elapsed=$((elapsed + 3))
done

log "TTS service is ready."
log "Pod '${POD_NAME}' is up. GPU devices are on '${POD_NAME}-tts' only (verify: sudo podman inspect ${POD_NAME}-tts --format '{{.HostConfig.Devices}}')."
log ""
log "Try it:"
log "  curl -F file=@sample.txt http://127.0.0.1:${BACKEND_HOST_PORT}/projects -o audiobook.wav"
log ""
log "Tear down with: sudo podman pod rm -f ${POD_NAME}"
