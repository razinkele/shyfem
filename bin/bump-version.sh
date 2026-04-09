#!/bin/bash
#
# bump-version.sh - Automatic version bumping for SHYFEM
#
# Usage: bump-version.sh [major|minor|patch] [--dry-run] [--no-tag] [--no-commit]
#
# Updates version in:
#   - VERSION (first line)
#   - src/utils/shyutil/version.f90 (module parameters)
#   - shyfem-ui/pyproject.toml (Python package)
#   - CHANGELOG.md (moves Unreleased to dated release)
#
# Creates a git tag (v$NEW_VERSION) and commit unless --no-tag/--no-commit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FEMDIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Parse arguments ---

BUMP_TYPE=""
DRY_RUN=false
NO_TAG=false
NO_COMMIT=false

for arg in "$@"; do
    case "$arg" in
        major|minor|patch) BUMP_TYPE="$arg" ;;
        --dry-run)         DRY_RUN=true ;;
        --no-tag)          NO_TAG=true ;;
        --no-commit)       NO_COMMIT=true ;;
        -h|--help)
            echo "Usage: $0 [major|minor|patch] [--dry-run] [--no-tag] [--no-commit]"
            echo ""
            echo "  major       Bump major version (X.0.0)"
            echo "  minor       Bump minor version (x.Y.0)"
            echo "  patch       Bump patch version (x.y.Z)"
            echo "  --dry-run   Show what would change without modifying files"
            echo "  --no-tag    Skip creating a git tag"
            echo "  --no-commit Skip creating a git commit"
            exit 0
            ;;
        *)
            echo "Error: unknown argument '$arg'" >&2
            echo "Usage: $0 [major|minor|patch] [--dry-run] [--no-tag] [--no-commit]" >&2
            exit 1
            ;;
    esac
done

if [ -z "$BUMP_TYPE" ]; then
    echo "Error: specify bump type: major, minor, or patch" >&2
    exit 1
fi

# --- Read current version from version.f90 ---

VERSION_F90="$FEMDIR/src/utils/shyutil/version.f90"
if [ ! -f "$VERSION_F90" ]; then
    echo "Error: $VERSION_F90 not found" >&2
    exit 1
fi

CURRENT_VERSION=$(grep "character\*10, parameter :: version" "$VERSION_F90" | sed "s/.*'\([^']*\)'.*/\1/")
if [ -z "$CURRENT_VERSION" ]; then
    echo "Error: could not parse version from $VERSION_F90" >&2
    exit 1
fi

# --- Compute new version ---

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

case "$BUMP_TYPE" in
    major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
    minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
    patch) PATCH=$((PATCH + 1)) ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"
NEW_VERSION_UNDERSCORE="${MAJOR}_${MINOR}_${PATCH}"
TODAY=$(date "+%d-%m-%Y")
TODAY_ISO=$(date "+%Y-%m-%d")
TODAY_FORTRAN=$(date "+%d.%m.%Y")
YEAR=$(date "+%Y")

echo "Version bump: $CURRENT_VERSION -> $NEW_VERSION ($BUMP_TYPE)"
echo "  Date: $TODAY_ISO"

if $DRY_RUN; then
    echo ""
    echo "[DRY RUN] Files that would be updated:"
    echo "  - $FEMDIR/VERSION"
    echo "  - $VERSION_F90"
    echo "  - $FEMDIR/shyfem-ui/pyproject.toml"
    echo "  - $FEMDIR/CHANGELOG.md"
    if ! $NO_TAG; then
        echo "  - Git tag: v$NEW_VERSION"
    fi
    exit 0
fi

# --- Update VERSION file ---

VERSION_FILE="$FEMDIR/VERSION"

# Prepend new version entry above the existing first line
{
    printf "version  %-10s %-14s VERS_%s\n" "$NEW_VERSION_UNDERSCORE" "$TODAY" "$NEW_VERSION_UNDERSCORE"
    echo ""
    printf "========================================================== %s - %s\n" "$TODAY" "$NEW_VERSION_UNDERSCORE"
    echo ""
    echo "! ./src/utils/shyutil/version.f90:"
    echo "! ${TODAY_FORTRAN}	auto	version ${NEW_VERSION}"
    echo ""
    echo "=========================================================="
    echo ""
    cat "$VERSION_FILE"
} > "$VERSION_FILE.tmp"
mv "$VERSION_FILE.tmp" "$VERSION_FILE"

