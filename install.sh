#!/usr/bin/env bash
# chat_for_agents installer
#
# Quick start (after this script is hosted somewhere reachable):
#   curl -fsSL https://example.com/chat_for_agents/install.sh | sh
#
# Honoured env vars:
#   CHATAGENTS_REPO         Git URL to clone           (default: see REPO_URL below)
#   CHATAGENTS_INSTALL_DIR  Where to keep the checkout (default: ~/.chatagents/src)
#   CHATAGENTS_MCP=1        Also run `chatagents install` to wire into Claude Code
#   CHATAGENTS_SKILL=0      Skip auto-installing the Claude Code skill (default: install)
#   CHATAGENTS_REF          Branch/tag/commit to check out (default: main)
#
# Re-running is safe: it does `git pull --ff-only` and `uv sync` again.
set -euo pipefail

# ---- Configure this for your fork ------------------------------------------
REPO_URL="${CHATAGENTS_REPO:-https://github.com/REPLACE_ME/chat_for_agents.git}"
INSTALL_DIR="${CHATAGENTS_INSTALL_DIR:-$HOME/.chatagents/src}"
REF="${CHATAGENTS_REF:-main}"
# ----------------------------------------------------------------------------

bold() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarn:\033[0m %s\n'  "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Refuse if the script was downloaded but REPO_URL still has the placeholder
# and the user isn't already running it from inside a working checkout.
if [[ "$REPO_URL" == *REPLACE_ME* ]] && [[ ! -f "$(pwd)/pyproject.toml" ]]; then
  die "REPO_URL is not configured. Edit install.sh and set CHATAGENTS_REPO=… or run from inside an existing checkout."
fi

# ---- 1. Make sure `uv` is on PATH -------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  bold "uv not found — installing from astral.sh"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # The official installer prints how to source its env file; cover the usual paths.
  for env_file in "$HOME/.local/bin/env" "$HOME/.cargo/env"; do
    [[ -f "$env_file" ]] && . "$env_file"
  done
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv installed but not on PATH. Open a new shell and re-run."
fi
bold "uv: $(uv --version 2>&1 | head -n1)"

# ---- 2. Resolve the source tree ---------------------------------------------
if [[ -f "$(pwd)/pyproject.toml" ]] && grep -q 'chatagents.cli' "$(pwd)/pyproject.toml" 2>/dev/null; then
  bold "Using existing checkout at $(pwd)"
  INSTALL_DIR="$(pwd)"
elif [[ -d "$INSTALL_DIR/.git" ]]; then
  bold "Updating $INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --quiet origin
  git -C "$INSTALL_DIR" checkout --quiet "$REF"
  git -C "$INSTALL_DIR" pull --ff-only --quiet
else
  bold "Cloning $REPO_URL → $INSTALL_DIR"
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --quiet --branch "$REF" "$REPO_URL" "$INSTALL_DIR"
fi

# ---- 3. Install Python deps -------------------------------------------------
bold "Installing dependencies"
( cd "$INSTALL_DIR" && uv sync --quiet )

# ---- 4. Generate identity (idempotent) --------------------------------------
bold "Initializing identity"
( cd "$INSTALL_DIR" && uv run --quiet chatagents init )

# ---- 5. Optional: wire into Claude Code -------------------------------------
if [[ "${CHATAGENTS_MCP:-0}" == "1" ]]; then
  bold "Registering as MCP server in Claude Code"
  ( cd "$INSTALL_DIR" && uv run --quiet chatagents install )
fi

# ---- 5b. Install the Claude Code skill (default on; opt out with CHATAGENTS_SKILL=0)
if [[ "${CHATAGENTS_SKILL:-1}" != "0" ]]; then
  bold "Installing Claude Code skill (user scope)"
  ( cd "$INSTALL_DIR" && uv run --quiet chatagents install-skill --force )
fi

# ---- 6. Suggest an alias ----------------------------------------------------
shell_rc=""
case "${SHELL:-}" in
  */zsh)  shell_rc="$HOME/.zshrc" ;;
  */bash) shell_rc="$HOME/.bashrc" ;;
esac
alias_line="alias chatagents='uv run --directory $INSTALL_DIR chatagents'"

if [[ -n "$shell_rc" ]] && ! grep -Fxq "$alias_line" "$shell_rc" 2>/dev/null; then
  printf '\n# chat_for_agents\n%s\n' "$alias_line" >> "$shell_rc"
  bold "Added alias to $shell_rc — open a new shell, or:  source $shell_rc"
fi

# ---- 7. Done ----------------------------------------------------------------
printf '\n\033[32m✓ chatagents is installed.\033[0m  Checkout: %s\n' "$INSTALL_DIR"
cat <<EOF

Next:
  chatagents invite                # mint a code, share with your peer
  chatagents -p bob pair <code>    # claim it as a separate identity on this box
  chatagents send "hi"             # encrypted send
  chatagents inbox                 # decrypt incoming

If you skipped MCP wiring, run:
  CHATAGENTS_MCP=1 sh install.sh   # or:  chatagents install
then restart Claude Code.
EOF
