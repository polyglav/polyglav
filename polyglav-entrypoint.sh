#!/bin/sh
set -e

if [ -n "$POLYGLAV_PATH" ]; then
  exec polyglav serve --host "$POLYGLAV_HOST" --port "$POLYGLAV_PORT" --path "$POLYGLAV_PATH"
fi

exec polyglav serve --host "$POLYGLAV_HOST" --port "$POLYGLAV_PORT"
