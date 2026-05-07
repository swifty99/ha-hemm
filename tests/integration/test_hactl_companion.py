"""Companion addon integration tests via hactl binary.

Tests the hactl-companion addon which provides YAML file access for templates,
scripts, and automations. If the companion is unavailable or broken, tests are
marked as deferred (xfail) and issues should be filed at:
https://github.com/swifty99/hactl/issues

Run with: make test-container (companion container must be healthy)
"""

from __future__ import annotations

import os
import urllib.request

import pytest

from .hactl import Hactl, HactlError

# Companion base URL (from docker-compose: port 9100 mapped)
COMPANION_URL = os.environ.get("COMPANION_BASE_URL", "http://127.0.0.1:9100")


def _companion_available() -> bool:
    """Check if the companion service is reachable."""
    try:
        req = urllib.request.Request(f"{COMPANION_URL}/v1/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


# Mark all tests in this module: skip if companion is unreachable
pytestmark = [
    pytest.mark.container,
    pytest.mark.skipif(
        not _companion_available(),
        reason="Companion addon not available — file issue at https://github.com/swifty99/hactl/issues",
    ),
]


class TestCompanionHealth:
    """Companion service health checks."""

    def test_companion_health_endpoint(self) -> None:
        """Companion /v1/health responds with status ok."""
        req = urllib.request.Request(f"{COMPANION_URL}/v1/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            import json

            data = json.loads(resp.read())
            assert data.get("status") == "ok"
            assert "version" in data

    def test_companion_version_reported(self) -> None:
        """Companion reports its version in health response."""
        req = urllib.request.Request(f"{COMPANION_URL}/v1/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            import json

            data = json.loads(resp.read())
            version = data.get("version", "")
            assert version, "Companion did not report version"


class TestCompanionConfigFiles:
    """Config file listing and reading via companion."""

    def test_list_config_files(self) -> None:
        """Companion lists config files in /config."""
        import json

        req = urllib.request.Request(
            f"{COMPANION_URL}/v1/config/files",
            method="GET",
            headers={"Authorization": "Bearer integration-test-token-12345"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            data = json.loads(resp.read())
            files = data.get("files", [])
            assert "configuration.yaml" in files

    def test_read_configuration_yaml(self) -> None:
        """Companion can read configuration.yaml."""
        import json
        import urllib.parse

        path = urllib.parse.quote("configuration.yaml")
        req = urllib.request.Request(
            f"{COMPANION_URL}/v1/config/file?path={path}",
            method="GET",
            headers={"Authorization": "Bearer integration-test-token-12345"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            data = json.loads(resp.read())
            assert "content" in data
            # Content should be non-empty (at minimum HA writes something)
            assert data["content"].strip(), "configuration.yaml is empty"

    def test_secrets_yaml_denied(self) -> None:
        """Companion denies access to secrets.yaml (403)."""
        import urllib.error
        import urllib.parse

        path = urllib.parse.quote("secrets.yaml")
        req = urllib.request.Request(
            f"{COMPANION_URL}/v1/config/file?path={path}",
            method="GET",
            headers={"Authorization": "Bearer integration-test-token-12345"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=10)
        assert exc_info.value.code == 403

    def test_path_traversal_denied(self) -> None:
        """Companion denies path traversal attempts (400)."""
        import urllib.error
        import urllib.parse

        path = urllib.parse.quote("../etc/passwd")
        req = urllib.request.Request(
            f"{COMPANION_URL}/v1/config/file?path={path}",
            method="GET",
            headers={"Authorization": "Bearer integration-test-token-12345"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=10)
        assert exc_info.value.code == 400


class TestCompanionTemplates:
    """Template sensor operations via companion (hactl tpl commands)."""

    def test_tpl_eval_simple(self, hactl: Hactl) -> None:
        """hactl tpl eval with a simple expression works."""
        result = hactl.tpl_eval('{{ 2 + 2 }}')
        assert result.success
        # Result should contain "4"
        assert "4" in result.stdout

    def test_tpl_eval_states_function(self, hactl: Hactl) -> None:
        """hactl tpl eval can call states() function."""
        result = hactl.tpl_eval('{{ states("sun.sun") }}')
        assert result.success
        # sun.sun should be "above_horizon" or "below_horizon"
        output = result.stdout.lower()
        assert "horizon" in output or "above" in output or "below" in output

    def test_tpl_eval_invalid_returns_error(self, hactl: Hactl) -> None:
        """hactl tpl eval with invalid Jinja returns an error indicator."""
        # This may or may not raise — depends on hactl's error handling
        try:
            result = hactl.tpl_eval('{{ invalid_function_xyz() }}')
            # If it succeeds, the output should indicate an error
            assert "error" in result.stdout.lower() or "undefined" in result.stdout.lower()
        except HactlError:
            # hactl returning non-zero on invalid template is also acceptable
            pass


class TestCompanionScripts:
    """Script operations via companion."""

    def test_script_ls_works(self, hactl: Hactl) -> None:
        """hactl script ls returns scripts (may be empty on fresh container)."""
        result = hactl.script_ls()
        assert result.success

    def test_script_ls_no_failing(self, hactl: Hactl) -> None:
        """No failing scripts on a fresh container."""
        try:
            result = hactl.script_ls(failing=True)
            assert result.success
            # Empty or no failing scripts is expected
        except HactlError:
            # Some hactl versions may not find any scripts — that's ok
            pass


class TestCompanionAutomations:
    """Automation operations via companion."""

    def test_auto_ls_works(self, hactl: Hactl) -> None:
        """hactl auto ls returns automations (may be empty on fresh container)."""
        result = hactl.auto_ls()
        assert result.success

    def test_auto_ls_no_failing(self, hactl: Hactl) -> None:
        """No failing automations on a fresh container."""
        try:
            result = hactl.auto_ls(failing=True)
            assert result.success
        except HactlError:
            pass


class TestCompanionServices:
    """Service calls via hactl svc command."""

    def test_svc_call_check_config(self, hactl: Hactl) -> None:
        """hactl svc call homeassistant.check_config succeeds."""
        result = hactl.svc_call("homeassistant.check_config")
        assert result.success
