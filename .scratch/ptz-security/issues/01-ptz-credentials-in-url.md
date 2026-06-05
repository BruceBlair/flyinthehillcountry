# 01 — PTZ credentials: hardcoded username in URL query string

Status: needs-triage

## Summary

The three `rest_command` PTZ entries in `ha-configuration.yaml` embed credentials in the URL query string:

```yaml
url: "https://192.168.100.131/api.cgi?cmd=PtzCtrl&user=flyhigh&password=!secret reolink_password"
```

**Partially mitigated (2026-06-05, commit `fd2cf1e2`):**
- Switched HTTP → HTTPS (traffic encrypted on LAN)
- Suppressed `rest_command` logger to `error` level (prevents URL from appearing in HA logs)

**Remaining exposure:**
- `user=flyhigh` is hardcoded in the config file (committed to git) rather than sourced from secrets
- The `!secret` tag inside a quoted URL string is ambiguous — standard YAML doesn't apply tags within string scalars; HA may preprocess it, but this is not guaranteed

## Constraints

Reolink's PTZ API authenticates via URL query parameters only — HTTP Basic auth headers are not accepted, so HA's `username:` / `password:` rest_command keys cannot be used.

## Options

1. **Create a dedicated camera API user** in Reolink UI with a minimal-permission account whose username exposure is low-risk. Rename from personal account (`flyhigh`) to something like `ha_ptz`. Move the new username to `!secret reolink_user`.

2. **Verify `!secret` interpolation** — confirm via HA logs or a test call that the password is actually being substituted. If not, the camera may be operating without auth on local LAN requests.

3. **Wait for HA Reolink integration** — the native HA Reolink integration handles PTZ without manual `rest_command` entries and manages credentials properly. If the camera is already in HA via the Reolink integration, these `rest_command` blocks may be removable.

## References

- `ha-configuration.yaml` lines 92–111
- Security review finding: 2026-06-05
