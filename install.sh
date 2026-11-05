#!/bin/sh
# install.sh — put open-computer-use on this Mac for coding agents. Idempotent.
#
#   1. the accessibility bridge, compiled from this checkout
#   2. `open-computer-use` on PATH, as an editable uv tool that follows this checkout
#   3. the skill, into every agent skill directory that exists
#
# Re-run after moving this repository: the tool and the bridge both live in it.
set -eu

REPO="$(cd "$(dirname "$0")" && pwd -P)"

"$REPO/scripts/build.sh" >/dev/null
echo "bridge: $REPO/open_computer_use/bin/axbridge"

# --editable: a `git pull` here is the update, and the bridge rebuilds itself
# when its source is newer than the binary.
uv tool install --quiet --force --python 3.12 --editable "$REPO"
echo "command: $(command -v open-computer-use || echo "open-computer-use (add ~/.local/bin to PATH)")"

# SKILL.md is copied, never linked: Claude Code and Codex both skip a skill whose
# SKILL.md is a symlink, silently.
for dir in ${OCU_SKILL_DIRS:-"$HOME/.claude/skills" "$HOME/.codex/skills"}; do
  [ -d "$dir" ] || continue
  mkdir -p "$dir/open-computer-use"
  cp "$REPO/skill/open-computer-use/SKILL.md" "$dir/open-computer-use/SKILL.md"
  echo "skill: $dir/open-computer-use"
done

echo
echo "Once: System Settings > Privacy & Security > Accessibility, enable each app agents run in"
echo "(the terminal, Codex), then restart it. Check with: open-computer-use status"
