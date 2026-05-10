# ha-hemm — Testing Guide

This document explains how ha-hemm is tested, what the tests actually verify, how you can run them yourself, and where we know the coverage is thin. It is written for someone new to the project — or to software testing in general — so it tries to explain the *why* at each step, not just the *what*.

Testing a Home Assistant custom integration is harder than testing a pure library. The integration's job is to translate between HA's runtime (config flows, entities, coordinators) and the HEMM core library — so testing against mocks would only confirm that the code calls the mock correctly, not that it actually works inside a real HA instance. This is why ha-hemm's test suite goes to some lengths to run against a real, live HA instance for the tests that matter most.

---

## The Three Layers

ha-hemm's tests are organized into three layers, each with a different scope and a different cost.

**Unit tests** are the fastest and cheapest. They cover config flows, device flows, coordinator lifecycle, diagnostics, sensor creation, and identification stubs — all running in-process against a simulated HA runtime provided by `pytest-homeassistant-custom-component`. No Docker, no network, no hactl. They run in under 10 seconds and serve as a quick sanity check during development.

**Container tests** are the main event. They start a real Home Assistant instance (and a companion addon) in Docker containers, run hactl commands against them, and check the output. These tests are slower (roughly two minutes once Docker images are cached, longer on first pull), but they are the ones that tell us whether the integration actually works in a real HA installation. Every interaction with HA goes through the real [hactl](https://github.com/swifty99/hactl) CLI binary — the same tool a human would use — rather than a purpose-built Python test client.

**Pi tests** cover hardware validation on a Raspberry Pi running HA OS. They verify that HEMM performs acceptably under realistic resource constraints (ARM CPU, limited RAM, SD card I/O). These are not automated in CI; they run manually against a physical Pi instance using hactl pointed at the Pi's IP. This layer is planned for Phase 8.

Each layer has its own pytest marker, and each layer is enforced independently in CI. You can think of the layers as a pyramid: many small unit tests at the base, a broad set of container tests in the middle, and a focused hardware validation at the top.

---

## Layer 1: Unit Tests

Unit tests live in `tests/` (top-level, not under `integration/`). They use `pytest-homeassistant-custom-component` to spin up a minimal in-process HA runtime — no Docker, no real network. To run them:

```bash
# Via Makefile (Linux/macOS/WSL)
make test

# Direct (Windows or any platform)
uv run pytest
```

This takes roughly 9 seconds and requires nothing beyond Python and the dev dependencies.

What the unit tests cover:

| Test file | What it checks |
|---|---|
| `test_smoke.py` | Domain constant is `"hemm"`, manifest.json valid, constants consistency |
| `test_config_flow.py` | Config flow creation with defaults, duplicate detection, solver backend selection |
| `test_device_flow.py` | All 7 device types (Room, ThermostatLoad, HeatPump, WaterHeater, Battery, PVForecast, EVCharger) in beginner & pro tiers, `safe_default` validation, schema builder correctness |
| `test_options_flow.py` | Settings management and device addition via options flows |
| `test_init.py` | Integration setup, coordinator creation, platform forwarding, unload entry |
| `test_sensor.py` | Sensor entity creation (empty result without sub-entries) |
| `test_diagnostics.py` | Diagnostics structure, `tested_ha_version` presence |
| `test_identification.py` | All 7 device identifier stubs return `None`, registry completeness |
| `test_markers.py` | Test marker demonstration (`unit`, `container`, `pi`, `slow`) |

45 unit tests exist across these files. The default `uv run pytest` invocation runs only unit tests — container, pi, and slow tests are excluded by the `addopts` setting in `pyproject.toml`.

### Windows-specific considerations

On Windows, `pytest-homeassistant-custom-component` interacts with `pytest-socket` (which blocks network access by default). The integration's `conftest.py` handles this automatically:

- `pytest_configure` enables sockets on Windows (ProactorEventLoop is incompatible with socket blocking)
- The `auto_enable_custom_integrations` fixture is set to allow loading the hemm integration

No manual configuration is needed — `uv run pytest` works on Windows, Linux, and macOS.

---

## Layer 2: Container Tests

Container tests live in `tests/integration/` and carry the `@pytest.mark.container` marker. The marker is what keeps them out of a plain `uv run pytest` invocation — you have to opt in explicitly. This is a deliberate design choice: running container tests requires Docker, and many development workflows (editing, linting, quick feedback loops) should not be blocked on Docker availability.

To run the full container test suite:

```bash
# Via Makefile — full cycle: install hactl, start stack, test, teardown
make test-container

# Or for fast iteration (start stack once, run tests repeatedly)
make docker-up                    # Start stack (once)
make test-container-quick         # Run tests (fast, stack stays up)
make docker-down                  # Tear down when done

# Direct commands (Windows — no make required)
docker compose -f docker-compose.test.yml up -d
# ... wait for healthy, install hemm, restart HA (see below) ...
$env:SKIP_DOCKER_COMPOSE="1"
uv run pytest tests/integration/ -m container --tb=short -v -o "addopts="
```

The first run takes roughly 3–4 minutes because Docker has to pull the Home Assistant image (~1.5 GB) and the companion image. Subsequent runs take about 2 minutes because images are cached locally.

### How the container stack works

The test stack is defined in `docker-compose.test.yml` and consists of two containers on a shared Docker network:

```
┌─────────────────────────────────────────────────────────────┐
│  Docker Network: ha-hemm_ha-net                             │
│                                                             │
│  ┌───────────────────────┐  ┌─────────────────────────────┐│
│  │ hemm-ha-test          │  │ hemm-companion-test         ││
│  │ HA Core (stable)      │  │ hactl-companion             ││
│  │ Port: 8123            │  │ Port: 9100                  ││
│  │                       │  │                             ││
│  │ Volumes:              │  │ Volumes:                    ││
│  │ - ha-config:/config   │  │ - ha-config:/config (shared)││
│  │ - custom_components/  │  │                             ││
│  │   hemm (bind, ro)     │  │ Auth:                       ││
│  │ - ../hemm (bind, ro)  │  │ SUPERVISOR_TOKEN=           ││
│  │ - configuration.yaml  │  │ integration-test-token-...  ││
│  └───────────────────────┘  └─────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
         ▲                               ▲
         │ REST/WS API                   │ REST API
         │                               │
    ┌────┴──────────────────────────┐    │
    │  Test runner (pytest on host) │    │
    │  └─ hactl binary (subprocess)├────┘
    │     └─ --dir <tmpdir>/.env   │
    └──────────────────────────────┘
```

**Home Assistant container** (`hemm-ha-test`): Runs the real HA Core image. The hemm custom component is bind-mounted read-only at `/config/custom_components/hemm`. The hemm core library source is mounted at `/hemm-src` and pip-installed into the container (hemm is not yet on PyPI, so HA can't install it from `manifest.json` requirements automatically). A `configuration.yaml` fixture is also bind-mounted.

**Companion container** (`hemm-companion-test`): Runs the [hactl-companion](https://github.com/swifty99/hactl_companion) addon, which provides YAML filesystem access that HA's REST/WS API doesn't expose (reading `configuration.yaml`, listing config files, template evaluation with filesystem context). Shares the same `ha-config` Docker volume as HA. Auth uses a static `SUPERVISOR_TOKEN` set via environment variable.

**hactl binary**: The real [hactl](https://github.com/swifty99/hactl) Go CLI binary, downloaded from GitHub releases to `.bin/hactl`. All test assertions go through this binary via subprocess calls — the same commands a human developer would use. This ensures tests verify the actual user-facing behavior, not an internal API that might drift.

**Python HactlClient** (`hactl_client.py`): Retained *only* for container onboarding. HA requires an interactive onboarding flow before its API becomes available, and the final step (creating a long-lived access token) requires a WebSocket connection. The Python client handles this setup, then all subsequent test interactions use the hactl binary exclusively.

### Container lifecycle (what `make docker-up` does)

1. `docker compose up -d` starts both containers
2. Wait for HA to become healthy (polling `/api/onboarding` via healthcheck)
3. `docker exec hemm-ha-test pip install /hemm-src` installs the hemm core library
4. `docker restart hemm-ha-test` restarts HA so it picks up the hemm package
5. Wait for HA healthy again
6. Wait for companion healthy (polling `http://127.0.0.1:9100/v1/health`)

### Onboarding (handled by pytest fixtures)

When tests start, the `ha_token` session-scoped fixture:

1. Checks for a cached token at `.bin/.ha_test_token` (for `SKIP_DOCKER_COMPOSE=1` mode)
2. If no cached token: runs headless onboarding via `HactlClient`:
   - `POST /api/onboarding/users` — creates owner account
   - `POST /auth/token` — exchanges auth code for short-lived tokens
   - WebSocket `auth/long_lived_access_token` — creates a long-lived token
   - `POST /api/onboarding/core_config` and `/api/onboarding/analytics` — completes onboarding
3. Writes token to `.bin/.ha_test_token` for reuse
4. Creates a temp directory with `.env` file (`HA_URL` + `HA_TOKEN`) for hactl
5. Returns the `Hactl` wrapper object that all tests use

### What the container tests cover

Every test file exercises a distinct area of the integration through the real hactl CLI:

| Test file | Tests | What it checks |
|---|---|---|
| `test_container.py` | 14 | Core integration lifecycle: HA healthy, hactl version, config flow setup, integration loaded, entities visible, reload works, no error logs, add all 7 device types via options flow |
| `test_hactl_companion.py` | 14 | Companion addon: health endpoint, version, config file listing, read `configuration.yaml`, secrets denied, path traversal denied, template evaluation (simple + states + invalid), script listing, automation listing, service calls |
| `test_hactl_config.py` | 13 | Config flow lifecycle: flow start returns form, data schema present, flow inspect, flow creates entry, abort on duplicate, config entries listing, entry data validation, options flow start/add device/add battery/safe_default required, reload keeps entry, config check passes |
| `test_hactl_entities.py` | 11 | Entity discovery: domain sensor listing, hemm pattern matching, all entities accessible, per-device sensors (battery 3 sensors, EV charger sensors), entity show/full/naming/history/related/anomalies (6 skipped — see Honest Gaps) |
| `test_hactl_health.py` | 9 | System health: HA running, version reporting, hactl binary version, custom component visibility via `cc ls` and `cc logs`, error log summary, component log filter, no unresolved hemm issues |
| `test_hactl_manifest.py` | 10 | Manifest validation: device config produces valid manifest for all 7 types (via config flow round-trip), diagnostics contains devices, invalid device rejected, manifest schema enforced |
| `test_hactl_stress.py` | 9 | Stress testing: 3 rapid reloads, no error logs after reloads, add 3 devices sequentially, entry remains loaded after many devices, dashboard CRUD (ls/create/show), entity state stability, health stability, no errors at end |

80 container tests collected. 74 pass. 6 are skipped (see Honest Gaps below).

### The Hactl wrapper

`tests/integration/hactl.py` provides the `Hactl` class — a typed Python wrapper around hactl subprocess calls. Each method maps to a hactl command:

```python
hactl = Hactl(binary=".bin/hactl", instance_dir="/tmp/ha-test-xyz")
result = hactl.health()                                 # hactl health --json
result = hactl.ent_ls(domain="sensor", pattern="hemm")  # hactl ent ls --domain sensor --pattern hemm --json
result = hactl.config_flow_start("hemm")                # hactl config flow-start hemm --json
```

All methods return `HactlOutput` with `.success`, `.stdout`, `.stderr`, and `.json_data`. Tests assert against the parsed JSON.

**One exception**: `config_entries()` queries the HA REST API directly (via urllib) because hactl does not yet have a `config entries` command. This is tracked as [hactl issue #1](https://github.com/swifty99/hactl/issues) in [ISSUES_HACTL_COMPANION.md](ISSUES_HACTL_COMPANION.md).

### Fixtures

The container test fixture is a single `configuration.yaml` at `tests/integration/config/configuration.yaml`. It is mounted into the HA container and provides a minimal but functional HA configuration.

Unlike hactl's multi-fixture approach (basic/faulty/realistic), ha-hemm currently uses a single fixture. The integration creates its own state through config flows during tests — each test class typically sets up a fresh HEMM config entry, adds devices, and verifies the result.

### Companion addon

The companion gives hactl filesystem access to the HA config directory. In tests, it is used for:

- Reading `configuration.yaml` to verify the test fixture loaded correctly
- Template evaluation (`hactl tpl eval '{{ states("sensor.x") }}'`)
- Listing scripts and automations
- Security boundary testing (secrets denied, path traversal denied)

The companion container requires a workaround for standalone Docker use: the published image's `/run.sh` uses a bashio shebang that only exists in HA OS. The docker-compose file overrides this with `command: ["python3", "-m", "companion"]`.

Companion tests are isolated in `test_hactl_companion.py`. If the companion is unavailable, tests skip gracefully (they do not fail).

---

## Layer 3: Pi Hardware Tests

Pi tests carry the `@pytest.mark.pi` marker and are planned for Phase 8. They will run hactl from the development machine pointed at a real HA instance on a Raspberry Pi:

```bash
# Point hactl at the Pi
mkdir -p ~/ha/pi
cat > ~/ha/pi/.env << 'EOF'
HA_URL=http://<pi-ip>:8123
HA_TOKEN=<pi-long-lived-token>
EOF

# Verify connectivity
hactl --dir ~/ha/pi health

# Run Pi tests
HA_BASE_URL=http://<pi-ip>:8123 HA_TOKEN=<token> SKIP_DOCKER_COMPOSE=1 uv run pytest -m pi
```

The same hactl binary and test patterns work — it's just pointed at a different HA instance via `--dir`. Pi tests will focus on:

- Solver performance under ARM CPU constraints (both backends)
- Memory usage during optimization runs
- SD card I/O impact on coordinator updates
- Long-soak stability (48–72h continuous operation)

---

## Running Tests Locally

The only hard prerequisite for unit tests is Python 3.12+ and `uv`. Container tests additionally require Docker.

| Goal | Command | Docker needed | Approximate time |
|---|---|---|---|
| Quick sanity check | `uv run pytest` | No | ~9 seconds |
| Lint + unit tests | `make ci` (or run both manually) | No | ~15 seconds |
| Container tests (full cycle) | `make test-container` | Yes | ~3 min first, ~2 min cached |
| Container tests (stack running) | `make test-container-quick` | Yes (running) | ~2 min |
| Specific test file | see below | Yes (running) | ~20 seconds |
| All CI checks | `make ci-full` | Yes | ~3 min |
| Lint only | `make lint` | No | ~2 seconds |
| Format | `make format` | No | ~2 seconds |

To run a specific container test file with the stack already running:

```bash
SKIP_DOCKER_COMPOSE=1 uv run pytest tests/integration/test_hactl_health.py -m container -v -o "addopts="
```

**A common mistake on Windows**: `make` is not available in PowerShell by default. Either install Make (`winget install GnuWin32.Make` or via Chocolatey), use WSL, or run the underlying commands directly:

```powershell
# Equivalent of "make test"
uv run pytest

# Equivalent of "make ci"
uv run ruff check custom_components/ tests/
uv run ruff format --check custom_components/ tests/
uv run pytest

# Equivalent of "make test-container" (manual steps on Windows)
docker compose -f docker-compose.test.yml up -d
# Wait for HA healthy...
docker exec hemm-ha-test pip install /hemm-src
docker restart hemm-ha-test
# Wait for HA healthy again...
$env:SKIP_DOCKER_COMPOSE="1"
uv run pytest tests/integration/ -m container --tb=short -v -o "addopts="
docker compose -f docker-compose.test.yml down -v --remove-orphans
```

### hactl binary management

The `hactl_binary` pytest fixture automatically downloads the latest hactl release if not found:

1. Checks `.bin/hactl` (project-local, from `make install-hactl`)
2. Checks PATH (system-wide install)
3. Downloads latest release from `https://github.com/swifty99/hactl/releases/latest/download/`

To install manually:

```bash
# Via Makefile (recommended)
make install-hactl

# Via go install (if Go is installed)
go install github.com/swifty99/hactl/cmd/hactl@latest

# Manual download (see Makefile install-hactl target for platform-specific commands)
```

### WSL2 gotchas (Windows development)

**Docker context**: WSL2 uses Docker Engine inside the Linux VM. Ensure you're using the WSL2 context, not Docker Desktop's Windows context:
```bash
docker context ls  # Should show "default" → unix:///var/run/docker.sock
```

**Port forwarding**: Docker containers inside WSL2 expose ports to `localhost` on Windows automatically. `http://localhost:8123` works from both Windows and WSL. If running Docker in a separate WSL distro, you may need `127.0.0.1` or the WSL IP.

**Volume mounts**: Named Docker volumes work identically. Bind mounts must use Linux paths in WSL. Always run tests from within the WSL filesystem (`~/repos/...`), not from `/mnt/c/...` which is slower and can cause permission issues.

**ProactorEventLoop**: If running Python tests directly on Windows (not WSL), `pytest-socket` and `aiohttp` require special handling — already done in `conftest.py` (socket enable, `ThreadedResolver`).

### Iterating on code changes

After changes to **custom component code** (`custom_components/hemm/`):
- Volume is mounted read-only; HA reads at startup
- Restart HA: `docker restart hemm-ha-test`, wait for healthy
- Re-run tests: `make test-container-quick`

After changes to **hemm core** (`../hemm/src/`):
- Reinstall in container: `docker exec hemm-ha-test pip install /hemm-src`
- Restart HA: `docker restart hemm-ha-test`, wait for healthy
- Re-run tests

---

## CI/CD Enforcement

The test suite only works as a quality gate if it runs automatically on every change. ha-hemm uses GitHub Actions for this. The workflow is defined in `.github/workflows/ci.yml` and runs on every push to `main` and every pull request targeting `main`.

The pipeline has three jobs:

**Lint** runs `ruff check` and `ruff format --check` on all source files. A formatting or style failure blocks merge.

**Unit Tests** runs `uv run pytest` against a Python version matrix (3.12, 3.13). This installs the hemm core library from GitHub (`git+https://github.com/swifty99/hemm.git`) since it's not on PyPI yet. Each matrix entry runs independently.

**Container Tests** runs the full container test suite against a matrix of HA versions. This starts the Docker Compose stack, pre-installs hemm into the container, and runs `uv run pytest tests/integration/ -m container`. The HA version matrix includes:

- Current stable version (required — failure blocks merge)
- Previous stable version (required — failure blocks merge)
- Next/beta version (non-blocking — failure shows as a warning)

If a future HA release breaks the integration, the container tests will fail before users encounter the issue. The non-blocking beta run gives advance notice of upcoming HA changes without making every PR depend on the stability of a pre-release build.

**Concurrency**: The workflow uses a concurrency group keyed on the branch/PR, so pushing new commits to the same PR cancels the previous run. This prevents wasted CI minutes.

**Dependabot** (`.github/dependabot.yml`) opens pull requests weekly for pip dependency updates and GitHub Actions version bumps.

---

## What Is Covered

The table below summarizes the current coverage across ha-hemm's features. "Unit" means there are in-process HA tests; "Container" means the feature is exercised by hactl against a real HA instance; "Companion" means the companion addon is involved.

| Feature area | Unit | Container | Companion |
|---|---|---|---|
| Config flow (hub setup) | ✓ | ✓ | — |
| Config flow (duplicate detection) | ✓ | ✓ | — |
| Options flow (settings) | ✓ | ✓ | — |
| Options flow (add device) | ✓ | ✓ | — |
| Device flow (all 7 types, beginner) | ✓ | ✓ | — |
| Device flow (pro tier) | ✓ | — | — |
| `safe_default` validation | ✓ | ✓ | — |
| Integration setup/unload | ✓ | ✓ | — |
| Integration reload | ✓ | ✓ | — |
| Coordinator creation | ✓ | ✓ | — |
| Sensor entity creation | ✓ | ✓ | — |
| Per-device sensor count | — | ✓ | — |
| Diagnostics endpoint | ✓ | ✓ | — |
| Manifest validation (all 7 types) | — | ✓ | — |
| Identification stubs | ✓ | — | — |
| Repair flow framework | ✓ | — | — |
| HA health check | — | ✓ | — |
| Error log monitoring | — | ✓ | — |
| Custom component visibility | — | ✓ | — |
| Issues/repairs listing | — | ✓ | — |
| Stress (rapid reloads) | — | ✓ | — |
| Stress (multi-device add) | — | ✓ | — |
| Dashboard CRUD | — | ✓ | — |
| Config file access | — | — | ✓ |
| Security (secrets denied) | — | — | ✓ |
| Security (path traversal) | — | — | ✓ |
| Template evaluation | — | — | ✓ |
| Script listing | — | — | ✓ |
| Automation listing | — | — | ✓ |
| Config check (service call) | — | ✓ | ✓ |

---

## Honest Gaps

No test suite is complete, and this one is no exception. The following areas are not well covered, and we think it is worth being explicit about them.

**Entity state values**: 6 container tests are skipped because the coordinator currently returns stub data (`0.0` power, `0%` confidence, `"idle"` mode). These tests (`test_ent_show_hemm_entity`, `test_ent_show_full_attributes`, `test_all_hemm_entities_have_prefix`, `test_ent_hist_returns_data`, `test_ent_related_works`, `test_ent_anomalies_clean_after_setup`) will be enabled in Phase 6 when the coordinator produces real optimization results. The skips are controlled by checking whether any hemm entity has a non-unknown state.

**Actuator layer**: The actuator-call engine with verification contracts (Phase 7) is not implemented yet, so there are no tests for script execution, timeout handling, retry logic, or the `safe_default` watchdog.

**Live optimization**: The coordinator currently returns stub data. Real MILP/distributed solver integration (Phase 6) will add tests that verify actual plan values, price signal responses, and constraint satisfaction.

**Online identification**: The identification framework exists but all identifiers return `None`. When Phase 6 activates identification, tests will verify parameter refinement, confidence reporting, and the repair-issue notification flow.

**Cross-platform CI**: All CI jobs run on Ubuntu. The integration works on Windows (verified locally), but platform-specific issues (path separators, event loop behavior) would not be caught in CI until a user reports them.

**Multi-entry scenarios**: Tests currently set up a single HEMM config entry. Multiple entries (e.g., separate buildings) are not tested.

**HA version edge cases**: The container test matrix covers 2–3 HA versions. Breaking changes in HA's config flow API, entity registry, or coordinator patterns between major versions could slip through if they happen outside the tested range.

**Companion YAML write operations**: Only read operations and security boundaries are tested. Write operations (creating scripts, automations) will be tested when the actuator layer (Phase 7) needs them.

---

## Known Upstream Issues

Issues discovered during testing are tracked in [ISSUES_HACTL_COMPANION.md](ISSUES_HACTL_COMPANION.md). Key items:

**hactl**:
- No `config entries` command — workaround: direct REST API call in test wrapper
- `--options` flag undocumented for `config flow-step`
- `cc ls` doesn't detect mounted custom_components (uses companion filesystem, not HA registry)
- `config flow-start` hangs on integration load failure instead of failing fast

**hactl-companion**:
- Published image requires bashio shebang workaround (`command: ["python3", "-m", "companion"]`)
- Alpine resolves `localhost` → `::1` but companion binds IPv4 only (use `127.0.0.1`)
- `resolve=true` returns `"null\n..."` for valid YAML
- No logging output (silent startup)

These are documented workarounds, not blockers. All container tests pass with the current workarounds in place.

---

## Quick Reference

```bash
# Prerequisites
docker info                                 # Docker must be running (container tests only)
uv --version                                # uv must be installed

# Unit tests
uv run pytest                               # Unit tests only (~9s, no Docker)

# Lint
uv run ruff check custom_components/ tests/
uv run ruff format --check custom_components/ tests/

# Container tests
make test-container                         # Full cycle: hactl install → start stack → test → teardown
make test-container-quick                   # Tests only (stack must be running)
make docker-up                              # Start stack manually
make docker-down                            # Tear down stack

# Manual hactl usage (after onboarding / token cached)
.bin/hactl --dir <tmpdir> health
.bin/hactl --dir <tmpdir> ent ls --domain sensor --pattern hemm
.bin/hactl --dir <tmpdir> config flow-start hemm

# CI checks
make ci                                     # lint + unit tests
make ci-full                                # lint + unit tests + container tests
```

The CI pipeline enforces all of the above on every pull request. If the CI badge at the top of the README is green, all required checks have passed against the current `main` branch.
