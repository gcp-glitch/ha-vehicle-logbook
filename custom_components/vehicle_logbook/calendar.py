"""Calendar with upcoming due dates and past workshop visits."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import STATUS_UNKNOWN
from .coordinator import VehicleLogbook, VehicleLogbookConfigEntry
from .entity import VehicleLogbookEntity
from .logbook import parse_date

# Past records shown on the calendar (fill-ups are left out to keep it readable).
HISTORY_LISTS = {
    "services": "Service",
    "oil_changes": "Oil change",
    "tyres": "Tyres",
    "parts": "Part replaced",
    "expenses": "Expense",
}


def _pretty(key: str) -> str:
    return key.replace("_", " ").capitalize()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VehicleLogbookConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendar."""
    async_add_entities([VehicleCareCalendar(entry.runtime_data)])


class VehicleCareCalendar(VehicleLogbookEntity, CalendarEntity):
    """Due dates (actual or estimated from km) plus logged workshop history."""

    _attr_translation_key = "vehicle_care"

    def __init__(self, vehicle: VehicleLogbook) -> None:
        """Initialise."""
        super().__init__(vehicle, "vehicle_care")

    def _events(self) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        name = self.vehicle.name
        for item in self.vehicle.summary.get("items", {}).values():
            when = item.effective_date
            if item.status == STATUS_UNKNOWN or when is None:
                continue
            estimated = item.due_date is None or (
                item.estimated_date is not None and item.estimated_date < item.due_date
            )
            detail = []
            if item.due_km is not None:
                detail.append(f"Due at {item.due_km:,.0f} km ({item.km_remaining:,.0f} km to go)")
            if item.due_date is not None:
                detail.append(f"Due by {item.due_date.isoformat()}")
            if estimated and item.estimated_date is not None:
                detail.append("Date estimated from your recent driving")
            events.append(
                CalendarEvent(
                    start=when,
                    end=when + timedelta(days=1),
                    summary=f"{name}: {_pretty(item.key)} due",
                    description="\n".join(detail),
                    uid=f"{self.vehicle.entry.entry_id}-due-{item.key}",
                )
            )
        data = self.vehicle.data
        for list_name, label in HISTORY_LISTS.items():
            for record in data.get(list_name, []):
                day = parse_date(record.get("date"))
                if day is None:
                    continue
                what = record.get("part") or record.get("action") or record.get("category") or ""
                cost = record.get("cost", record.get("amount"))
                summary = f"{name}: {label}{' - ' + _pretty(what) if what else ''}"
                description = "\n".join(
                    x for x in (
                        f"Odometer {record['odometer']:,.0f} km" if record.get("odometer") else "",
                        f"Cost {cost:,.2f}" if cost else "",
                        record.get("workshop") or "",
                        record.get("notes") or "",
                    ) if x
                )
                events.append(
                    CalendarEvent(
                        start=day, end=day + timedelta(days=1), summary=summary,
                        description=description, uid=f"{self.vehicle.entry.entry_id}-{record.get('id')}",
                    )
                )
        return sorted(events, key=lambda e: e.start)

    @property
    def event(self) -> CalendarEvent | None:
        """Next upcoming due date."""
        today = self.vehicle.today
        upcoming = [e for e in self._events() if e.start >= today and e.summary.endswith(" due")]
        overdue = [e for e in self._events() if e.start < today and e.summary.endswith(" due")]
        if overdue:
            return overdue[0]
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Events in range."""
        start: date = start_date.date()
        end: date = end_date.date()
        return [e for e in self._events() if e.end > start and e.start <= end]
