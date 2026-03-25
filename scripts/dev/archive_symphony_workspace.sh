#!/usr/bin/env bash
set -euo pipefail

workspace_path="${1:-$PWD}"
workspace_path="$(cd "$workspace_path" && pwd -P)"
issue_identifier="${2:-$(basename "$workspace_path")}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"

if ! git -C "$workspace_path" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Not a git workspace: $workspace_path" >&2
  exit 1
fi

origin_remote="$(git -C "$workspace_path" remote get-url origin 2>/dev/null || true)"
archive_root="${SYMPHONY_ARCHIVE_ROOT:-}"

if [ -z "$archive_root" ]; then
  if [ -n "$origin_remote" ] && [ -d "$origin_remote" ]; then
    archive_root="$origin_remote/artifacts/symphony-archive"
  else
    archive_root="$(dirname "$workspace_path")/_archives"
  fi
fi

archive_dir="$archive_root/$issue_identifier/$timestamp"
files_dir="$archive_dir/files"
mkdir -p "$files_dir"

ahead_patch="$archive_dir/commits.patch"
worktree_patch="$archive_dir/worktree.patch"
staged_patch="$archive_dir/staged.patch"
changed_list="$archive_dir/files.list"
deleted_list="$archive_dir/deleted-files.list"

branch_name="$(git -C "$workspace_path" branch --show-current 2>/dev/null || true)"
head_sha="$(git -C "$workspace_path" rev-parse HEAD 2>/dev/null || true)"
upstream_ref="$(git -C "$workspace_path" rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || true)"

{
  echo "issue_identifier=$issue_identifier"
  echo "workspace_path=$workspace_path"
  echo "archived_at_utc=$timestamp"
  echo "archive_dir=$archive_dir"
  echo "origin_remote=$origin_remote"
  echo "branch=$branch_name"
  echo "head=$head_sha"
  echo "upstream=$upstream_ref"
} > "$archive_dir/metadata.env"

git -C "$workspace_path" status --short --branch > "$archive_dir/status.txt" || true
git -C "$workspace_path" remote -v > "$archive_dir/remotes.txt" || true
git -C "$workspace_path" log --oneline --decorate -20 > "$archive_dir/log.txt" || true
git -C "$workspace_path" diff --stat > "$archive_dir/diff.stat.txt" || true
git -C "$workspace_path" diff --cached --stat > "$archive_dir/staged.stat.txt" || true
git -C "$workspace_path" diff --binary > "$worktree_patch" || true
git -C "$workspace_path" diff --cached --binary > "$staged_patch" || true

if [ -n "$upstream_ref" ]; then
  git -C "$workspace_path" format-patch --stdout "$upstream_ref..HEAD" > "$ahead_patch" || true
fi

{
  git -C "$workspace_path" diff --name-only HEAD || true
  git -C "$workspace_path" diff --cached --name-only || true
  git -C "$workspace_path" ls-files --others --exclude-standard || true
} | sed '/^$/d' | sort -u > "$changed_list"

{
  git -C "$workspace_path" diff --name-only --diff-filter=D HEAD || true
  git -C "$workspace_path" diff --cached --name-only --diff-filter=D || true
} | sed '/^$/d' | sort -u > "$deleted_list"

while IFS= read -r rel_path; do
  [ -n "$rel_path" ] || continue
  if [ ! -e "$workspace_path/$rel_path" ]; then
    continue
  fi
  mkdir -p "$files_dir/$(dirname "$rel_path")"
  cp -a "$workspace_path/$rel_path" "$files_dir/$rel_path"
done < "$changed_list"

if [ -s "$changed_list" ]; then
  tar -czf "$archive_dir/files.tar.gz" -C "$files_dir" . 2>/dev/null || true
fi

echo "$archive_dir"
