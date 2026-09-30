"""Sensors for Vehicle Logbook."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DOCUMENTS,
    ITEM_OIL,
    ITEM_SERVICE,
    ITEM_TYRE_ROTATION,
    ITEM_TYRES,
    PARTS,
    SENSOR_DOCUMENTS,
    SENSOR_PARTS,
    STATUSES,
)
from .coordinator import VehicleLogbook, VehicleLogbookConfigEntry
from .entity import VehicleLogbookEntity
from .logbook import DueItem

ALL_ITEMS = [ITEM_SERVICE, ITEM_OIL, ITEM_TYRE_ROTATION, ITEM_TYRES, *PARTS, *DOCUMENTS]

type Summary = dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class LogbookSensorDescription(SensorEntityDescription):
    """Sensor description with value/attribute callbacks."""

    value_fn: Callable[[Summary], Any]
    attrs_fn: Callable[[Summary], dict[str, Any]] | None = None
    money: bool = False  # unit is the HA currency (optionally with a suffix)
    money_suffix: str = ""


def _item(summary: Summary, key: str) -> DueItem | None:
    return summary.get("items", {}).get(key)


def _item_attrs(key: str) -> Callable[[Summary], dict[str, Any]]:
    def attrs(summary: Summary) -> dict[str, Any]:
        item = _item(summary, key)
        return item.as_dict() if item else {}

    return attrs


def _all_items(summary: Summary) -> dict[str, Any]:
    items: list[DueItem] = list(summary.get("items", {}).values())
    known = sorted(
        (i for i in items if i.status != "unknown"),
        key=lambda i: (i.effective_date or date.max, i.km_remaining or 0),
    )
    nxt = summary.get("next_due")
    return {
        **(nxt.as_dict() if nxt else {}),
        "upcoming": [i.as_dict() for i in known],
        "not_tracked_yet": [i.key for i in items if i.status == "unknown"],
    }


def _fuel(attr: str) -> Callable[[Summary], Any]:
    return lambda s: getattr(s["fuel"], attr) if s.get("fuel") else None


SENSORS: tuple[LogbookSensorDescription, ...] = (
    LogbookSensorDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda s: s.get("odometer"),
        attrs_fn=lambda s: {"km_per_day": s.get("km_per_day"), "monthly_km": s.get("monthly_km", [])},
    ),
    LogbookSensorDescription(
        key="fuel_consumption",
        translation_key="fuel_consumption",
        native_unit_of_measurement="L/100km",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_fuel("avg_consumption"),
        attrs_fn=lambda s: {
            "fillups": s["fuel"].fillup_count,
            "total_litres": s["fuel"].total_litres,
            "suspect_fillups": s["fuel"].suspect_count,
            "history": s["fuel"].history,
        },
    ),
    LogbookSensorDescription(
        key="last_fuel_consumption",
        translation_key="last_fuel_consumption",
        native_unit_of_measurement="L/100km",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_fuel("last_consumption"),
    ),
    LogbookSensorDescription(
        key="last_fuel_price",
        translation_key="last_fuel_price",
        money=True,
        money_suffix="/L",
        suggested_display_precision=2,
        value_fn=_fuel("last_price_per_litre"),
        attrs_fn=lambda s: {
            "last_fillup_date": s["fuel"].last_fillup_date,
            "price_history": s["fuel"].price_history,
        },
    ),
    LogbookSensorDescription(
        key="fuel_cost_per_km",
        translation_key="fuel_cost_per_km",
        money=True,
        money_suffix="/km",
        suggested_display_precision=2,
        value_fn=_fuel("cost_per_km"),
    ),
    LogbookSensorDescription(
        key="running_cost_per_km",
        translation_key="running_cost_per_km",
        money=True,
        money_suffix="/km",
        suggested_display_precision=2,
        value_fn=lambda s: s.get("running_cost_per_km"),
    ),
    LogbookSensorDescription(
        key="fuel_spend_this_month",
        translation_key="fuel_spend_this_month",
        device_class=SensorDeviceClass.MONETARY,
        money=True,
        suggested_display_precision=0,
        value_fn=lambda s: s["costs"]["fuel_month"],
    ),
    LogbookSensorDescription(
        key="cost_this_month",
        translation_key="cost_this_month",
        device_class=SensorDeviceClass.MONETARY,
        money=True,
        suggested_display_precision=0,
        value_fn=lambda s: s["costs"]["month"],
    ),
    LogbookSensorDescription(
        key="cost_this_year",
        translation_key="cost_this_year",
        device_class=SensorDeviceClass.MONETARY,
        money=True,
        suggested_display_precision=0,
        value_fn=lambda s: s["costs"]["year"],
        attrs_fn=lambda s: {
            "by_category": s["costs"]["year_by_category"],
            "monthly": s.get("monthly_costs", []),
        },
    ),
    LogbookSensorDescription(
        key="total_cost",
        translation_key="total_cost",
        device_class=SensorDeviceClass.MONETARY,
        money=True,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s["costs"]["total"],
        attrs_fn=lambda s: {"records": s.get("counts")},
    ),
    LogbookSensorDescription(
        key="next_due",
        translation_key="next_due",
        device_class=SensorDeviceClass.ENUM,
        options=[*ALL_ITEMS, "nothing"],
        value_fn=lambda s: s["next_due"].key if s.get("next_due") else "nothing",
        attrs_fn=_all_items,
    ),
    LogbookSensorDescription(
        key="service_due_in",
        translation_key="service_due_in",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        value_fn=lambda s: (i.km_remaining if (i := _item(s, ITEM_SERVICE)) else None),
        attrs_fn=_item_attrs(ITEM_SERVICE),
    ),
    LogbookSensorDescription(
        key="service_due_date",
        translation_key="service_due_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda s: (i.due_date if (i := _item(s, ITEM_SERVICE)) else None),
    ),
    *(
        LogbookSensorDescription(
            key=f"{item}_status",
            translation_key=f"{item}_status",
            device_class=SensorDeviceClass.ENUM,
            options=STATUSES,
            value_fn=(lambda s, k=item: (i.status if (i := _item(s, k)) else "unknown")),
            attrs_fn=_item_attrs(item),
        )
        for item in (
            ITEM_SERVICE,
            ITEM_OIL,
            ITEM_TYRE_ROTATION,
            ITEM_TYRES,
            *SENSOR_PARTS,
            *SENSOR_DOCUMENTS,
        )
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VehicleLogbookConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for a vehicle."""
    vehicle = entry.runtime_data
    async_add_entities(LogbookSensor(vehicle, description) for description in SENSORS)


class LogbookSensor(VehicleLogbookEntity, SensorEntity):
    """A logbook sensor."""

    # Chart data lives in attributes; keep it out of the recorder database.
    _unrecorded_attributes = frozenset(
        {"history", "price_history", "monthly", "monthly_km", "upcoming", "not_tracked_yet"}
    )

    entity_description: LogbookSensorDescription

    def __init__(self, vehicle: VehicleLogbook, description: LogbookSensorDescription) -> None:
        """Initialise."""
        super().__init__(vehicle, description.key)
        self.entity_description = description
        if description.money:
            self._attr_native_unit_of_measurement = (
                f"{vehicle.hass.config.currency}{description.money_suffix}"
            )

    @property
    def native_value(self) -> Any:
        """Current value."""
        return self.entity_description.value_fn(self.vehicle.summary)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.vehicle.summary)
