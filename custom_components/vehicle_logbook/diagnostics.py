"""Diagnostics download."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_REGISTRATION
from .coordinator import VehicleLogbookConfigEntry

TO_REDACT = {CONF_REGISTRATION, "reference"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VehicleLogbookConfigEntry
) -> dict[str, Any]:
    """Return the vehicle's config and logbook (registration and references redacted)."""
    vehicle = entry.runtime_data
    return async_redact_data(
        {
            "data": dict(entry.data),
            "options": dict(entry.options),
            "linked_odometer": vehicle.linked_odometer,
            "logbook": vehicle.export(),
        },
        TO_REDACT,
    )
