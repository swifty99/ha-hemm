"""Tests for HEMM services and coordinator Phase 6 features."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.hemm.const import (
    DOMAIN,
    EVENT_SOLVER_SWITCHED,
    SERVICE_ADD_CONSTRAINT,
    SERVICE_BUMP_PRIORITY,
    SERVICE_REMOVE_CONSTRAINT,
    SERVICE_REPLAN,
    SERVICE_SET_SOLVER,
    SERVICE_SIMULATE,
    SERVICE_TICK,
)
from custom_components.hemm.coordinator import HemmCoordinator


@pytest.mark.unit
async def test_services_registered(hass: HomeAssistant, init_integration: ConfigEntry) -> None:
    """Test that all Phase 6 services are registered."""
    assert hass.services.has_service(DOMAIN, SERVICE_REPLAN)
    assert hass.services.has_service(DOMAIN, SERVICE_SIMULATE)
    assert hass.services.has_service(DOMAIN, SERVICE_SET_SOLVER)
    assert hass.services.has_service(DOMAIN, SERVICE_ADD_CONSTRAINT)
    assert hass.services.has_service(DOMAIN, SERVICE_REMOVE_CONSTRAINT)
    assert hass.services.has_service(DOMAIN, SERVICE_BUMP_PRIORITY)
    assert hass.services.has_service(DOMAIN, SERVICE_TICK)


@pytest.mark.unit
async def test_services_unregistered_on_unload(hass: HomeAssistant, init_integration: ConfigEntry) -> None:
    """Test that services are unregistered when the last entry is unloaded."""
    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert not hass.services.has_service(DOMAIN, SERVICE_REPLAN)
    assert not hass.services.has_service(DOMAIN, SERVICE_TICK)


@pytest.mark.unit
async def test_coordinator_stub_mode(hass: HomeAssistant, init_integration: ConfigEntry) -> None:
    """Test coordinator operates in stub mode when hemm core is unavailable."""
    coordinator: HemmCoordinator = hass.data[DOMAIN][init_integration.entry_id]
    assert coordinator.data is not None
    # In stub mode (no solver run yet), coordinator returns idle data
    assert coordinator.data["last_status"] in ("idle", "stub", "optimal")
    assert coordinator.data["iteration_count"] >= 0


@pytest.mark.unit
async def test_coordinator_properties_phase6(hass: HomeAssistant, init_integration: ConfigEntry) -> None:
    """Test new coordinator properties from Phase 6."""
    coordinator: HemmCoordinator = hass.data[DOMAIN][init_integration.entry_id]
    assert coordinator.last_result is None  # No solver run in stub mode
    assert coordinator.dry_run_log == []
    assert coordinator.id_results == []


@pytest.mark.unit
async def test_coordinator_switch_solver(hass: HomeAssistant, init_integration: ConfigEntry) -> None:
    """Test solver switching fires event."""
    coordinator: HemmCoordinator = hass.data[DOMAIN][init_integration.entry_id]

    events = []
    hass.bus.async_listen(EVENT_SOLVER_SWITCHED, lambda e: events.append(e))

    coordinator.switch_solver("distributed")
    await hass.async_block_till_done()

    assert coordinator.solver_backend == "distributed"
    assert len(events) == 1
    assert events[0].data["old_backend"] == "milp_central"
    assert events[0].data["new_backend"] == "distributed"


@pytest.mark.unit
async def test_service_set_solver(hass: HomeAssistant, init_integration: ConfigEntry) -> None:
    """Test hemm.set_solver service call."""
    events = []
    hass.bus.async_listen(EVENT_SOLVER_SWITCHED, lambda e: events.append(e))

    await hass.services.async_call(DOMAIN, SERVICE_SET_SOLVER, {"backend": "distributed"}, blocking=True)
    await hass.async_block_till_done()

    coordinator: HemmCoordinator = hass.data[DOMAIN][init_integration.entry_id]
    assert coordinator.solver_backend == "distributed"
    assert len(events) == 1


@pytest.mark.unit
async def test_service_set_solver_dry_run(hass: HomeAssistant, init_integration: ConfigEntry) -> None:
    """Test hemm.set_solver with dry_run doesn't change backend."""
    await hass.services.async_call(
        DOMAIN, SERVICE_SET_SOLVER, {"backend": "distributed", "dry_run": True}, blocking=True
    )
    await hass.async_block_till_done()

    coordinator: HemmCoordinator = hass.data[DOMAIN][init_integration.entry_id]
    assert coordinator.solver_backend == "milp_central"  # Unchanged


@pytest.mark.unit
async def test_coordinator_data_keys(hass: HomeAssistant, init_integration: ConfigEntry) -> None:
    """Test coordinator data contains all Phase 6 keys."""
    coordinator: HemmCoordinator = hass.data[DOMAIN][init_integration.entry_id]
    data = coordinator.data
    assert data is not None
    assert "last_status" in data
    assert "last_solve_time" in data
    assert "device_plans" in data
    assert "last_plans" in data
    assert "iteration_count" in data


@pytest.mark.unit
async def test_diagnostics_extended(hass: HomeAssistant, init_integration: ConfigEntry) -> None:
    """Test extended diagnostics output."""
    from custom_components.hemm.diagnostics import async_get_config_entry_diagnostics

    diag = await async_get_config_entry_diagnostics(hass, init_integration)

    assert "tested_ha_version" in diag
    assert "active_constraint_windows" in diag
    assert "last_solver_result" in diag
    assert "lambda_history" in diag
    assert "dry_run_log" in diag
    assert "identification_results" in diag
    assert "coordinator_state" in diag
    assert "last_status" in diag["coordinator_state"]
