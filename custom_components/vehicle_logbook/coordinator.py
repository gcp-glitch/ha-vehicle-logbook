"""Runtime state for one vehicle: storage, linked odometer and computed summary."""

from __future__ import annotations

import copy
from datetime import date
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import DistanceConverter

from . import logbook
from .const import (
    CONF_INITIAL_ODOMETER,
    CONF_ODOMETER_ENTITY,
    DEFAULT_OPTIONS,
    DOMAIN,
    SIGNAL_UPDATED,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

type VehicleLogbookConfigEntry = ConfigEntry[VehicleLogbook]

SAVE_DELAY = 30


class VehicleLogbook:
    """Holds one vehicle's logbook and keeps its summary up to date."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.data: dict[str, Any] = logbook.empty_data()
        self.linked_odometer: float | None = None
        self.summary: dict[str, Any] = {}

    @property
    def options(self) -> dict[str, Any]:
        """Options merged over defaults."""
        return {**DEFAULT_OPTIONS, **self.entry.options}

    @property
    def name(self) -> str:
        """Vehicle name."""
        return self.entry.title

    @property
    def signal(self) -> str:
        """Dispatcher signal for this vehicle."""
        return SIGNAL_UPDATED.format(self.entry.entry_id)

    async def async_setup(self) -> None:
        """Load storage and start listeners."""
        stored = await self._store.async_load()
        if stored:
            base = logbook.empty_data()
            base.update(stored)
            self.data = base
        entity_id = self.options.get(CONF_ODOMETER_ENTITY)
        if entity_id:
            self._read_linked(self.hass.states.get(entity_id))
            self.entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, [entity_id], self._handle_odometer_event
                )
            )
        # Date-based items change status at midnight.
        self.entry.async_on_unload(
            async_track_time_change(self.hass, self._handle_midnight, hour=0, minute=0, second=5)
        )
        self.refresh(notify=False)

    @callback
    def _read_linked(self, state: Any) -> bool:
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
            return False
        try:
            value = float(state.state)
        except ValueError:
            return False
        unit = state.attributes.get("unit_of_measurement")
        if unit and unit != "km":
            try:
                value = DistanceConverter.convert(value, unit, "km")
            except Exception:  # noqa: BLE001 - unknown unit, use raw value
                _LOGGER.debug("Unknown odometer unit %s", unit)
        value = round(value, 1)
        if value <= 0 or value == self.linked_odometer:
            return False
        self.linked_odometer = value
        if logbook.record_odometer(self.data, value, self.today, "sensor"):
            self._store.async_delay_save(lambda: self.data, SAVE_DELAY)
        return True

    @callback
    def _handle_odometer_event(self, event: Event[EventStateChangedData]) -> None:
        if self._read_linked(event.data["new_state"]):
            self.refresh()

    @callback
    def _handle_midnight(self, _now: Any) -> None:
        self.refresh()

    @property
    def today(self) -> date:
        """Local date."""
        return dt_util.now().date()

    @property
    def odometer(self) -> float | None:
        """Current odometer."""
        return self.summary.get("odometer")

    @callback
    def refresh(self, notify: bool = True) -> None:
        """Recompute the summary and tell the entities."""
        self.summary = logbook.summarize(
            self.data,
            self.options,
            self.entry.data.get(CONF_INITIAL_ODOMETER),
            self.linked_odometer,
            self.today,
        )
        if notify:
            async_dispatcher_send(self.hass, self.signal)

    async def async_commit(self) -> None:
        """Save now and refresh."""
        await self._store.async_save(self.data)
        self.refresh()

    # ------------------------------------------------------------------ mutations

    async def async_add(self, list_name: str, record: dict[str, Any]) -> dict[str, Any]:
        """Add a record to one of the lists."""
        record = {"id": logbook.new_id(), **{k: v for k, v in record.items() if v is not None}}
        self.data.setdefault(list_name, []).append(record)
        await self.async_commit()
        return record

    async def async_set_odometer(self, km: float, when: date) -> None:
        """Manual odometer reading."""
        logbook.record_odometer(self.data, km, when, "manual")
        await self.async_commit()

    async def async_delete(self, record_id: str) -> dict[str, Any] | None:
        """Delete a record by id from whichever list holds it."""
        for name in logbook.RECORD_LISTS:
            records = self.data.get(name, [])
            for index, record in enumerate(records):
                if record.get("id") == record_id:
                    removed = records.pop(index)
                    await self.async_commit()
                    return {"list": name, **removed}
        return None

    async def async_update(self, record_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Update fields of a record (e.g. fix a typo)."""
        for name in logbook.RECORD_LISTS:
            for record in self.data.get(name, []):
                if record.get("id") == record_id:
                    record.update({k: v for k, v in changes.items() if v is not None})
                    if "litres" in changes or "total_cost" in changes:
                        # A corrected fill-up counts in the stats again.
                        record.pop("suspect", None)
                    await self.async_commit()
                    return {"list": name, **record}
        return None

    async def async_import(self, imported: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        """Merge imported records."""
        added = logbook.merge_import(self.data, imported)
        await self.async_commit()
        return added

    def export(self) -> dict[str, Any]:
        """Deep copy of the stored data."""
        return copy.deepcopy(self.data)