echo "  Updated: VERSION"

# --- Update version.f90 ---

# Update version string
sed -i "s/character\*10, parameter :: version = '${CURRENT_VERSION}'/character*10, parameter :: version = '${NEW_VERSION}'/" "$VERSION_F90"

# Update commit date
CURRENT_COMMIT=$(grep "character\*10, parameter :: commit" "$VERSION_F90" | sed "s/.*'\([^']*\)'.*/\1/")
sed -i "s/character\*10, parameter :: commit  = '${CURRENT_COMMIT}'/character*10, parameter :: commit  = '${TODAY_ISO}'/" "$VERSION_F90"

# Update local commit
CURRENT_LCOMMIT=$(grep "character\*50, parameter :: lcommit" "$VERSION_F90" | sed "s/.*'\([^']*\)'.*/\1/")
sed -i "s|character\*50, parameter :: lcommit = '${CURRENT_LCOMMIT}'|character*50, parameter :: lcommit = '${TODAY_ISO}'|" "$VERSION_F90"

# Update copyright year range
sed -i "s/Copyright (C) The Shyfem Team 1985-[0-9]*/Copyright (C) The Shyfem Team 1985-${YEAR}/" "$VERSION_F90"

# Update LaTeX version macros
sed -i "s|\\\\newcommand{\\\\VERSION}{[^}]*}|\\\\newcommand{\\\\VERSION}{${NEW_VERSION}}|" "$VERSION_F90"
sed -i "s|\\\\newcommand{\\\\version}{[^}]*}|\\\\newcommand{\\\\version}{${NEW_VERSION_UNDERSCORE}}|" "$VERSION_F90"
sed -i "s|\\\\newcommand{\\\\COMMIT}{[^}]*}|\\\\newcommand{\\\\COMMIT}{${TODAY_ISO}}|" "$VERSION_F90"

echo "  Updated: version.f90"

# --- Update pyproject.toml ---

PYPROJECT="$FEMDIR/shyfem-ui/pyproject.toml"
if [ -f "$PYPROJECT" ]; then
    sed -i "s/^version = \"[^\"]*\"/version = \"${NEW_VERSION}\"/" "$PYPROJECT"
    echo "  Updated: pyproject.toml"
fi

# --- Update CHANGELOG.md ---

CHANGELOG="$FEMDIR/CHANGELOG.md"
if [ -f "$CHANGELOG" ]; then
    # Replace "[Unreleased] — YYYY-MM-DD" with the release header, and add new Unreleased
    sed -i "s/## \[Unreleased\].*/## [${NEW_VERSION}] — ${TODAY_ISO}/" "$CHANGELOG"

    # Insert a fresh Unreleased section at the top (after the header lines)
    sed -i "/^## \[${NEW_VERSION}\]/i\\
## [Unreleased]\\
\\
---\\
" "$CHANGELOG"

    echo "  Updated: CHANGELOG.md"
fi

# --- Git commit and tag ---

if ! $NO_COMMIT; then
    cd "$FEMDIR"
    git add VERSION src/utils/shyutil/version.f90 CHANGELOG.md README.md
    [ -f "$PYPROJECT" ] && git add shyfem-ui/pyproject.toml
    git commit -m "release: bump version to ${NEW_VERSION}

Update VERSION, version.f90, pyproject.toml, and CHANGELOG.md."
    echo "  Created commit"
fi

if ! $NO_TAG; then
    cd "$FEMDIR"
    git tag -a "v${NEW_VERSION}" -m "SHYFEM ${NEW_VERSION}"
    echo "  Created tag: v${NEW_VERSION}"
fi

echo ""
echo "Done! Version bumped to ${NEW_VERSION}"
echo ""
echo "Next steps:"
echo "  git log --oneline -1    # verify commit"
echo "  git tag -l              # verify tag"
echo "  git push && git push --tags  # push to remote"
