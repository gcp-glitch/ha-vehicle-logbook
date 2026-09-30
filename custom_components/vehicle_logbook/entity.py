"""Base entity for a vehicle."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import CONF_MAKE, CONF_MODEL, CONF_REGISTRATION, CONF_YEAR, DOMAIN
from .coordinator import VehicleLogbook


class VehicleLogbookEntity(Entity):
    """Entity that redraws when the vehicle's logbook changes."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, vehicle: VehicleLogbook, key: str) -> None:
        """Initialise."""
        self.vehicle = vehicle
        entry = vehicle.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        model = " ".join(
            str(v) for v in (entry.data.get(CONF_MODEL), entry.data.get(CONF_YEAR)) if v
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=entry.data.get(CONF_MAKE) or None,
            model=model or None,
            serial_number=entry.data.get(CONF_REGISTRATION) or None,
        )

    async def async_added_to_hass(self) -> None:
        """Listen for logbook updates."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.vehicle.signal, self.async_write_ha_state)
        )
