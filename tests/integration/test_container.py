"""Container-based integration tests for HEMM.

These tests spin up a real HA container, perform onboarding, install the HEMM
integration via the config flow API, and verify it works end-to-end.

Run with: make test-container (requires Docker)
"""

from __future__ import annotations

import pytest

from .hactl_client import HactlClient


@pytest.mark.container
async def test_ha_container_healthy(ha_client: HactlClient) -> None:
    """Test that HA container is running and healthy."""
    result = await ha_client.get_health()
    assert result.status == 200
    assert result.data.get("message") == "API running."


@pytest.mark.container
async def test_ha_config_accessible(ha_client: HactlClient) -> None:
    """Test that HA config is accessible after onboarding."""
    result = await ha_client.get_config()
    assert result.status == 200
    assert "version" in result.data
    assert "components" in result.data


@pytest.mark.container
async def test_hemm_integration_setup(ha_client: HactlClient) -> None:
    """Test that the HEMM integration can be set up via config flow."""
    # Create HEMM config entry via flow
    result = await ha_client.create_config_entry(
        domain="hemm",
        data={
            "name": "HEMM",
            "horizon_hours": 24,
            "max_iterations": 50,
            "price_adapter": "template",
            "solver_backend": "milp_central",
        },
    )
    assert result.status == 200
    assert result.data.get("type") == "create_entry"
    assert result.data.get("title") == "HEMM"


@pytest.mark.container
async def test_hemm_integration_loaded(ha_client: HactlClient) -> None:
    """Test that the HEMM domain appears in loaded config entries."""
    # First set up the integration
    await ha_client.create_config_entry(
        domain="hemm",
        data={
            "name": "HEMM",
            "horizon_hours": 24,
            "max_iterations": 50,
            "price_adapter": "template",
            "solver_backend": "milp_central",
        },
    )

    # Verify it's in config entries
    entries = await ha_client.get_config_entries()
    assert entries.status == 200
    hemm_entries = [e for e in entries.data["entries"] if e.get("domain") == "hemm"]
    assert len(hemm_entries) >= 1
    assert hemm_entries[0]["state"] == "loaded"


@pytest.mark.container
async def test_hemm_diagnostics_retrievable(ha_client: HactlClient) -> None:
    """Test that diagnostics endpoint is accessible for the HEMM entry."""
    # Set up integration
    flow_result = await ha_client.create_config_entry(
        domain="hemm",
        data={
            "name": "HEMM",
            "horizon_hours": 24,
            "max_iterations": 50,
            "price_adapter": "template",
            "solver_backend": "milp_central",
        },
    )

    # Get the entry ID from the flow result
    entry_id = flow_result.data.get("result", {}).get("entry_id")
    if not entry_id:
        # Fetch from config entries
        entries = await ha_client.get_config_entries()
        hemm_entries = [e for e in entries.data["entries"] if e.get("domain") == "hemm"]
        assert hemm_entries, "HEMM integration not found"
        entry_id = hemm_entries[0]["entry_id"]

    # Get diagnostics
    diag = await ha_client.get_diagnostics(entry_id)
    assert diag.status == 200
    assert "tested_ha_version" in diag.data.get("data", {})


@pytest.mark.container
async def test_hemm_reload(ha_client: HactlClient) -> None:
    """Test that the HEMM integration can be reloaded."""
    # Ensure integration exists
    entries = await ha_client.get_config_entries()
    hemm_entries = [e for e in entries.data["entries"] if e.get("domain") == "hemm"]

    if not hemm_entries:
        await ha_client.create_config_entry(
            domain="hemm",
            data={
                "name": "HEMM",
                "horizon_hours": 24,
                "max_iterations": 50,
                "price_adapter": "template",
                "solver_backend": "milp_central",
            },
        )
        entries = await ha_client.get_config_entries()
        hemm_entries = [e for e in entries.data["entries"] if e.get("domain") == "hemm"]

    entry_id = hemm_entries[0]["entry_id"]
    result = await ha_client.reload_integration(entry_id)
    # Reload should succeed (2xx)
    assert result.status in (200, 201, 204)
