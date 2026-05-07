# Docker Integration Testing Manual

## Overview

The HEMM HA integration uses Docker containers for end-to-end integration testing.
The stack consists of:

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `hemm-ha-test` | `ghcr.io/home-assistant/home-assistant:stable` | 8123 | Home Assistant Core |
| `hemm-companion-test` | `ghcr.io/swifty99/hactl_companion:latest` | 9100 | hactl companion addon |

All tests are driven by **hactl** (Go CLI binary) that talks to HA's REST/WS API
and the companion's REST API.

## Prerequisites

- Docker Desktop (Windows/macOS) or Docker Engine (Linux)
- `uv` (Python package manager)
- Internet access (first run pulls images ~1.5GB)

## Quick Start

```bash
cd ha-hemm

# One-command: install hactl, start stack, run tests, tear down
make test-container

# Or for fast iteration (stack stays up between runs):
make docker-up              # Start stack (once)
make test-container-quick   # Run tests against running stack (fast)
make docker-down            # Tear down when done
```

## Stack Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Docker Network: ha-hemm_ha-net                             │
│                                                              │
│  ┌─────────────────────────┐  ┌──────────────────────────┐ │
│  │  hemm-ha-test           │  │  hemm-companion-test     │ │
│  │  HA Core (stable)       │  │  hactl-companion v0.2    │ │
│  │  Port: 8123             │  │  Port: 9100              │ │
│  │                         │  │                          │ │
│  │  Volumes:               │  │  Volumes:                │ │
│  │  - ha-config:/config    │  │  - ha-config:/config     │ │
│  │  - custom_components/   │  │                          │ │
│  │  - hemm-src (readonly)  │  │  Auth:                   │ │
│  │                         │  │  SUPERVISOR_TOKEN=       │ │
│  └─────────────────────────┘  │  integration-test-...    │ │
│                               └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
         ▲                               ▲
         │ REST/WS API                   │ REST API
         │                               │
    ┌────┴─────┐                    ┌────┴─────┐
    │  hactl   │ ← Go CLI binary    │  pytest  │ ← direct HTTP
    │  .bin/   │                    │  urllib   │
    └──────────┘                    └──────────┘
```

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make test-container` | Full cycle: start → test → teardown |
| `make test-container-quick` | Tests only (stack must be running) |
| `make docker-up` | Start stack, install hemm, wait for healthy |
| `make docker-down` | Stop stack, remove volumes + cached token |
| `make docker-reset` | Full reset (down + up) |
| `make docker-status` | Show container status |
| `make docker-logs` | HA container logs (last 20) |
| `make docker-logs-companion` | Companion logs |
| `make install-hactl` | Download latest hactl binary to `.bin/` |

## Manual Docker Workflow

### 1. Start the stack

```powershell
# Windows
docker compose -f docker-compose.test.yml up -d

# Wait for HA healthy
do { sleep 2; $s = docker inspect --format "{{.State.Health.Status}}" hemm-ha-test } while ($s -ne "healthy")

# Install hemm package (not on PyPI yet)
docker exec hemm-ha-test pip install /hemm-src

# Restart HA to pick up hemm
docker restart hemm-ha-test
# Wait healthy again...
```

### 2. Run tests

```powershell
$env:SKIP_DOCKER_COMPOSE = "1"
uv run pytest tests/integration/ -m container --tb=short -q
```

### 3. Iterate

After code changes to `custom_components/hemm/`:
- Changes are live (volume mount is `:ro` but HA reads at startup)
- Restart HA: `docker restart hemm-ha-test`
- Re-run tests: `make test-container-quick`

After changes to hemm core (`../hemm/src/`):
- Reinstall: `docker exec hemm-ha-test pip install /hemm-src`
- Restart: `docker restart hemm-ha-test`

### 4. Tear down

```powershell
docker compose -f docker-compose.test.yml down -v
Remove-Item .bin\.ha_test_token -ErrorAction SilentlyContinue
```

## hactl Usage

hactl requires a `.env` file in its `--dir` directory:

```env
HA_URL=http://localhost:8123
HA_TOKEN=<long-lived-access-token>
```

The test framework creates this automatically in a temp directory. For manual use:

