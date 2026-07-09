#!/bin/bash
# Restarts ecowitt-proxy if Docker's healthcheck has marked it unhealthy.
# Docker's `unless-stopped` restart policy only fires on process exit, and
# the proxy's old failure mode was a hang with no exit — hence this watchdog.
status=$(docker inspect --format='{{.State.Health.Status}}' ecowitt-proxy 2>/dev/null)
if [ "$status" = "unhealthy" ]; then
  echo "$(date -u +%FT%TZ) ecowitt-proxy unhealthy — restarting"
  docker restart ecowitt-proxy
fi
