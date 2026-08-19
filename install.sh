#!/usr/bin/env bash
# Install the gpt-image-bridge skill for Claude Code.
#
# Copies the skill into ~/.claude/skills/gpt-image-bridge/ and makes the
# wrapper executable. Safe to re-run (idempotent).

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$repo_root/skills/gpt-image-bridge"
dst="$HOME/.claude/skills/gpt-image-bridge"

if [[ ! -f "$src/SKILL.md" ]]; then
  echo "install.sh: could not find $src/SKILL.md — run this from the cloned repo." >&2
  exit 1
fi

mkdir -p "$HOME/.claude/skills"
rm -rf "$dst"
cp -R "$src" "$dst"
chmod +x "$dst/bin/gpt-image-2"

echo "✓ Installed gpt-image-bridge skill → $dst"

if ! command -v codex >/dev/null 2>&1; then
  cat >&2 <<'EOF'

⚠  codex CLI is not on your PATH, so the default provider is unavailable.

    macOS:     brew install codex
    any OS:    npm install -g @openai/codex
    Then:      codex login        # log in with your ChatGPT subscription

    Alternative: install Python 3, set ATLASCLOUD_API_KEY, and call the
    wrapper with --provider atlas.

EOF
  exit 0
fi

# codex prints login status to stderr and exits nonzero when logged out,
# so check the exit code rather than grepping a stream.
if ! codex login status >/dev/null 2>&1; then
  echo ""
  echo "⚠  codex is installed but not logged in. Run: codex login" >&2
  exit 0
fi

echo "✓ codex CLI detected and logged in. You're good to go."
echo ""
echo "Test it:"
echo "  ~/.claude/skills/gpt-image-bridge/bin/gpt-image-2 \"a red balloon on a blue sky\" /tmp/test.png"
