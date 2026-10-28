#!/bin/bash
# Note: This code is purely AI-generated.
# X2 build-line guard (shared by pre-commit and pre-push).
# Blocks work on a branch that is NOT the line declared in roms/BUILD_TARGET.
# Escape hatch for deliberate cross-line maintenance: X2_COMMIT_OTHER_LINE=1
set -u

find_target_file() {
  local d="$PWD"
  while [ "$d" != "/" ] && [ -n "$d" ]; do
    [ -f "$d/roms/BUILD_TARGET" ] && { printf '%s' "$d/roms/BUILD_TARGET"; return 0; }
    d=$(dirname "$d")
  done
  return 1
}

target_file=$(find_target_file) || {
  echo "X2 guard: could not locate roms/BUILD_TARGET above $PWD" >&2
  exit 1
}
target=$(sed -e 's/<!--.*-->//' -e 's/#.*//' "$target_file" | grep -v '^[[:space:]]*$' | head -1 | tr -d '[:space:]')
[ -n "$target" ] || { echo "X2 guard: BUILD_TARGET is empty" >&2; exit 1; }

branch=$(git symbolic-ref --short HEAD 2>/dev/null || echo '(detached)')
[ "$branch" = "$target" ] && exit 0

if [ "${X2_COMMIT_OTHER_LINE:-0}" = "1" ]; then
  echo "X2 guard: proceeding on '$branch' (declared build line: '$target') — override X2_COMMIT_OTHER_LINE=1 accepted." >&2
  exit 0
fi

cat >&2 <<EOF

==================================================================
  X2 BUILD-LINE GUARD — BLOCKED
    current branch : $branch
    declared line  : $target
    declaration    : $target_file

  This branch is NOT the line we are building. Committing here is the
  exact mistake that has burned multiple 12-15h bake cycles: the work
  looks correct locally but the build clones a different branch.

    Fix for the next build :  git checkout $target
    Deliberate other line  :  X2_COMMIT_OTHER_LINE=1 git <command>
==================================================================
EOF
exit 1
