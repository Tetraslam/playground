#!/usr/bin/env bash
# spotify.sh — queue-safe Spotify control for agents.
#
# THE GOLDEN RULE (tetraslam usually has a queue going — DON'T clobber it):
#   - To play a song, ADD it to the queue (append) — never "start playback",
#     which replaces the current context and wipes the queue.
#   - Always READ the queue first so you know what you're touching.
#
# HOW IT WORKS
#   Everything goes through the Spotify Web API using the OAuth token that
#   spotify_player caches at ~/.cache/spotify-player/user_client_token.json
#   (auto-refreshed; carries every scope we need incl. user-modify-playback-
#   state + user-read-playback-state). We deliberately do NOT depend on the
#   spotify_player *daemon* being connected as a device — it's fragile and
#   often has no cached credentials ("try to connect to a client"), which used
#   to break `now`/`queue`/`search`. The Web API works whenever ANY device is
#   active (your phone, desktop app, another laptop), which is the common case.
#   `playerctl`/MPRIS is used only as a local fallback for `now`.
#
# COMMANDS
#   spotify.sh now                  # what's playing
#   spotify.sh queue                # show current queue
#   spotify.sh search "<query>"     # search tracks -> "id  name — artist"
#   spotify.sh add "<query>"        # SAFE: append best match to queue
#   spotify.sh add-id <track_id>    # SAFE: append a known track id
#   spotify.sh play|pause|next|prev # transport (does NOT change the queue)
#   spotify.sh vol <0-100>          # set volume
#   spotify.sh replace "<query>"    # DANGER: start fresh playback (wipes queue)
#   spotify.sh token-check          # verify the cached token is usable
#
# Requires: jq, curl. A valid spotify_player token cache. Premium account.
set -euo pipefail

TOKEN_FILE="${SPOTIFY_TOKEN_FILE:-$HOME/.cache/spotify-player/user_client_token.json}"
API="https://api.spotify.com/v1"

die() { echo "spotify: $*" >&2; exit 1; }

token() {
  # Nudge spotify_player to refresh the cached token if it can; harmless if the
  # daemon is down — the file is refreshed opportunistically and we validate it
  # below regardless.
  spotify_player get key playback >/dev/null 2>&1 || true
  [[ -f "$TOKEN_FILE" ]] || die "no token cache at $TOKEN_FILE — run spotify_player once to authenticate"
  local t; t="$(jq -r '.access_token // empty' "$TOKEN_FILE" 2>/dev/null)"
  [[ -n "$t" ]] || die "no access_token in $TOKEN_FILE"
  printf '%s' "$t"
}

# api METHOD PATH [curl args...] -> prints "<http_code>\n<body>".
# Use api_call() to split it; command substitution means we can't rely on a
# global, so the status code travels with the output.
api() {
  local method="$1" path="$2"; shift 2
  local out
  out="$(curl -s -w '\n%{http_code}' -X "$method" "$API$path" \
    -H "Authorization: Bearer $(token)" "$@")"
  local code="${out##*$'\n'}"
  local body="${out%$'\n'*}"
  printf '%s\n%s' "$code" "$body"
}

# api_call METHOD PATH [curl args...] -> sets API_HTTP and API_BODY.
API_HTTP=""; API_BODY=""
api_call() {
  local resp; resp="$(api "$@")"
  API_HTTP="${resp%%$'\n'*}"
  API_BODY="${resp#*$'\n'}"
}

# Resolve a query to the best track id. Echoes "name — artist" to stderr.
search_id() {
  local q="$1" id name
  api_call GET "/search?type=track&limit=5&q=$(jq -rn --arg s "$q" '$s|@uri')"
  [[ "$API_HTTP" == 2* ]] || die "search failed (HTTP $API_HTTP): ${API_BODY:0:200}"
  id="$(printf '%s' "$API_BODY" | jq -r '.tracks.items[0].id // empty')"
  name="$(printf '%s' "$API_BODY" | jq -r '.tracks.items[0] | "\(.name) — \(.artists[0].name)" // empty')"
  [[ -n "$id" ]] || die "no track found for '$q'"
  echo "  → $name" >&2
  printf '%s' "$id"
}

