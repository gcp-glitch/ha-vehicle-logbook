"""Vehicle Logbook: fuel, services, tyres, parts, paperwork and costs per vehicle."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, STORAGE_VERSION
from .coordinator import VehicleLogbook, VehicleLogbookConfigEntry
from .services import async_setup_services

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions once for all vehicles."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: VehicleLogbookConfigEntry) -> bool:
    """Set up one vehicle."""
    vehicle = VehicleLogbook(hass, entry)
    await vehicle.async_setup()
    entry.runtime_data = vehicle
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: VehicleLogbookConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VehicleLogbookConfigEntry) -> bool:
    """Unload a vehicle."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: VehicleLogbookConfigEntry) -> None:
    """Delete the vehicle's logbook file when the vehicle is removed."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
