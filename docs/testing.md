# Testing Guide — HEMM Integration Tests

## Architecture

HEMM integration tests use a layered approach:

1. **Unit tests** (`pytest -m unit`): In-process HA tests using `pytest-homeassistant-custom-component`
2. **Container tests** (`pytest -m container`): Real HA Docker container + companion addon, driven by the real `hactl` binary
3. **Pi tests** (`pytest -m pi`): Hardware validation on Raspberry Pi

## Container Test Stack

```
┌─────────────────────────────────────────┐
│  Test runner (pytest on host/WSL)       │
│  └─ hactl binary (subprocess calls)    │
│     └─ points at temp dir with .env    │
├─────────────────────────────────────────┤
│  Docker Compose                         │
│  ├─ homeassistant (HA container)        │
│  │   └─ /config/custom_components/hemm  │
│  └─ companion (hactl_companion addon)   │
│      └─ shared /config volume           │
└─────────────────────────────────────────┘
```

### Components

- **hactl binary**: Real Go binary from [github.com/swifty99/hactl](https://github.com/swifty99/hactl). Downloaded automatically on first run.
- **Python HactlClient** (`hactl_client.py`): Retained **only** for container onboarding (WebSocket long-lived token creation). All test assertions use the hactl binary.
- **Companion addon** (`ghcr.io/swifty99/hactl_companion`): Provides YAML file access for templates, scripts, and automations.

### Test Flow

1. `docker compose up -d --wait` starts HA + companion
2. Python `HactlClient` performs headless onboarding → gets long-lived token
3. Token written to temp dir `.env` with `HA_URL`
4. `Hactl` subprocess wrapper uses `--dir` flag pointing at temp dir
5. Tests call hactl commands, parse JSON output, assert

## Running Locally

### Prerequisites

- Docker (via WSL2 on Windows, or native Linux/macOS)
- Python 3.12+ with `uv`
- Internet access (for hactl binary download on first run)

### Quick Start

```bash
cd ha-hemm

# Install hactl binary (downloads to .bin/)
make install-hactl

# Run container tests
make test-container
```

### Manual Container Management

```bash
# Start containers manually (useful for debugging)
docker compose -f docker-compose.test.yml up -d --wait

# Skip auto docker-compose in tests (containers already running)
SKIP_DOCKER_COMPOSE=1 make test-container

# Run specific test file
SKIP_DOCKER_COMPOSE=1 uv run pytest tests/integration/test_hactl_health.py -m container -v

# Stop containers
docker compose -f docker-compose.test.yml down -v --remove-orphans
```

## WSL2 Gotchas (Windows Development)

### Docker Context

WSL2 uses Docker Engine inside the Linux VM. Ensure you're using the WSL2 Docker context, **not** Docker Desktop's Windows context:

```bash
docker context ls
# Should show "default" pointing to unix:///var/run/docker.sock
```

If using Docker Desktop with WSL2 integration enabled, Docker commands work from both Windows and WSL. However, **run tests from WSL** for consistent path handling.

### Port Forwarding

Docker containers inside WSL2 expose ports to `localhost` on Windows automatically. `http://localhost:8123` works from both Windows and WSL.

**Exception**: If running Docker inside a separate WSL distro than your dev environment, you may need `host.docker.internal` or the WSL IP:

```bash
# Find WSL IP (run from WSL)
ip addr show eth0 | grep "inet "
```

### DNS Resolution

WSL2 sometimes has DNS issues inside containers. If `curl` from inside the container fails:

```bash
# Check /etc/resolv.conf in WSL
cat /etc/resolv.conf

# Fix: add to docker-compose.test.yml if needed
# services:
#   homeassistant:
#     dns:
#       - 8.8.8.8
#       - 1.1.1.1
```

### Volume Mounts

Docker volumes (named volumes like `ha-config`) work identically in WSL2. **Bind mounts** use Linux paths:

```yaml
# CORRECT (WSL path)
volumes:
  - ./custom_components/hemm:/config/custom_components/hemm:ro

# WRONG (Windows path from WSL)
# - /mnt/c/repos/hemmdev/ha-hemm/custom_components/hemm:/config/...
```

Always run `make test-container` from within the WSL filesystem (`~/repos/...`), not from `/mnt/c/...` which is slower and can cause permission issues.

### ProactorEventLoop (Python on Windows)

If running Python tests directly on Windows (not WSL), the `ProactorEventLoop` used by HA requires:
- `aiohttp.ThreadedResolver()` instead of `aiodns`
- Real sockets enabled (pytest-socket disabled)

These are already handled in `conftest.py`.

### File Permissions

Files created by Docker containers may have root ownership in WSL. If you see permission errors:

```bash
sudo chown -R $(whoami):$(whoami) tests/integration/config/.storage/
```

## hactl Binary Management

### Automatic Download

The `hactl_binary` pytest fixture automatically downloads the latest release if not found:

1. Checks `.bin/hactl` (project-local)
2. Checks PATH (system-wide)
3. Downloads from `https://github.com/swifty99/hactl/releases/latest/download/`

### Manual Installation

```bash
# Via Makefile (recommended)
make install-hactl

# Via go install
go install github.com/swifty99/hactl/cmd/hactl@latest

# Manual download (Linux amd64)
curl -sL https://github.com/swifty99/hactl/releases/latest/download/hactl_linux_amd64 -o .bin/hactl
chmod +x .bin/hactl
```

### Version Updates

hactl is always pinned to `latest` release. The download URL uses GitHub's `/releases/latest/download/` redirect which always resolves to the newest release.

To update manually: delete `.bin/hactl` and re-run `make install-hactl`.

## Companion Addon

The companion addon provides YAML file access that HA's REST/WS API doesn't offer:
- Read/write `configuration.yaml`, `scripts.yaml`, `automations.yaml`
- Template sensor CRUD
- `!include` resolution

### If Companion Tests Fail

Companion tests are isolated in `test_hactl_companion.py`. If the companion image is broken or missing features:

1. Tests are **skipped** (not failed) — controlled by `_companion_available()` check
2. File an issue at: https://github.com/swifty99/hactl/issues
3. Include: what endpoint failed, expected vs actual behavior, companion version

### Companion Auth

In tests, the companion uses a static token: `integration-test-token-12345` (set via `SUPERVISOR_TOKEN` env in docker-compose).

## Phase 8: Pi Testing with hactl

For Pi hardware validation (Phase 8), hactl on this development machine connects to the HA Pi instance:

```bash
mkdir -p ~/ha/pi
cat > ~/ha/pi/.env << 'EOF'
HA_URL=http://<pi-ip>:8123
HA_TOKEN=<pi-long-lived-token>
EOF

# Test connectivity
hactl --dir ~/ha/pi health

# Run Pi-specific tests
HA_BASE_URL=http://<pi-ip>:8123 HA_TOKEN=<token> SKIP_DOCKER_COMPOSE=1 make test-pi
```

The same hactl binary works — it's just pointed at a different HA instance via `--dir`.

## CI Configuration

GitHub Actions uses:
- Linux runner with Docker
- hactl binary downloaded from releases (Linux amd64)
- HA version matrix (3 stable versions × Python 3.12/3.13)
- Companion image pulled from GHCR

```yaml
# Relevant CI steps:
- name: Install hactl
  run: make install-hactl

- name: Start test containers
  run: docker compose -f docker-compose.test.yml up -d --wait

- name: Run container tests
  run: uv run pytest -m container --timeout=300
```

## Troubleshooting

### "hactl failed (rc=1): connection refused"

Container not ready yet. Increase `start_period` in healthcheck or wait longer in fixture.

### "Companion not available — file issue"

Companion image not pulled or not healthy. Check:
```bash
docker logs hemm-companion-test
docker compose -f docker-compose.test.yml ps
```

### "Timeout after 30s"

hactl command took too long. Possible causes:
- HA container overloaded
- Large response being truncated at token cap
- Network issue between host and container

### "No hemm entry found"

Integration setup failed silently. Check:
```bash
hactl --dir <dir> log --errors
hactl --dir <dir> cc ls
```
