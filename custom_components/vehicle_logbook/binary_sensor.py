"""Binary sensor: something needs attention."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import STATUS_OVERDUE
from .coordinator import VehicleLogbook, VehicleLogbookConfigEntry
from .entity import VehicleLogbookEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VehicleLogbookConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the attention sensor."""
    async_add_entities([AttentionBinarySensor(entry.runtime_data)])


class AttentionBinarySensor(VehicleLogbookEntity, BinarySensorEntity):
    """On when anything is due soon or overdue."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "needs_attention"

    def __init__(self, vehicle: VehicleLogbook) -> None:
        """Initialise."""
        super().__init__(vehicle, "needs_attention")

    @property
    def is_on(self) -> bool:
        """Anything due soon or overdue."""
        return bool(self.vehicle.summary.get("attention"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Items needing attention."""
        items = self.vehicle.summary.get("attention", [])
        return {
            "overdue": [i.key for i in items if i.status == STATUS_OVERDUE],
            "due_soon": [i.key for i in items if i.status != STATUS_OVERDUE],
            "items": [i.as_dict() for i in items],
        }
