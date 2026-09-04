#!/usr/bin/env bash
# Ping the deployed health endpoint to keep the Render free-tier deploy warm.
#
# A cold start can take a while, so retry a few times before giving up. Any
# 2xx/3xx means the service is awake (exit 0). If every attempt is unreachable
# (transport error -> 000, or a 4xx/5xx), the endpoint is genuinely down: exit
# non-zero so the broken deploy surfaces instead of a silently-green keepalive.
#
# Extracted from the workflow so the retry/exit-status contract is unit-testable
# (see tests/unit/test_keepalive.py). Tunables let tests run without real waits:
#   $1 or $KEEPALIVE_URL  target URL
#   KEEPALIVE_ATTEMPTS    number of tries (default 3)
#   KEEPALIVE_SLEEP       seconds between tries (default 20)
set -u

URL="${1:-${KEEPALIVE_URL:-https://untangle-073l.onrender.com/healthz}}"
attempts="${KEEPALIVE_ATTEMPTS:-3}"
sleep_secs="${KEEPALIVE_SLEEP:-20}"

echo "Pinging $URL"
code=000
attempt=1
while [ "$attempt" -le "$attempts" ]; do
  # curl's -w "%{http_code}" already prints 000 on a transport failure, so we
  # read that value directly (|| true keeps set -u happy on non-zero exit) and
  # only default when curl produced nothing — never appending a second 000.
  code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 90 "$URL" 2>/dev/null) || true
  code=${code:-000}
  echo "attempt $attempt: HTTP $code"
  case "$code" in 2*|3*) echo "awake"; exit 0;; esac
  [ "$attempt" -lt "$attempts" ] && sleep "$sleep_secs"
  attempt=$((attempt + 1))
done

echo "::error::keepalive could not reach $URL after $attempts attempts (last code $code)"
exit 1
