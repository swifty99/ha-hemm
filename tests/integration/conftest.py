"""Pytest fixtures for container-based integration tests."""

from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio

from .hactl import Hactl, get_hactl_binary_name, get_hactl_download_url
from .hactl_client import HactlClient

_LOGGER = logging.getLogger(__name__)

COMPOSE_FILE = Path(__file__).parent.parent.parent / "docker-compose.test.yml"
CONFIG_DIR = Path(__file__).parent / "config"
BIN_DIR = Path(__file__).parent.parent.parent / ".bin"


def pytest_collection_modifyitems(items: list) -> None:
    """Enable sockets for integration tests (pytest-socket blocks by default)."""
    try:
        import pytest_socket

        pytest_socket.enable_socket()
        pytest_socket.disable_socket = lambda *a, **kw: None
        pytest_socket.socket_allow_hosts = lambda *a, **kw: None
    except (ImportError, AttributeError):
        pass


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Force-enable sockets before each integration test."""
    try:
        import pytest_socket

        pytest_socket.enable_socket()
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations() -> None:
    """Override parent conftest — container tests don't use HA test framework."""


@pytest.fixture(scope="session")
def ha_version() -> str:
    """HA version from environment or default."""
    return os.environ.get("HA_VERSION", "stable")


@pytest.fixture(scope="session")
def ha_base_url() -> str:
    """HA container base URL."""
    return os.environ.get("HA_BASE_URL", "http://localhost:8123")


@pytest.fixture(scope="session")
def companion_base_url() -> str:
    """Companion container base URL."""
    return os.environ.get("COMPANION_BASE_URL", "http://localhost:9100")


@pytest.fixture(scope="session")
def hactl_binary() -> Path:
    """Ensure hactl binary is available. Download from GitHub releases if needed.

    Checks in order:
    1. .bin/hactl (project-local, from `make install-hactl`)
    2. PATH (system-wide install)
    3. Download latest release to .bin/
    """
    binary_name = get_hactl_binary_name()

    # Check project .bin/ directory
    local_bin = BIN_DIR / binary_name
    if local_bin.exists():
        _LOGGER.info("Using hactl from .bin/: %s", local_bin)
        return local_bin

    # Check PATH
    which_result = shutil.which("hactl")
    if which_result:
        _LOGGER.info("Using hactl from PATH: %s", which_result)
        return Path(which_result)

    # Download latest release
    _LOGGER.info("Downloading hactl binary from GitHub releases...")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    url = get_hactl_download_url()

    try:
        import tarfile
        import tempfile
        import zipfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(url).suffix) as tmp:
            urllib.request.urlretrieve(url, tmp.name)
            archive_path = Path(tmp.name)

        if url.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(BIN_DIR)
        elif url.endswith(".tar.gz"):
            with tarfile.open(archive_path) as tf:
                tf.extractall(BIN_DIR)

        archive_path.unlink(missing_ok=True)

        # Make executable on Unix
        if sys.platform != "win32":
            local_bin.chmod(local_bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        _LOGGER.info("Downloaded hactl to: %s", local_bin)
        return local_bin
    except Exception as e:
        pytest.skip(f"Failed to download hactl binary: {e}")


@pytest.fixture(scope="session")
def docker_compose_up(ha_version: str):
    """Start HA + companion containers via docker-compose for the test session."""
    # Skip if container is already running (e.g. manually started)
    skip_docker = os.environ.get("SKIP_DOCKER_COMPOSE", "")
    if skip_docker:
        yield
        return

    env = {**os.environ, "HA_VERSION": ha_version}

    # Ensure clean config dir (remove any stale .storage etc.)
    storage_dir = CONFIG_DIR / ".storage"
    if storage_dir.exists():
        shutil.rmtree(storage_dir)

    _LOGGER.info("Starting HA container (version=%s)...", ha_version)
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"],
        env=env,
        check=True,
        capture_output=True,
        timeout=180,
    )

    # Wait for HA container to be healthy (companion may fail, that's OK)
    _LOGGER.info("Waiting for HA container to become healthy...")
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "up",
            "-d",
            "--wait",
            "homeassistant",
        ],
        env=env,
        capture_output=True,
        timeout=180,
    )

    # Install hemm package from mounted source so HA can resolve the requirement
    _LOGGER.info("Installing hemm package inside container...")
    subprocess.run(
        ["docker", "exec", "hemm-ha-test", "pip", "install", "/hemm-src"],
        capture_output=True,
        timeout=120,
    )

    # Restart HA so it picks up the newly installed hemm package
    _LOGGER.info("Restarting HA container to load hemm...")
    subprocess.run(
        ["docker", "restart", "hemm-ha-test"],
        capture_output=True,
        timeout=60,
    )
    # Wait for healthy again
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "up",
            "-d",
            "--wait",
            "homeassistant",
        ],
        env=env,
        capture_output=True,
        timeout=180,
    )

    yield

    _LOGGER.info("Stopping HA container...")
    # Remove cached token (becomes invalid after volume removal)
    token_file = BIN_DIR / ".ha_test_token"
    token_file.unlink(missing_ok=True)
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v", "--remove-orphans"],
        env=env,
        capture_output=True,
        timeout=60,
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def ha_token(docker_compose_up: None, ha_base_url: str) -> str:
    """Perform onboarding and return a long-lived access token.

    Waits for HA to be ready, performs onboarding if needed, returns token.
    Caches token to .ha_test_token for reuse with SKIP_DOCKER_COMPOSE.
    """
    token_file = BIN_DIR / ".ha_test_token"

    async with HactlClient(base_url=ha_base_url) as client:
        ready = await client.wait_for_ready(timeout=120.0)
        assert ready, "HA container did not become ready within 120s"

        if await client.needs_onboarding():
            await client.complete_onboarding()
            _LOGGER.info("HA onboarding complete, token acquired")
            # Cache token for reuse
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(client._token)
        else:
            # Already onboarded — try env, then cached token file
            token = os.environ.get("HA_TOKEN", "")
            if not token and token_file.exists():
                token = token_file.read_text().strip()
                _LOGGER.info("Using cached token from %s", token_file)
            if not token:
                msg = "HA is already onboarded but no HA_TOKEN provided and no cached token"
                raise RuntimeError(msg)
            client._token = token

        return client._token


