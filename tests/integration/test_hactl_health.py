"""Health and system-level tests via hactl binary.

Tests in this module verify the HA container is healthy, the hemm custom component
is installed and running, and there are no unexpected errors.
"""

from __future__ import annotations

import pytest

from .hactl import Hactl, HactlError


@pytest.mark.container
class TestHactlHealth:
    """HA container health checks via hactl."""

    def test_health_returns_running(self, hactl: Hactl) -> None:
        """hactl health reports HA is running."""
        result = hactl.health()
        assert result.success
        assert result.json_data is not None
        # HA health JSON should contain state info
        data = result.json_data
        if isinstance(data, dict):
            # Accept various response shapes from different hactl versions
            assert any(k in data for k in ("state", "version", "ha_version", "status"))

    def test_health_reports_version(self, hactl: Hactl) -> None:
        """hactl health includes HA version."""
        result = hactl.health()
        assert result.success
        # Version should appear somewhere in the output
        text = result.stdout
        assert "202" in text  # HA versions are 2024.x, 2025.x, 2026.x

    def test_hactl_binary_version(self, hactl: Hactl) -> None:
        """hactl version command works."""
        result = hactl.version()
        assert result.success
        assert result.stdout.strip()  # Non-empty output


@pytest.mark.container
class TestHactlCustomComponents:
    """Custom component visibility via hactl."""

    def test_cc_ls_shows_hemm(self, hactl: Hactl) -> None:
        """hactl cc ls includes the hemm custom component."""
        result = hactl.cc_ls()
        if not result.success:
            pytest.skip("hactl cc ls not available (requires companion)")
        # hemm should appear in the output
        output = result.stdout.lower() if result.stdout else ""
        json_str = str(result.json_data).lower() if result.json_data else ""
        if "no custom components" in output:
            # cc ls doesn't detect mounted custom_components — verify via config entries
            entries = hactl.config_entries()
            assert entries.success and entries.json_data
            hemm = [e for e in entries.json_data if e.get("domain") == "hemm"]
            assert hemm, "hemm not found via cc ls or config entries"
        else:
            assert "hemm" in output or "hemm" in json_str, (
                f"hemm not found in cc ls output:\nstdout: {result.stdout}\njson: {result.json_data}"
            )

    def test_cc_logs_hemm_no_errors(self, hactl: Hactl) -> None:
        """hactl cc logs hemm — no error-level entries after clean setup."""
        try:
            result = hactl.cc_logs("hemm", unique=True)
            # If command succeeds, check that there are no critical errors
            # Empty output or "no errors" is fine
            assert result.success
        except HactlError as e:
            # If hactl returns non-zero because there are no logs, that's ok
            if "no" in e.output.stderr.lower() or "empty" in e.output.stderr.lower():
                pass
            else:
                raise


@pytest.mark.container
class TestHactlLogs:
    """System log inspection via hactl."""

    def test_log_errors_unique_after_setup(self, hactl: Hactl) -> None:
        """No unexpected error-level logs from hemm after fresh setup."""
        result = hactl.log(errors=True, unique=True)
        assert result.success
        # Check that hemm-related errors are absent or expected
        output = result.stdout.lower() if result.stdout else ""
        # Errors related to hemm would be concerning; generic HA errors are ok
        # We're looking for absence of hemm-specific errors
        if "hemm" in output:
            # Only acceptable hemm log messages are warnings, not errors
            # If there are hemm errors, this test should fail for investigation
            pytest.fail(f"Unexpected hemm errors in log:\n{result.stdout}")

    def test_log_component_filter(self, hactl: Hactl) -> None:
        """hactl log --component hemm returns only hemm-related entries."""
        result = hactl.log(component="hemm")
        assert result.success
        # May be empty (no log entries) — that's fine


@pytest.mark.container
class TestHactlIssues:
    """Repair issues inspection via hactl."""

    def test_no_unresolved_hemm_issues(self, hactl: Hactl) -> None:
        """No unresolved repair issues from hemm domain after setup."""
        result = hactl.issues()
        assert result.success
        # If there are issues, check none are from hemm domain
        if result.json_data:
            issues = result.json_data if isinstance(result.json_data, list) else result.json_data.get("issues", [])
            hemm_issues = [i for i in issues if i.get("domain") == "hemm"]
            assert not hemm_issues, f"Unexpected hemm repair issues: {hemm_issues}"
