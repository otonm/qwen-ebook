#!/usr/bin/env bash
# One-time idempotent setup for a fresh Debian 13 (trixie) host targeting the
# production RX 9070 XT (gfx1201) VM. Safe to re-run — every step checks
# whether it's already done before acting.
#
# Does NOT run `sudo tailscale up` (needs interactive auth) or re-login the
# user into new groups — both are printed as manual follow-ups at the end.
set -euo pipefail

CLONE_DIR="${CLONE_DIR:-$HOME/qwen-ebook}"
REPO_URL="https://github.com/otonm/qwen-ebook"

log() { echo "[bootstrap-vm] $*"; }

# 1. Podman
if command -v podman >/dev/null 2>&1; then
  log "Podman already installed ($(podman --version))."
else
  log "Installing Podman..."
  sudo apt-get update && sudo apt-get install -y podman
fi

# 2. git (needed for the clone step below)
if command -v git >/dev/null 2>&1; then
  log "git already installed."
else
  log "Installing git..."
  sudo apt-get update && sudo apt-get install -y git
fi

# 3. Tailscale (install only; auth is a manual follow-up)
if command -v tailscale >/dev/null 2>&1; then
  log "Tailscale already installed ($(tailscale version | head -n1))."
else
  log "Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
fi
log "Next step (not run by this script): run 'tailscale up --ssh' via sudo"
log "  (--ssh enables Tailscale SSH; this requires interactive auth)"

# 4. render/video groups (needed for /dev/kfd + /dev/dri access without root,
#    per backend/GPU-ENABLEMENT.md)
if id -nG "$USER" | tr ' ' '\n' | grep -qx render && id -nG "$USER" | tr ' ' '\n' | grep -qx video; then
  log "'$USER' already in render and video groups."
else
  log "Adding '$USER' to render and video groups..."
  sudo usermod -aG render,video "$USER"
  log "Group membership added — re-login (or 'newgrp') for it to take effect."
fi

# 5. Clone the repo
if [ -d "${CLONE_DIR}/.git" ]; then
  log "Repo already cloned at ${CLONE_DIR}."
else
  log "Cloning ${REPO_URL} into ${CLONE_DIR}..."
  git clone "${REPO_URL}" "${CLONE_DIR}"
fi

log ""
log "Bootstrap complete. Manual follow-ups this script deliberately does NOT do:"
log "  1. run 'tailscale up --ssh' via sudo   (interactive auth required)"
log "  2. Re-login (or 'newgrp render' / 'newgrp video') for group membership to take effect"
