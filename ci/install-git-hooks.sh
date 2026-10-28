#!/bin/bash
# Note: This code is purely AI-generated.
# Install the X2 build-line guard into every repo of this project.
# Hooks are HARD COPIES (not symlinks) per the workspace rule that forbids
# symlinks from ~/Projects into system/tooling locations.
set -eu

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
SRC="$ROOT/roms/common/tools/git-hooks"
TARGET_FILE="$ROOT/roms/BUILD_TARGET"

[ -f "$TARGET_FILE" ] || { echo "missing $TARGET_FILE" >&2; exit 1; }
line=$(sed -e 's/<!--.*-->//' -e 's/#.*//' "$TARGET_FILE" | grep -v '^[[:space:]]*$' | head -1 | tr -d '[:space:]')

printf 'declared build line: %s\n\n' "$line"
for rel in roms/common/device/X2 roms/common/vendor/realme roms/common/kernel/sm6150 roms/lineage/manifests; do
  repo="$ROOT/$rel"
  [ -d "$repo/.git" ] || continue
  hooks=$(git -C "$repo" rev-parse --git-path hooks)
  case "$hooks" in /*) ;; *) hooks="$repo/$hooks" ;; esac
  mkdir -p "$hooks"
  cp "$SRC/_guard.sh" "$SRC/pre-commit" "$SRC/pre-push" "$hooks/"
  chmod +x "$hooks/_guard.sh" "$hooks/pre-commit" "$hooks/pre-push"
  printf '  installed -> %-30s (%s)\n' "$rel" "$(basename "$hooks")"
done
printf '\nDone. Test: cd into a repo on the wrong branch and run: git commit --allow-empty -m test\n'
