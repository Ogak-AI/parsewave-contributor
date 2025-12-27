#!/usr/bin/env bash
set -euo pipefail

# This script launches a Linux container with Claude Code CLI, runs `claude`,
# and then extracts the generated credential file to the host at
#   ${HOME}/.claude/.credentials.json
# It supports macOS hosts where Claude Desktop stores tokens in Keychain and not as files.

IMAGE_NAME="macos-claude-auth-helper:latest"
CONTAINER_NAME="macos-claude-auth-helper-$(date +%s)"
HOST_CLAUDE_DIR="${HOME}/.claude"
HOST_CRED_PATH="${HOST_CLAUDE_DIR}/.credentials.json"

cat <<'GUIDE'
[Claude macOS Auth Helper]

On macOS hosts Claude Code CLI stores tokens in Keychain and not as files as on Linux.
If you use macOS and want to run a task using Claude agent with your Claude subscription
instead of using API key (`uv run tb run --agent claude-code --use-subscription ...`),
you need to run this script to setup the credentials.

This script will:
- Build a small Linux container with the Claude Code CLI
- Launch `claude` interactively inside the container so you can log in
- After you close Claude, copy /root/.claude/.credentials.json from the container
  to ${HOME}/.claude/.credentials.json on your Mac (replacing any old directory)
- Remove the temporary container

Instructions:
1) Continue and wait for Claude to open in the container
2) Choose Claude account with subscription
3) Complete the interactive login: 
   3.1) Open the link in your browser when shown
   3.2) Login into your Claude account if not already
   3.3) Click Authorize to connect the account to Claude CLI
   3.4) Copy the authorization code from the browser and paste it into the CLI
   3.5) Wait for "Login successful", then press Enter
4) Exit Claude (Ctrl+C or the /exit command)
5) The script will save credentials and clean up automatically

Press Enter to continue, or Ctrl+C to cancel.
GUIDE
read -r _

echo "[1/5] Building auth helper image..."
docker build -t "${IMAGE_NAME}" -f docker/macos-claude-auth/Dockerfile .

echo "[2/5] Starting container and launching 'claude' (interactive)..."
# Run interactive 'claude'; when the user exits Claude, the container exits immediately
docker run -it --name "${CONTAINER_NAME}" "${IMAGE_NAME}" bash -lc "claude"

echo "[3/5] Ensuring host Claude directory exists..."
mkdir -p "${HOST_CLAUDE_DIR}"

echo "[4/5] Preparing destination..."
if [ -d "${HOST_CRED_PATH}" ]; then
  backup_path="${HOST_CRED_PATH}.backup-$(date +%Y%m%d-%H%M%S)"
  echo "Detected directory at ${HOST_CRED_PATH}. Backing up to ${backup_path} and replacing with file."
  mv "${HOST_CRED_PATH}" "${backup_path}"
fi

echo "Copying credentials from container..."
if docker cp "${CONTAINER_NAME}:/root/.claude/.credentials.json" "${HOST_CRED_PATH}" 2>/dev/null; then
  chmod 600 "${HOST_CRED_PATH}" || true
  echo "Credentials copied to ${HOST_CRED_PATH}"
else
  echo "ERROR: Could not find /root/.claude/.credentials.json in the container."
  echo "If you saw a login URL, ensure you completed it before exiting the container shell."
  echo "You can re-run: docker start -ai ${CONTAINER_NAME} and run 'claude login' again."
  exit 1
fi

echo "[5/5] Cleaning up container..."
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

echo "Done. Claude credentials are now available on the host."

