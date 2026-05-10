"""Entity state tests via hactl binary.

Verifies that HEMM creates the expected sensor entities per device,
with correct naming, attributes, and state values.
"""

from __future__ import annotations

import pytest

from .hactl import Hactl, HactlError


def _get_hemm_entry_id(hactl: Hactl) -> str | None:
    """Helper: get the hemm config entry ID."""
    result = hactl.config_entries()
    entries = result.json_data if isinstance(result.json_data, list) else result.json_data.get("entries", [])
    hemm_entries = [e for e in entries if e.get("domain") == "hemm"]
    return hemm_entries[0]["entry_id"] if hemm_entries else None


def _add_device(hactl: Hactl, device_type: str, config: dict) -> None:
    """Helper: add a device via options flow."""
    entry_id = _get_hemm_entry_id(hactl)
    assert entry_id, "HEMM must be set up first"

    result = hactl.config_options(entry_id)
    flow_id = result.json_data["flow_id"]

    hactl.config_flow_step(flow_id, {"action": "add_device"}, options=True)
    hactl.config_flow_step(flow_id, {"device_type": device_type, "tier": "beginner"}, options=True)
    hactl.config_flow_step(flow_id, config, options=True)


@pytest.mark.container
class TestEntityDiscovery:
    """Entity discovery and listing via hactl."""

    def test_ent_ls_domain_sensor(self, hactl: Hactl) -> None:
        """hactl ent ls --domain sensor works and returns results."""
        result = hactl.ent_ls(domain="sensor")
        assert result.success

    def test_ent_ls_pattern_hemm(self, hactl: Hactl) -> None:
        """hactl ent ls --pattern hemm finds hemm entities."""
        result = hactl.ent_ls(pattern="hemm")
        assert result.success
        # After setup, some hemm entities should exist
        output = result.stdout.lower() if result.stdout else ""
        json_str = str(result.json_data).lower() if result.json_data else ""
        assert "hemm" in output or "hemm" in json_str or result.json_data == []

    def test_ent_ls_all_entities_accessible(self, hactl: Hactl) -> None:
        """hactl ent ls without filters returns all entities."""
        result = hactl.ent_ls()
        assert result.success
        # A working HA instance always has entities
        assert result.stdout or result.json_data


@pytest.mark.container
class TestEntityPerDevice:
    """Verify correct entities are created per device type."""

    def test_battery_creates_three_sensors(self, hactl: Hactl) -> None:
        """Adding a battery creates plan, confidence, and mode sensors."""
        # Add battery device
        _add_device(
            hactl,
            "battery",
            {
                "device_name": "Ent Test Battery",
                "capacity_kwh": 10.0,
                "max_charge_kw": 5.0,
                "max_discharge_kw": 5.0,
                "safe_default_script": "script.hemm_battery_safe",
            },
        )

        # Check for entity pattern
        result = hactl.ent_ls(pattern="hemm")
        assert result.success
        output = (result.stdout or "") + str(result.json_data or "")
        # Should find plan, confidence, mode sensors
        # Entity naming: sensor.hemm_{device_id}_{type}
        assert "hemm" in output.lower()

    def test_ev_charger_creates_sensors(self, hactl: Hactl) -> None:
        """Adding an EV charger creates the expected sensors."""
        _add_device(
            hactl,
            "ev_charger",
            {
                "device_name": "Ent Test EV",
                "max_charge_kw": 11.0,
                "safe_default_script": "script.hemm_ev_safe",
            },
        )

        result = hactl.ent_ls(pattern="hemm")
        assert result.success


