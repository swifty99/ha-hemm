# Issues to File: hactl & hactl-companion

Issues discovered during HEMM integration testing (2026-05-07).

---

## hactl Issues (https://github.com/swifty99/hactl/issues)

### Issue 1: `config entries` command missing

**Title:** Add `config entries` command to list config entries

**Description:**
hactl has no command to list config entries. The only way to get config entry IDs
(needed for `config options <entry_id>`) is to query the HA REST API directly:
`GET /api/config/config_entries/entry`.

**Current workaround:** Our test wrapper makes a direct REST API call using urllib.

**Requested:**
```
hactl config entries             # List all config entries
hactl config entries --domain hemm  # Filter by domain
```

Output should include: `entry_id`, `domain`, `title`, `state`, `version`.

**Priority:** High — needed for any config flow automation.

---

### Issue 2: `config flow-step --options` flag undocumented

**Title:** Document `--options` flag for `config flow-step`

**Description:**
When stepping through an options flow (started via `config options <entry_id>`),
the `config flow-step` command requires the `--options` flag. Without it, the step
is sent to the wrong API endpoint (`/api/config/config_entries/flow/` instead of
`/api/config/config_entries/options/flow/`).

This is not documented in `hactl config flow-step --help`.

**Requested:** Add `--options` to help text and/or auto-detect based on flow context.

---

### Issue 3: `cc ls` returns "no custom components" despite loaded integration

**Title:** `cc ls` doesn't detect mounted custom_components

**Description:**
After successfully loading a custom integration (hemm) via volume mount at
`/config/custom_components/hemm`, `hactl cc ls` reports "no custom components".

The integration IS loaded (config entry state = "loaded", entities created), but
the cc command doesn't detect it. This may be because `cc ls` relies on the
companion's filesystem listing rather than HA's component registry.

**Expected:** `cc ls` should show custom components that HA has loaded, regardless
of whether the companion can see them on disk.

**Workaround:** Verify via config entries (`domain == "hemm"` with `state == "loaded"`).

---

### Issue 4: IPv6 connection on Windows (hactl resolves localhost → ::1)

**Title:** hactl should prefer IPv4 when connecting to HA on localhost

**Description:**
On Windows, hactl sometimes resolves `localhost` to `::1` (IPv6). If HA is only
listening on `0.0.0.0` (IPv4), the connection fails or times out.

**Suggested fix:** 
- Use `127.0.0.1` in .env template/docs  
- Or: try IPv4 first, fall back to IPv6

**Workaround:** Use `HA_URL=http://127.0.0.1:8123` in .env file.

---

### Issue 5: `config flow-start` timeout on first load

**Title:** `config flow-start` times out when integration has import errors

**Description:**
When a custom integration fails to load (e.g., missing pip dependency), 
`config flow-start <domain>` hangs until timeout instead of returning an error.
HA returns 500 but hactl retries indefinitely.

After hactl retries 2x and gets 500, it should fail fast with a clear message:
"Integration failed to load. Check HA logs."

**Current behavior:** 30s timeout, then generic "Timeout" error.

---
### Issue 6: auto find an configure companioen

---

## hactl-companion Issues (https://github.com/swifty99/hactl_companion/issues)

### Issue 6: Published Docker image broken — bashio shebang in run.sh

**Title:** Docker image unusable outside HA OS — `/run.sh` has bashio shebang

**Description:**
The published image `ghcr.io/swifty99/hactl_companion:latest` has:
```bash
#!/usr/bin/with-contenv bashio
exec python3 -m companion
```

This shebang (`/usr/bin/with-contenv bashio`) only exists in HA OS/Supervised
environments. When running in plain Docker (for development/testing), the 
container exits immediately with:
```
exec /run.sh: no such file or directory
```

**Fix options:**
1. Change shebang to `#!/bin/bash` with fallback
2. Use `CMD ["python3", "-m", "companion"]` in Dockerfile (no run.sh needed)
3. Keep run.sh for HA OS, add docker-compose override for dev

**Workaround:** Add `command: ["python3", "-m", "companion"]` to docker-compose.

**Priority:** High — blocks all Docker-based development and CI testing.

---

### Issue 7: Companion binds 0.0.0.0 but Alpine resolves localhost to ::1

**Title:** Health endpoint unreachable via `localhost` in Alpine containers

**Description:**
The companion server binds to `0.0.0.0:9100` (IPv4 only). Inside Alpine
containers, `localhost` resolves to `::1` first (IPv6). The Docker healthcheck
using `wget http://localhost:9100/v1/health` fails because wget connects to
`[::1]:9100` which has no listener.

**Fix options:**
1. Bind to `::` (dual-stack) instead of `0.0.0.0`
2. Document that healthchecks should use `127.0.0.1`
3. Change run.sh/server.py to bind dual-stack by default

**Workaround:** Use `http://127.0.0.1:9100` in healthcheck commands.

---

### Issue 8: `resolve=true` returns unexpected content for configuration.yaml

**Title:** `/v1/config/file?resolve=true` returns "null\n...\n" for valid YAML

**Description:**
When fetching `configuration.yaml` with `resolve=true`, the companion returns:
```json
{"content": "null\n...\n"}
```

The actual file content is:
```yaml
homeassistant:
  name: "HEMM Test Home"
  unit_system: metric
default_config:
```

Without `resolve=true`, the endpoint returns the correct raw content.
The YAML resolver seems to fail silently on certain multi-document or 
HA-specific YAML structures.

**Expected:** Either return resolved content or fall back to raw on parse failure.

---

### Issue 9: No logging output to stdout/stderr

**Title:** Companion produces no log output (silent startup)

**Description:**
When running `python3 -m companion`, the server starts successfully but produces
zero log output. No startup banner, no request logging, no error messages.

This makes debugging extremely difficult. At minimum:
- Startup message: "hactl-companion v0.2.0 listening on 0.0.0.0:9100"
- Request logging (at least errors/4xx/5xx)
- Configurable log level via env var (e.g., `LOG_LEVEL=debug`)

---

### Issue 10: No `--version` / `--help` CLI flags

**Title:** Add `--version` and `--help` CLI arguments

**Description:**
`python3 -m companion --version` starts the server instead of printing version.
`python3 -m companion --help` also starts the server.

Requested: standard CLI flags for version and help.

---

## Summary Table

| # | Repo | Severity | Title |
|---|------|----------|-------|
| 1 | hactl | High | Add `config entries` command |
| 2 | hactl | Medium | Document `--options` flag |
| 3 | hactl | Low | `cc ls` misses mounted components |
| 4 | hactl | Low | IPv6 localhost resolution |
| 5 | hactl | Medium | Fail fast on 500 instead of timeout |
| 6 | companion | **High** | Broken Docker image (bashio shebang) |
| 7 | companion | Medium | IPv6 healthcheck failure |
| 8 | companion | Low | resolve=true YAML parsing |
| 9 | companion | Medium | No logging output |
| 10 | companion | Low | No --version/--help flags |
