#!/usr/bin/env bash
# One-command local full-stack bring-up: builds both container images,
# starts the two-container Podman pod (DEPL-01: GPU devices on the `tts`
# container only), waits for the TTS service to report ready, and prints a
# ready-to-use curl command against the backend.
#
# See deploy/README.md for the two-container isolation rationale and the
# D-09 production-hardware re-verification follow-up.
set -euo pipefail

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

log() { echo "[run-local] $*"; }

cleanup_existing_pod() {
  if podman pod exists "${POD_NAME}" 2>/dev/null; then
    log "Removing existing pod '${POD_NAME}'..."
    podman pod rm -f "${POD_NAME}" >/dev/null
  fi
}

log "Building backend image (${BACKEND_IMAGE})..."
podman build -f "${BACKEND_DIR}/Containerfile.backend" -t "${BACKEND_IMAGE}" "${BACKEND_DIR}"

log "Building TTS image (${TTS_IMAGE})..."
podman build -f "${BACKEND_DIR}/Containerfile.tts" -t "${TTS_IMAGE}" "${BACKEND_DIR}"

cleanup_existing_pod

log "Creating pod '${POD_NAME}' (only port ${BACKEND_HOST_PORT} published to the host; TTS port 8001 stays internal, T-03-01)..."
podman pod create --name "${POD_NAME}" -p "${BACKEND_HOST_PORT}:8000"

log "Starting TTS container (GPU devices /dev/kfd + /dev/dri passed ONLY here, per DEPL-01)..."
# Flags per backend/GPU-ENABLEMENT.md's proven rung-2 fallback-ladder
# configuration on this local host (--device x2, --group-add keep-groups,
# --security-opt label=disable, HSA_OVERRIDE_GFX_VERSION=11.0.0). On the
# production RX 9070 XT (gfx1201) VM these flags should be re-verified from
# scratch per D-09 — they may not all be necessary there.
# The named volume persists the Hugging Face model download across pod
# restarts (several GB; without this every restart re-downloads it).
podman run -d --pod "${POD_NAME}" --name "${POD_NAME}-tts" \
  --device /dev/kfd --device /dev/dri \
  --group-add keep-groups \
  --security-opt label=disable \
  -e HSA_OVERRIDE_GFX_VERSION=11.0.0 \
  -v "${HF_CACHE_VOLUME}:/root/.cache/huggingface" \
  "${TTS_IMAGE}"

log "Starting backend container (no GPU devices; TTS_BACKEND=http, TTS_SERVICE_URL=http://localhost:8001)..."
podman run -d --pod "${POD_NAME}" --name "${POD_NAME}-backend" \
  -e TTS_BACKEND=http \
  -e TTS_SERVICE_URL=http://localhost:8001 \
  "${BACKEND_IMAGE}"

log "Waiting up to ${HEALTH_TIMEOUT_SECONDS}s for TTS /healthz (model load can take a few minutes)..."
elapsed=0
until podman exec "${POD_NAME}-tts" python3 -c \
  "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/healthz', timeout=3).status == 200 else 1)" \
  >/dev/null 2>&1; do
  if [ "${elapsed}" -ge "${HEALTH_TIMEOUT_SECONDS}" ]; then
    log "ERROR: TTS /healthz did not become ready within ${HEALTH_TIMEOUT_SECONDS}s."
    log "Inspect logs with: podman logs ${POD_NAME}-tts"
    exit 1
  fi
  sleep 3
  elapsed=$((elapsed + 3))
done

log "TTS service is ready."
log "Pod '${POD_NAME}' is up. GPU devices are on '${POD_NAME}-tts' only (verify: podman inspect ${POD_NAME}-tts --format '{{.HostConfig.Devices}}')."
log ""
log "Try it:"
log "  curl -F file=@sample.txt http://127.0.0.1:${BACKEND_HOST_PORT}/projects -o audiobook.wav"
log "  (use 127.0.0.1, not localhost — this host's rootless Podman pasta"
log "   forwarding resets IPv6 ::1 loopback connections; IPv4 works fine)"
log ""
log "Tear down with: podman pod rm -f ${POD_NAME}"
