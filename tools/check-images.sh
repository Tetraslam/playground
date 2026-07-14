#!/usr/bin/env bash
# check-images.sh — block oversized media from being committed.
#
# Small assets are fine to commit. Large ones bloat the repo forever
# (git history keeps every byte). Limits by type:
#   images  > 5 MB  (IMAGE_MAX_MB)  — downscale: magick big.png -resize 50% -strip out.png
#   videos  > 20 MB (VIDEO_MAX_MB)  — prefer animated .webp loops (counted as images);
#                                     re-encode: ffmpeg -i in.mp4 -crf 28 out.mp4
#   .blend  > 5 MB  (BLEND_MAX_MB)  — .blend is build output; commit the script that
#                                     makes it, not the file (see AGENTS.md § Blender)
#
# Raw render output belongs in the toy's renders/ (gitignored); curated frames
# and loops go in examples/.
#
# Bypass (rare): ALLOW_BIG_IMAGES=1 git commit ...
set -euo pipefail

MAX_MB="${IMAGE_MAX_MB:-5}"
MAX_BYTES=$((MAX_MB * 1024 * 1024))
VIDEO_MAX_MB="${VIDEO_MAX_MB:-20}"
VIDEO_MAX_BYTES=$((VIDEO_MAX_MB * 1024 * 1024))
BLEND_MAX_MB="${BLEND_MAX_MB:-5}"
BLEND_MAX_BYTES=$((BLEND_MAX_MB * 1024 * 1024))

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
        echo "✗ $f is ${mb} MB (image limit ${MAX_MB} MB)" >&2
        echo "    downscale it:  magick \"$f\" -resize 50% -strip \"$f\"" >&2
        echo "    or move generated images to scratch/ (gitignored)" >&2
        fail=1
      fi
      ;;
    *.mp4|*.webm|*.mkv|*.mov|*.avi)
      [[ -f "$f" ]] || continue
      size=$(stat -c%s "$f" 2>/dev/null || echo 0)
      if (( size > VIDEO_MAX_BYTES )); then
        mb=$(awk "BEGIN{printf \"%.1f\", $size/1048576}")
        echo "✗ $f is ${mb} MB (video limit ${VIDEO_MAX_MB} MB)" >&2
        echo "    re-encode smaller:  ffmpeg -i \"$f\" -crf 28 -preset slow out.mp4" >&2
        echo "    or commit an animated .webp loop instead (tools/blender.sh encode)" >&2
        fail=1
      fi
      ;;
    *.blend)
      [[ -f "$f" ]] || continue
      size=$(stat -c%s "$f" 2>/dev/null || echo 0)
      if (( size > BLEND_MAX_BYTES )); then
        mb=$(awk "BEGIN{printf \"%.1f\", $size/1048576}")
        echo "✗ $f is ${mb} MB (.blend limit ${BLEND_MAX_MB} MB)" >&2
        echo "    .blend files are build output — commit the script that generates it" >&2
        echo "    (see AGENTS.md § Blender toys)" >&2
        fail=1
      fi
      ;;
  esac
done < <(git diff --cached --name-only --diff-filter=ACM)

if [[ "$fail" == "1" ]]; then
  echo "" >&2
  echo "Large media doesn't belong in git history. Override (rare): ALLOW_BIG_IMAGES=1 git commit" >&2
  exit 1
fi
exit 0
