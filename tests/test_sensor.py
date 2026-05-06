"""Tests for the HEMM sensor platform."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


@pytest.mark.unit
async def test_no_sensors_without_subentries(hass: HomeAssistant, init_integration: ConfigEntry) -> None:
    """Test that no sensors are created without device sub-entries."""
    states = hass.states.async_all("sensor")
    hemm_sensors = [s for s in states if s.entity_id.startswith("sensor.")]
    # Should have no HEMM device sensors (only possible hub sensors if any)
    hemm_device_sensors = [
        s for s in hemm_sensors if "plan" in s.entity_id or "confidence" in s.entity_id or "mode" in s.entity_id
    ]
    assert len(hemm_device_sensors) == 0
