#!/bin/sh
# install.sh — put open-computer-use on this Mac for coding agents. Idempotent.
#
#   1. the accessibility bridge, compiled from this checkout
#   2. `open-computer-use` on PATH, as an editable uv tool that follows this checkout
#   3. the skill, into every agent skill directory that exists
#
# Re-run after moving this repository: the tool and the bridge both live in it.
#
# Piped from curl there is no checkout beside the script: it puts the latest release (or
# the tag given with `sh -s -- vX.Y.Z`) in ~/.local/share/open-computer-use/repo and runs
# that release's install.sh. Rerunning it is the update.
#
#   curl -fsSL https://raw.githubusercontent.com/max1874/open-computer-use/main/install.sh | sh
set -eu

case $0 in
*install.sh) ;;
*)
  url=https://github.com/max1874/open-computer-use
  tag=${1:-$(curl -fsSLI -o /dev/null -w '%{url_effective}' "$url/releases/latest")}
  tag=${tag##*/}
  case $tag in v*) ;; *) echo "install.sh: no release found" >&2; exit 1 ;; esac
  home="$HOME/.local/share/open-computer-use/repo"
  [ -d "$home/.git" ] || git clone -q "$url.git" "$home"
  git -C "$home" fetch -q --tags origin
  git -C "$home" -c advice.detachedHead=false checkout -q "$tag"
  exec "$home/install.sh"
  ;;
esac

REPO="$(cd "$(dirname "$0")" && pwd -P)"

"$REPO/scripts/build.sh" >/dev/null
echo "bridge: $REPO/open_computer_use/bin/axbridge"

# --editable: a `git pull` here is the update, and the bridge rebuilds itself
# when its source is newer than the binary.
uv tool install --quiet --force --python 3.12 --editable "$REPO"
echo "command: $(command -v open-computer-use || echo "open-computer-use (add ~/.local/bin to PATH)")"

# SKILL.md is copied, never linked: Claude Code and Codex both skip a skill whose
# SKILL.md is a symlink, silently. The skill directory itself may be a link to this
# checkout; then it is already current.
for dir in ${OCU_SKILL_DIRS:-"$HOME/.claude/skills" "$HOME/.agents/skills"}; do
  [ -d "$dir" ] || continue
  if [ ! "$dir/open-computer-use" -ef "$REPO/skills/open-computer-use" ]; then
    mkdir -p "$dir/open-computer-use"
    cp "$REPO/skills/open-computer-use/SKILL.md" "$dir/open-computer-use/SKILL.md"
  fi
  echo "skill: $dir/open-computer-use"
done

echo
echo "Once: System Settings > Privacy & Security > Accessibility, enable each app agents run in"
echo "(the terminal, Codex), then restart it. Check with: open-computer-use status"