now_api() {
  api_call GET "/me/player"
  if [[ "$API_HTTP" == 200 ]] && [[ -n "$API_BODY" ]]; then
    printf '%s' "$API_BODY" | jq -r '
      "▶ \(.item.name) — \(.item.artists[0].name)" +
      "  [\(if .is_playing then "playing" else "paused" end) on \(.device.name)]"'
    return 0
  fi
  return 1
}

now_mpris() {
  command -v playerctl >/dev/null 2>&1 || return 1
  playerctl -p spotify status >/dev/null 2>&1 || return 1
  local s; s="$(playerctl -p spotify status 2>/dev/null)"
  playerctl -p spotify metadata --format "▶ {{title}} — {{artist}}  [${s,,} via MPRIS]" 2>/dev/null
}

show_now() {
  now_api || now_mpris || die "nothing playing (no active device and no MPRIS player)"
}

show_queue() {
  api_call GET "/me/player/queue"
  [[ "$API_HTTP" == 2* ]] || die "queue read failed (HTTP $API_HTTP) — is a device active?"
  printf '%s' "$API_BODY" | jq -r '
    "▶ now: \(.currently_playing.name // "?") — \(.currently_playing.artists[0].name // "?")",
    "  queue (\(.queue|length)):",
    (.queue[:10][] | "    \(.name) — \(.artists[0].name)")'
}

cmd="${1:-now}"; shift || true
case "$cmd" in
  now)   show_now ;;
  queue) show_queue ;;
  search)
    [[ $# -ge 1 ]] || die "usage: spotify.sh search \"<query>\""
    api_call GET "/search?type=track&limit=8&q=$(jq -rn --arg s "$*" '$s|@uri')"
    [[ "$API_HTTP" == 2* ]] || die "search failed (HTTP $API_HTTP)"
    printf '%s' "$API_BODY" | jq -r '.tracks.items[] | "\(.id)  \(.name) — \(.artists[0].name)"' ;;
  add)
    [[ $# -ge 1 ]] || die "usage: spotify.sh add \"<query>\""
    echo "queue before:" >&2; show_queue >&2 || true; echo >&2
    id="$(search_id "$*")"
    api_call POST "/me/player/queue?uri=spotify:track:$id"
    [[ "$API_HTTP" == 2* ]] || die "enqueue failed (HTTP $API_HTTP) — is a device active?"
    echo "✓ appended to queue (your existing queue is preserved)" ;;
  add-id)
    [[ $# -ge 1 ]] || die "usage: spotify.sh add-id <track_id>"
    api_call POST "/me/player/queue?uri=spotify:track:$1"
    [[ "$API_HTTP" == 2* ]] || die "enqueue failed (HTTP $API_HTTP)"
    echo "✓ appended track $1 to queue" ;;
  play)  api_call PUT  "/me/player/play";  echo "▶ play" ;;
  pause) api_call PUT  "/me/player/pause"; echo "⏸ pause" ;;
  next)  api_call POST "/me/player/next";  echo "⏭ next" ;;
  prev)  api_call POST "/me/player/previous"; echo "⏮ prev" ;;
  vol)
    [[ $# -ge 1 ]] || die "usage: spotify.sh vol <0-100>"
    api_call PUT "/me/player/volume?volume_percent=$1"; echo "🔊 volume $1" ;;
  replace)
    [[ $# -ge 1 ]] || die "usage: spotify.sh replace \"<query>\""
    echo "⚠ this REPLACES the current context and wipes the queue." >&2
    id="$(search_id "$*")"
    api_call PUT "/me/player/play" -H "Content-Type: application/json" \
      --data "{\"uris\":[\"spotify:track:$id\"]}"
    [[ "$API_HTTP" == 2* ]] || die "replace failed (HTTP $API_HTTP)"
    echo "▶ now playing (queue replaced)" ;;
  token-check)
    api_call GET "/me"
    [[ "$API_HTTP" == 200 ]] && echo "✓ token OK ($(printf '%s' "$API_BODY" | jq -r '.display_name // .id'))" \
      || die "token check failed (HTTP $API_HTTP)" ;;
  *) die "unknown command '$cmd' (try: now queue search add add-id play pause next prev vol replace token-check)" ;;
esac