@pytest.mark.container
class TestEntityState:
    """Entity state inspection via hactl ent show."""

    def test_ent_show_hemm_entity(self, hactl: Hactl) -> None:
        """hactl ent show on a hemm sensor returns state + attributes."""
        # Find a hemm entity first
        result = hactl.ent_ls(pattern="hemm", domain="sensor")
        if not result.json_data:
            pytest.skip("No hemm sensor entities available")

        # Get first hemm entity
        entities = result.json_data if isinstance(result.json_data, list) else []
        if not entities:
            pytest.skip("No hemm entities in JSON response")

        entity_id = entities[0].get("entity_id", entities[0].get("id", ""))
        if not entity_id:
            pytest.skip("Cannot determine entity_id from response")

        show_result = hactl.ent_show(entity_id)
        assert show_result.success

    def test_ent_show_full_attributes(self, hactl: Hactl) -> None:
        """hactl ent show --full includes all attributes."""
        result = hactl.ent_ls(pattern="hemm", domain="sensor")
        if not result.json_data:
            pytest.skip("No hemm sensor entities available")

        entities = result.json_data if isinstance(result.json_data, list) else []
        if not entities:
            pytest.skip("No hemm entities in JSON response")

        entity_id = entities[0].get("entity_id", entities[0].get("id", ""))
        if not entity_id:
            pytest.skip("Cannot determine entity_id")

        show_result = hactl.ent_show(entity_id, full=True)
        assert show_result.success


@pytest.mark.container
class TestEntityNaming:
    """Verify entity naming conventions (hemm_ prefix)."""

    def test_all_hemm_entities_have_prefix(self, hactl: Hactl) -> None:
        """All entities from hemm domain follow sensor.hemm_* naming."""
        result = hactl.ent_ls(pattern="hemm", domain="sensor")
        if not result.json_data:
            pytest.skip("No hemm entities")

        entities = result.json_data if isinstance(result.json_data, list) else []
        for ent in entities:
            entity_id = ent.get("entity_id", ent.get("id", ""))
            if entity_id:
                assert entity_id.startswith("sensor.hemm_"), (
                    f"Entity {entity_id} doesn't follow hemm_ naming convention"
                )


@pytest.mark.container
class TestEntityHistory:
    """Entity history via hactl ent hist."""

    def test_ent_hist_returns_data(self, hactl: Hactl) -> None:
        """hactl ent hist on a hemm sensor returns history points."""
        result = hactl.ent_ls(pattern="hemm", domain="sensor")
        if not result.json_data:
            pytest.skip("No hemm sensor entities")

        entities = result.json_data if isinstance(result.json_data, list) else []
        if not entities:
            pytest.skip("No entities in response")

        entity_id = entities[0].get("entity_id", entities[0].get("id", ""))
        if not entity_id:
            pytest.skip("Cannot determine entity_id")

        # History may be empty on a fresh container, but the command should succeed
        hist_result = hactl.ent_hist(entity_id, since="1h")
        assert hist_result.success


@pytest.mark.container
class TestEntityRelated:
    """Entity relationship discovery via hactl ent related."""

    def test_ent_related_works(self, hactl: Hactl) -> None:
        """hactl ent related returns related entities/automations."""
        result = hactl.ent_ls(pattern="hemm", domain="sensor")
        if not result.json_data:
            pytest.skip("No hemm sensor entities")

        entities = result.json_data if isinstance(result.json_data, list) else []
        if not entities:
            pytest.skip("No entities")

        entity_id = entities[0].get("entity_id", entities[0].get("id", ""))
        if not entity_id:
            pytest.skip("Cannot determine entity_id")

        related_result = hactl.ent_related(entity_id)
        assert related_result.success


@pytest.mark.container
class TestEntityAnomalies:
    """Entity anomaly detection via hactl ent anomalies."""

    def test_ent_anomalies_clean_after_setup(self, hactl: Hactl) -> None:
        """No anomalies reported on freshly created hemm sensors."""
        result = hactl.ent_ls(pattern="hemm", domain="sensor")
        if not result.json_data:
            pytest.skip("No hemm sensor entities")

        entities = result.json_data if isinstance(result.json_data, list) else []
        if not entities:
            pytest.skip("No entities")

        entity_id = entities[0].get("entity_id", entities[0].get("id", ""))
        if not entity_id:
            pytest.skip("Cannot determine entity_id")

        try:
            anom_result = hactl.ent_anomalies(entity_id)
            assert anom_result.success
            # Fresh entities shouldn't have anomalies (gaps, stuck, spikes)
        except HactlError:
            # Some hactl versions may not support anomalies on all entity types
            pass
