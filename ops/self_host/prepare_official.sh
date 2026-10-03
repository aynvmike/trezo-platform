#!/bin/sh
# Fetch official configuration at an explicitly reviewed commit. Does NOT start
# containers, create secrets, install software, or change Trezo configuration.
set -eu
umask 077
if [ "$#" -ne 2 ]; then
  echo 'Usage: sh prepare_official.sh REVIEWED_40_CHARACTER_COMMIT NEW_DIRECTORY' >&2
  exit 2
fi
TREZO_UPSTREAM_COMMIT=$1
TREZO_STAGE_DIR=$2
case "$TREZO_UPSTREAM_COMMIT" in
  *[!0-9a-f]*|'') echo 'A lowercase full Git commit SHA is required.' >&2; exit 2 ;;
esac
if [ "${#TREZO_UPSTREAM_COMMIT}" -ne 40 ] || [ -e "$TREZO_STAGE_DIR" ]; then
  echo 'Commit must be 40 characters; destination must not exist.' >&2
  exit 2
fi
mkdir -m 700 -- "$TREZO_STAGE_DIR"
TREZO_STAGE_DIR=$(cd "$TREZO_STAGE_DIR" && pwd)
# Partial failure leaves a clearly incomplete staging directory, never a running
# service. Review .fetch.log privately; this script never prints remote errors.
touch "$TREZO_STAGE_DIR/PREPARATION_INCOMPLETE"
if ! (
  git init -q "$TREZO_STAGE_DIR/upstream"
  git -C "$TREZO_STAGE_DIR/upstream" config core.autocrlf false
  git -C "$TREZO_STAGE_DIR/upstream" remote add origin https://github.com/supabase/supabase.git
  git -C "$TREZO_STAGE_DIR/upstream" fetch --depth=1 origin "$TREZO_UPSTREAM_COMMIT"
  git -C "$TREZO_STAGE_DIR/upstream" checkout --detach -q FETCH_HEAD
) >"$TREZO_STAGE_DIR/.fetch.log" 2>&1; then
  echo 'Official source fetch failed; staging remains incomplete.' >&2
  exit 2
fi
TREZO_ACTUAL_COMMIT=$(git -C "$TREZO_STAGE_DIR/upstream" rev-parse HEAD)
if [ "$TREZO_ACTUAL_COMMIT" != "$TREZO_UPSTREAM_COMMIT" ] ||
   [ ! -f "$TREZO_STAGE_DIR/upstream/docker/docker-compose.yml" ] ||
   [ ! -f "$TREZO_STAGE_DIR/upstream/docker/.env.example" ]; then
  echo 'Commit or expected official Docker files could not be verified.' >&2
  exit 2
fi
mkdir "$TREZO_STAGE_DIR/stack"
cp -R "$TREZO_STAGE_DIR/upstream/docker/." "$TREZO_STAGE_DIR/stack/"
printf 'commit=%s\nsource=https://github.com/supabase/supabase.git\nstarted=false\n' \
  "$TREZO_ACTUAL_COMMIT" > "$TREZO_STAGE_DIR/preparation.txt"
rm "$TREZO_STAGE_DIR/PREPARATION_INCOMPLETE"
echo 'Official configuration prepared. No services started; secrets and private port bindings still require configuration.'
