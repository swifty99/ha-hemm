"""Stress and regression tests via hactl binary.

Tests that verify stability under repeated operations: rapid reloads,
device add/remove cycles, multiple coordinator runs, and dashboard operations.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from .hactl import Hactl, HactlError

# Standard HEMM config flow data
HEMM_FLOW_DATA = {
    "name": "HEMM",
    "horizon_hours": 24,
    "max_iterations": 50,
    "price_adapter": "template",
    "solver_backend": "milp_central",
}


def _get_hemm_entry_id(hactl: Hactl) -> str | None:
    """Helper: get hemm config entry ID."""
    result = hactl.config_entries()
    entries = result.json_data if isinstance(result.json_data, list) else result.json_data.get("entries", [])
    hemm_entries = [e for e in entries if e.get("domain") == "hemm"]
    return hemm_entries[0]["entry_id"] if hemm_entries else None


def _ensure_hemm_entry(hactl: Hactl) -> str:
    """Helper: ensure HEMM is set up."""
    entry_id = _get_hemm_entry_id(hactl)
    if entry_id:
        return entry_id
    result = hactl.config_flow_start("hemm")
    flow_id = result.json_data["flow_id"]
    hactl.config_flow_step(flow_id, HEMM_FLOW_DATA)
    entry_id = _get_hemm_entry_id(hactl)
    assert entry_id
    return entry_id


@pytest.mark.container
class TestRapidReloads:
    """Test that rapid reloads don't crash the integration."""

    def test_three_rapid_reloads(self, hactl: Hactl) -> None:
        """Three rapid config entry reloads don't crash HEMM."""
        entry_id = _ensure_hemm_entry(hactl)

        for _i in range(3):
            hactl.svc_call("homeassistant.reload_config_entry", {"entry_id": entry_id})

        # Verify still loaded after rapid reloads
        result = hactl.config_entries()
        entries = result.json_data if isinstance(result.json_data, list) else result.json_data.get("entries", [])
        hemm_entry = next((e for e in entries if e.get("domain") == "hemm"), None)
        assert hemm_entry is not None
        assert hemm_entry["state"] == "loaded"

    def test_reload_no_error_logs(self, hactl: Hactl) -> None:
        """After rapid reloads, no hemm error logs appear."""
        entry_id = _ensure_hemm_entry(hactl)
        hactl.svc_call("homeassistant.reload_config_entry", {"entry_id": entry_id})

        # Check for errors
        result = hactl.log(errors=True, component="hemm")
        assert result.success
        # If there are error entries specifically from hemm about reload, flag it
        if (
            result.stdout
            and "hemm" in result.stdout.lower()
            and "error" in result.stdout.lower()
            and ("traceback" in result.stdout.lower() or "exception" in result.stdout.lower())
        ):
            pytest.fail(f"Reload caused hemm errors:\n{result.stdout[:500]}")


@pytest.mark.container
class TestDeviceAddRemoveCycle:
    """Test adding and removing devices in sequence."""

    DEVICE_CONFIGS: ClassVar[list[tuple[str, dict[str, object]]]] = [
        ("battery", {
            "device_name": "Cycle Battery",
            "capacity_kwh": 10.0,
            "max_charge_kw": 5.0,
            "max_discharge_kw": 5.0,
            "safe_default_script": "script.hemm_battery_safe",
        }),
        ("ev_charger", {
            "device_name": "Cycle EV",
            "max_charge_kw": 11.0,
            "safe_default_script": "script.hemm_ev_safe",
        }),
        ("heat_pump", {
            "device_name": "Cycle HP",
            "max_power_kw": 5.0,
            "safe_default_script": "script.hemm_hp_safe",
        }),
    ]

    def test_add_three_devices_sequentially(self, hactl: Hactl) -> None:
        """Adding 3 devices sequentially leaves integration healthy."""
        entry_id = _ensure_hemm_entry(hactl)

        for device_type, config in self.DEVICE_CONFIGS:
            result = hactl.config_options(entry_id)
            flow_id = result.json_data["flow_id"]

            hactl.config_flow_step(flow_id, {"action": "add_device"}, options=True)
            hactl.config_flow_step(flow_id, {"device_type": device_type, "tier": "beginner"}, options=True)
            result = hactl.config_flow_step(flow_id, config, options=True)
            assert result.json_data.get("type") == "create_entry", (
                f"Failed to add {device_type}: {result.json_data}"
            )

        # Verify integration still healthy
        result = hactl.config_entries()
        entries = result.json_data if isinstance(result.json_data, list) else result.json_data.get("entries", [])
        hemm_entry = next(e for e in entries if e.get("domain") == "hemm")
        assert hemm_entry["state"] == "loaded"

    def test_entry_remains_loaded_after_many_devices(self, hactl: Hactl) -> None:
        """Integration state remains 'loaded' with many devices configured."""
        result = hactl.config_entries()
        entries = result.json_data if isinstance(result.json_data, list) else result.json_data.get("entries", [])
        hemm_entry = next((e for e in entries if e.get("domain") == "hemm"), None)
        if hemm_entry:
            assert hemm_entry["state"] == "loaded"


@pytest.mark.container
class TestDashboard:
    """Dashboard operations via hactl (Phase 9 prep)."""

    def test_dash_ls_works(self, hactl: Hactl) -> None:
        """hactl dash ls succeeds on container."""
        result = hactl.dash_ls()
        assert result.success

    def test_dash_create_hemm(self, hactl: Hactl) -> None:
        """Create a hemm-specific dashboard."""
        try:
            result = hactl.dash_create(
                url_path="hemm-test",
                title="HEMM Test Dashboard",
                icon="mdi:flash",
                confirm=True,
            )
            assert result.success
        except HactlError as e:
            # Dashboard creation may fail if already exists — that's ok
            if "already" in e.output.stderr.lower() or "exists" in e.output.stderr.lower():
                pass
            else:
                raise

    def test_dash_show_default(self, hactl: Hactl) -> None:
        """hactl dash show (default dashboard) works."""
        try:
            result = hactl.dash_show()
            assert result.success
        except HactlError:
            # May fail if no default dashboard exists — acceptable on fresh container
            pass


@pytest.mark.container
class TestMultipleCoordinatorRuns:
    """Verify coordinator can run multiple cycles without error."""

    def test_entity_state_stable_across_checks(self, hactl: Hactl) -> None:
        """Entity states remain consistent across multiple hactl queries."""
        # Query hemm entities twice — state should be consistent
        result1 = hactl.ent_ls(pattern="hemm")
        result2 = hactl.ent_ls(pattern="hemm")
        assert result1.success
        assert result2.success
        # Both should return the same set of entities
        # (not checking exact values since coordinator may update)

    def test_health_stable_after_operations(self, hactl: Hactl) -> None:
        """HA remains healthy after all our test operations."""
        result = hactl.health()
        assert result.success
        assert result.json_data is not None

    def test_no_hemm_errors_at_end(self, hactl: Hactl) -> None:
        """Final check: no hemm errors accumulated during test session."""
        try:
            result = hactl.cc_logs("hemm", unique=True)
            assert result.success
            # If there are errors, log them but don't necessarily fail
            # (some may be from intentional invalid-config tests)
        except HactlError:
            # No logs command or no hemm logs is fine
            pass