@pytest_asyncio.fixture
async def ha_client(ha_token: str, ha_base_url: str) -> AsyncGenerator[HactlClient, None]:
    """Create a per-test authenticated hactl client."""
    async with HactlClient(base_url=ha_base_url, token=ha_token) as client:
        yield client


# --- hactl binary fixtures ---


@pytest.fixture(scope="session")
def hactl_dir(ha_token: str, ha_base_url: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a temporary hactl instance directory with .env pointing at the test HA.

    This mimics the real hactl workflow: one directory per HA instance containing .env.
    """
    dir_path = tmp_path_factory.mktemp("hactl_instance")
    env_file = dir_path / ".env"
    env_file.write_text(f"HA_URL={ha_base_url}\nHA_TOKEN={ha_token}\n")
    _LOGGER.info("Created hactl instance dir: %s", dir_path)
    return dir_path


@pytest.fixture(scope="session")
def hactl_session(hactl_binary: Path, hactl_dir: Path) -> Hactl:
    """Session-scoped hactl instance — reused across tests for efficiency.

    Use this for read-only operations. For tests that modify state,
    prefer the function-scoped `hactl` fixture.
    """
    h = Hactl(binary=hactl_binary, instance_dir=hactl_dir)
    # Verify connectivity
    try:
        h.health()
        _LOGGER.info("hactl session connected to HA successfully")
    except Exception as e:
        pytest.skip(f"hactl cannot connect to HA container: {e}")
    return h


@pytest.fixture
def hactl(hactl_binary: Path, hactl_dir: Path) -> Hactl:
    """Function-scoped hactl instance — fresh per test.

    Safe for tests that modify state.
    """
    return Hactl(binary=hactl_binary, instance_dir=hactl_dir)
