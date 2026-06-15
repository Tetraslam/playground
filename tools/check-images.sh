#!/usr/bin/env bash
# check-images.sh — block oversized images from being committed.
#
# Small image assets are fine to commit. Large ones bloat the repo forever
# (git history keeps every byte). This rejects any staged image > MAX_MB.
# Generated/scratch images belong in scratch/ (gitignored), not in git.
#
# magick (ImageMagick) is available — if you genuinely need a big image in the
# repo, downscale it first, e.g.:
#   magick big.png -resize 50% -strip out.png
#
# Bypass (rare): ALLOW_BIG_IMAGES=1 git commit ...
set -euo pipefail

MAX_MB="${IMAGE_MAX_MB:-5}"
MAX_BYTES=$((MAX_MB * 1024 * 1024))

if [[ "${ALLOW_BIG_IMAGES:-0}" == "1" ]]; then
  echo "check-images: bypassed via ALLOW_BIG_IMAGES=1" >&2
  exit 0
fi

fail=0
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  case "${f,,}" in
    *.png|*.jpg|*.jpeg|*.gif|*.webp|*.bmp|*.tiff|*.tif|*.heic|*.avif)
      [[ -f "$f" ]] || continue
      size=$(stat -c%s "$f" 2>/dev/null || echo 0)
      if (( size > MAX_BYTES )); then
        mb=$(awk "BEGIN{printf \"%.1f\", $size/1048576}")
        echo "✗ $f is ${mb} MB (limit ${MAX_MB} MB)" >&2
        echo "    downscale it:  magick \"$f\" -resize 50% -strip \"$f\"" >&2
        echo "    or move generated images to scratch/ (gitignored)" >&2
        fail=1
      fi
      ;;
  esac
done < <(git diff --cached --name-only --diff-filter=ACM)

if [[ "$fail" == "1" ]]; then
  echo "" >&2
  echo "Large images don't belong in git history. Override (rare): ALLOW_BIG_IMAGES=1 git commit" >&2
  exit 1
fi
exit 0
