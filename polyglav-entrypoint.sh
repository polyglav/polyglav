#!/bin/sh
set -e

set -- serve --host "$POLYGLAV_HOST" --port "$POLYGLAV_PORT"

if [ -n "$POLYGLAV_TOKEN" ]; then
  set -- "$@" --token "$POLYGLAV_TOKEN"
fi

if [ -n "$POLYGLAV_ALLOW_UNAUTHENTICATED" ]; then
  set -- "$@" --allow-unauthenticated
fi

if [ -n "$POLYGLAV_PATH" ]; then
  set -- "$@" --path "$POLYGLAV_PATH"
fi

exec polyglav "$@"
