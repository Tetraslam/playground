#!/usr/bin/env bash
# spotify.sh — queue-safe Spotify control for agents.
#
# THE GOLDEN RULE (tetraslam usually has a queue going — DON'T clobber it):
#   - To play a song, ADD it to the queue (append) — never "start playback",
#     which replaces the current context and wipes the queue.
#   - Always READ the queue first so you know what you're touching.
#
# spotify_player's CLI can only *replace* context (playback start ...), so for
# safe enqueue we hit the Spotify Web API's POST /me/player/queue using the
# access token spotify_player already caches (auto-refreshed, has the
# user-modify-playback-state scope).
#
# COMMANDS
#   spotify.sh now                  # what's playing
#   spotify.sh queue                # show current queue
#   spotify.sh search "<query>"     # search tracks (JSON-ish summary)
#   spotify.sh add "<query>"        # SAFE: append best match to queue
#   spotify.sh add-id <track_id>    # SAFE: append a known track id
#   spotify.sh play|pause|next|prev # transport (does NOT change the queue)
#   spotify.sh vol <0-100>          # set volume
#   spotify.sh replace "<query>"    # DANGER: start fresh playback (wipes queue)
#
# Requires: spotify_player (authenticated), jq, curl. Premium account.
set -euo pipefail

TOKEN_FILE="$HOME/.cache/spotify-player/user_client_token.json"

token() {
  # spotify_player refreshes this file; a `get` call nudges a refresh if stale.
  spotify_player get key playback >/dev/null 2>&1 || true
  jq -r '.access_token' "$TOKEN_FILE" 2>/dev/null
}

api() { # method path
  curl -s -X "$1" "https://api.spotify.com/v1$2" -H "Authorization: Bearer $(token)"
}

search_id() { # query -> best track id + name on stderr
  local q="$1" json
  json="$(spotify_player search "$q" 2>/dev/null)"
  local id name
  id="$(printf '%s' "$json" | jq -r '.tracks[0].id // empty')"
  name="$(printf '%s' "$json" | jq -r '.tracks[0] | "\(.name) — \(.artists[0].name)" // empty')"
  [[ -n "$id" ]] || { echo "spotify: no track found for '$q'" >&2; return 1; }
  echo "$name" >&2
  printf '%s' "$id"
}

show_queue() {
  spotify_player get key queue 2>/dev/null | jq -r '
    "▶ now: \(.currently_playing.name) — \(.currently_playing.artists[0].name)",
    "  queue (\(.queue|length)):",
    (.queue[:10][] | "    \(.name) — \(.artists[0].name)")'
}

cmd="${1:-now}"; shift || true
case "$cmd" in
  now)
    spotify_player get key playback 2>/dev/null | jq -r '
      "▶ \(.item.name) — \(.item.artists[0].name)  [\(.is_playing|if . then "playing" else "paused" end)]"' ;;
  queue) show_queue ;;
  search)
    [[ $# -ge 1 ]] || { echo "usage: spotify.sh search \"<query>\"" >&2; exit 2; }
    spotify_player search "$*" 2>/dev/null | jq -r '.tracks[:8][] | "\(.id)  \(.name) — \(.artists[0].name)"' ;;
  add)
    [[ $# -ge 1 ]] || { echo "usage: spotify.sh add \"<query>\"" >&2; exit 2; }
    echo "queue before:" >&2; show_queue >&2; echo >&2
    id="$(search_id "$*")"
    api POST "/me/player/queue?uri=spotify:track:$id" >/dev/null
    echo "✓ appended to queue (your existing queue is preserved)" ;;
  add-id)
    [[ $# -ge 1 ]] || { echo "usage: spotify.sh add-id <track_id>" >&2; exit 2; }
    api POST "/me/player/queue?uri=spotify:track:$1" >/dev/null
    echo "✓ appended track $1 to queue" ;;
  play)  spotify_player playback play  >/dev/null 2>&1; echo "▶ play" ;;
  pause) spotify_player playback pause >/dev/null 2>&1; echo "⏸ pause" ;;
  next)  spotify_player playback next  >/dev/null 2>&1; echo "⏭ next" ;;
  prev)  spotify_player playback previous >/dev/null 2>&1; echo "⏮ prev" ;;
  vol)
    [[ $# -ge 1 ]] || { echo "usage: spotify.sh vol <0-100>" >&2; exit 2; }
    spotify_player playback volume "$1" >/dev/null 2>&1; echo "🔊 volume $1" ;;
  replace)
    [[ $# -ge 1 ]] || { echo "usage: spotify.sh replace \"<query>\"" >&2; exit 2; }
    echo "⚠ this REPLACES the current context and wipes the queue." >&2
    id="$(search_id "$*")"
    spotify_player playback start track --id "$id" >/dev/null 2>&1
    echo "▶ now playing (queue replaced)" ;;
  *) echo "spotify: unknown command '$cmd' (try: now queue search add add-id play pause next prev vol replace)" >&2; exit 2 ;;
esac