```powershell
# After tests have run, the token is cached:
$token = Get-Content .bin\.ha_test_token
Set-Content .env "HA_URL=http://localhost:8123`nHA_TOKEN=$token"

# Now use hactl directly:
.bin\hactl.exe health
.bin\hactl.exe ent ls --domain sensor
.bin\hactl.exe config flow-start hemm
.bin\hactl.exe log --errors --unique
```

### Key hactl Commands for HEMM Testing

```bash
# Health & diagnostics
hactl health                     # HA connection check
hactl cc ls                      # List custom components
hactl log --errors --unique      # Error log summary

# Config flows
hactl config flow-start hemm     # Start HEMM config flow
hactl config flow-step <id> --data '{"name":"HEMM",...}'
hactl config options <entry_id>  # Start options flow
hactl config flow-step <id> --data '{"action":"add_device"}' --options

# Entities
hactl ent ls --pattern hemm      # List HEMM entities
hactl ent show sensor.hemm_*     # Entity state
hactl ent hist sensor.hemm_* --since 1h

# Templates (via companion)
hactl tpl eval '{{ states("sensor.hemm_plan") }}'

# Service calls
hactl svc call homeassistant.reload_config_entry --data '{"entry_id":"..."}'
```

## Companion Add-on

The companion provides filesystem access to `/config` that HA's REST API doesn't expose:

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/health` | Liveness (no auth) |
| `GET /v1/config/files` | List YAML files |
| `GET /v1/config/file?path=...` | Read config file |
| `PUT /v1/config/file?path=...` | Write config file |

Auth: `Authorization: Bearer <SUPERVISOR_TOKEN>` (set in docker-compose env)

### Known Issues

1. **Published image uses bashio shebang** — The `ghcr.io/swifty99/hactl_companion:latest`
   image has `/run.sh` with `#!/usr/bin/with-contenv bashio` which doesn't exist outside
   HA OS. Fix: use `command: ["python3", "-m", "companion"]` in docker-compose.
   
2. **IPv6 healthcheck** — Alpine resolves `localhost` to `::1` but companion binds
   `0.0.0.0` only. Fix: use `127.0.0.1` in healthcheck URLs.

3. **hemm pip requirement** — `manifest.json` requires `hemm==0.1.0` which isn't on
   PyPI. Fix: mount source and pip install before HA restart.

## Test Categories

| Marker | Tests | Description |
|--------|-------|-------------|
| `container` | 74+ | Full integration against Docker HA |
| `unit` | 45 | Fast mocked unit tests |
| `slow` | - | Long simulation tests |
| `pi` | - | Raspberry Pi hardware tests |

### Integration Test Files

| File | Tests | Focus |
|------|-------|-------|
| `test_container.py` | Config flow lifecycle | Setup, reload, add devices |
| `test_hactl_health.py` | Stack health | Version, logs, issues |
| `test_hactl_config.py` | Config entries & flows | CRUD, options, reload |
| `test_hactl_companion.py` | Companion API | Health, files, templates |
| `test_hactl_entities.py` | Entity management | Discovery, state, history |
| `test_hactl_manifest.py` | Manifest validation | Device config → manifest |
| `test_hactl_stress.py` | Stress testing | Rapid reloads, many devices |

## Troubleshooting

### "HA is already onboarded but no HA_TOKEN provided"
The container persisted onboarding state but the token was lost.
Fix: `make docker-reset` (removes volumes and starts fresh)

### "RequirementsNotFound: Requirements for hemm not found"
HA can't install hemm from PyPI.
Fix: `docker exec hemm-ha-test pip install /hemm-src && docker restart hemm-ha-test`

### "500 Internal Server Error" on config flow
hemm integration failed to load. Check: `docker logs hemm-ha-test | grep hemm`

### Companion "unhealthy"
Check healthcheck URL uses `127.0.0.1` not `localhost`. Alpine resolves to IPv6.

### pytest-socket blocks connections
Integration tests need real sockets. The conftest forces `pytest_socket.enable_socket()`
in `pytest_runtest_setup`. If still blocked, check for conflicting fixtures.

### Tests pass individually but fail in full suite
Log pollution from earlier tests (e.g., `test_tpl_eval_invalid` creates template errors
that `test_log_errors_unique` might catch). The log test filters by component now.
