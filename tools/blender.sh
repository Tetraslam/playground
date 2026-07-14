#!/usr/bin/env bash
# blender.sh — the playground's Blender wrapper. Headless by default.
#
#   tools/blender.sh new <file.blend> [--empty]
#       Create a .blend (default startup scene; --empty strips all objects).
#       The MCP *_for_cli tools error on nonexistent files — make one first.
#
#   tools/blender.sh run <script.py> [file.blend] [-- args...]
#       Run a Python script in background Blender, optionally opening a blend
#       first. Args after -- land in sys.argv after the '--'.
#
#   tools/blender.sh render <file.blend> <out.png> [--final|--cycles] [--res WxH] [--samples N]
#       Render a still. Default: EEVEE 960x540 (~2s, the iteration loop).
#       --cycles: Cycles/OPTIX @ 64 samples. --final: Cycles/OPTIX 1920x1080
#       @ 256 samples + denoise (the examples/ preset).
#
#   tools/blender.sh snap <file.blend> <out.png>
#       Fast 480x270 EEVEE thumbnail — for agents to *look* at their work.
#
#   tools/blender.sh turntable <file.blend> <outbase> [--frames N] [--fps N] [--final] [--res WxH]
#       Orbit a camera 360° around the scene bbox, render frames, then encode
#       <outbase>.webp + <outbase>.mp4 + <outbase>_strip.png. Frames land in
#       <outbase>_frames/. Default 96 frames @ 24fps (a 4s seamless loop).
#
#   tools/blender.sh encode <frames_dir> <outbase> [--fps N]
#       Frame sequence -> .webp (committable, plays in GitHub READMEs) +
#       .mp4 (local viewing) + _strip.png (6-frame filmstrip for review).
#
#   tools/blender.sh gui [file.blend]
#       Launch the Blender GUI (detached). With the MCP addon's auto-start
#       enabled, the interactive MCP tools connect to it.
#
# Conventions: raw output goes in the toy's renders/ (gitignored); curated
# stills/loops/strips go in examples/ (committed). See AGENTS.md § Blender.
set -euo pipefail

BLENDER_BIN="${BLENDER_BIN:-blender}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPS="$HERE/_blender_ops.py"

die() { echo "blender.sh: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || die "missing dependency: $1"; }

blender_ops() { # blender_ops <blend|-> [BSH_VAR=val ...]
  local blend="$1"; shift
  local args=(--background)
  [[ "$blend" != "-" ]] && args+=("$blend")
  env "$@" "$BLENDER_BIN" "${args[@]}" --python "$OPS" 2>&1 | grep -Ev '^(Blender quit|$)' || true
}

cmd="${1:-}"; shift || die "usage: tools/blender.sh <new|run|render|snap|turntable|encode|gui> ..."

case "$cmd" in
  new)
    out="${1:?usage: new <file.blend> [--empty]}"; shift || true
    empty=0; [[ "${1:-}" == "--empty" ]] && empty=1
    blender_ops - BSH_CMD=new BSH_OUT="$out" BSH_EMPTY="$empty"
    ;;

  run)
    script="${1:?usage: run <script.py> [file.blend] [-- args...]}"; shift
    blend=""
    if [[ $# -gt 0 && "${1:-}" != "--" ]]; then blend="$1"; shift; fi
    [[ "${1:-}" == "--" ]] && shift
    args=(--background)
    [[ -n "$blend" ]] && args+=("$blend")
    "$BLENDER_BIN" "${args[@]}" --python "$script" -- "$@"
    ;;

  render|snap)
    blend="${1:?usage: $cmd <file.blend> <out.png> [--final|--cycles] [--res WxH] [--samples N]}"
    out="${2:?missing output path}"; shift 2
    engine=eevee res=960x540 samples=64
    [[ "$cmd" == "snap" ]] && res=480x270
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --final)   engine=cycles res=1920x1080 samples=256 ;;
        --cycles)  engine=cycles ;;
        --res)     res="$2"; shift ;;
        --samples) samples="$2"; shift ;;
        *) die "unknown flag: $1" ;;
      esac; shift
    done
    mkdir -p "$(dirname "$out")"
    blender_ops "$blend" BSH_CMD=render BSH_OUT="$out" BSH_ENGINE="$engine" BSH_RES="$res" BSH_SAMPLES="$samples"
    ;;

  turntable)
    blend="${1:?usage: turntable <file.blend> <outbase> [--frames N] [--fps N] [--final] [--res WxH]}"
    outbase="${2:?missing outbase}"; shift 2
    engine=eevee res=960x540 samples=64 frames=96 fps=24
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --final)  engine=cycles samples=128 ;;   # 128 is plenty at motion; 256 is for stills
        --frames) frames="$2"; shift ;;
        --fps)    fps="$2"; shift ;;
        --res)    res="$2"; shift ;;
        *) die "unknown flag: $1" ;;
      esac; shift
    done
    frames_dir="${outbase}_frames"
    mkdir -p "$frames_dir"
    blender_ops "$blend" BSH_CMD=turntable BSH_OUT="$frames_dir" BSH_ENGINE="$engine" BSH_RES="$res" BSH_SAMPLES="$samples" BSH_FRAMES="$frames"
    "$0" encode "$frames_dir" "$outbase" --fps "$fps"
    ;;

  encode)
    need ffmpeg; need magick
    frames_dir="${1:?usage: encode <frames_dir> <outbase> [--fps N]}"
    outbase="${2:?missing outbase}"; shift 2
    fps=24
    [[ "${1:-}" == "--fps" ]] && fps="$2"
    shopt -s nullglob
    frames=("$frames_dir"/*.png)
    (( ${#frames[@]} > 0 )) || die "no PNG frames in $frames_dir"
    mkdir -p "$(dirname "$outbase")"
    # webp: the committable loop (GitHub READMEs animate it; gif is 5-10x bigger)
    ffmpeg -y -loglevel error -framerate "$fps" -pattern_type glob -i "$frames_dir/*.png" \
      -c:v libwebp_anim -loop 0 -q:v 70 "${outbase}.webp"
    # mp4: local viewing (h264 wants even dims -> crop filter)
    ffmpeg -y -loglevel error -framerate "$fps" -pattern_type glob -i "$frames_dir/*.png" \
      -vf "crop=trunc(iw/2)*2:trunc(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -crf 23 -movflags +faststart \
      "${outbase}.mp4"
    # filmstrip: 6 evenly spaced frames — how an agent reviews motion
    n=${#frames[@]}
    picks=()
    for i in 0 1 2 3 4 5; do picks+=("${frames[$(( i * (n - 1) / 5 ))]}"); done
    magick montage "${picks[@]}" -tile 6x1 -geometry +2+2 -background '#111111' "${outbase}_strip.png"
    echo "encode -> ${outbase}.webp $(du -h "${outbase}.webp" | cut -f1), ${outbase}.mp4, ${outbase}_strip.png"
    ;;

  gui)
    blend="${1:-}"
    args=()
    [[ -n "$blend" ]] && args+=("$blend")
    nohup "$BLENDER_BIN" "${args[@]}" >/dev/null 2>&1 &
    disown
    echo "gui: blender launching (pid $!). MCP interactive tools connect once the addon server is up (enable auto-start in the addon prefs)."
    ;;

  *)
    die "unknown command: $cmd (new|run|render|snap|turntable|encode|gui)"
    ;;
esac
