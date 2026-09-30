"""Actions (services) for logging vehicle records."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import logbook
from .const import (
    DOCUMENTS,
    DOMAIN,
    EXPENSE_CATEGORIES,
    PARTS,
    RECORD_LISTS,
    SERVICE_TYPES,
    TYRE_ACTIONS,
)
from .coordinator import VehicleLogbook

ATTR_VEHICLE = "vehicle"
MAX_CSV_BYTES = 5_000_000

_POSITIVE = vol.All(vol.Coerce(float), vol.Range(min=0))
_KM = vol.All(vol.Coerce(float), vol.Range(min=0, max=5_000_000))

BASE = {
    vol.Required(ATTR_VEHICLE): cv.string,
    vol.Optional("date"): cv.date,
    vol.Optional("odometer"): _KM,
    vol.Optional("notes"): cv.string,
}

SCHEMAS: dict[str, vol.Schema] = {
    "log_fillup": vol.Schema(
        {
            **BASE,
            vol.Required("litres"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1000)),
            vol.Optional("total_cost"): _POSITIVE,
            vol.Optional("price_per_litre"): _POSITIVE,
            vol.Optional("full_tank", default=True): cv.boolean,
            vol.Optional("missed_previous", default=False): cv.boolean,
            vol.Optional("station"): cv.string,
        }
    ),
    "log_service": vol.Schema(
        {
            **BASE,
            vol.Optional("cost"): _POSITIVE,
            vol.Optional("service_type", default="minor"): vol.In(SERVICE_TYPES),
            vol.Optional("workshop"): cv.string,
            vol.Optional("includes_oil_change", default=True): cv.boolean,
            vol.Optional("next_service_km"): _KM,
            vol.Optional("next_service_date"): cv.date,
        }
    ),
    "log_oil_change": vol.Schema(
        {**BASE, vol.Optional("cost"): _POSITIVE, vol.Optional("oil"): cv.string}
    ),
    "log_tyres": vol.Schema(
        {
            **BASE,
            vol.Required("action"): vol.In(TYRE_ACTIONS),
            vol.Optional("cost"): _POSITIVE,
            vol.Optional("brand"): cv.string,
            vol.Optional("size"): cv.string,
            vol.Optional("tread_mm"): vol.All(vol.Coerce(float), vol.Range(min=0, max=30)),
            vol.Optional("dot_date"): cv.date,
        }
    ),
    "log_part": vol.Schema(
        {
            **BASE,
            vol.Required("part"): vol.In(list(PARTS)),
            vol.Optional("cost"): _POSITIVE,
            vol.Optional("interval_km"): _KM,
            vol.Optional("interval_months"): vol.All(vol.Coerce(int), vol.Range(min=0, max=240)),
        }
    ),
    "set_document": vol.Schema(
        {
            vol.Required(ATTR_VEHICLE): cv.string,
            vol.Required("document"): vol.In(DOCUMENTS),
            vol.Required("expiry_date"): cv.date,
            vol.Optional("date"): cv.date,
            vol.Optional("cost"): _POSITIVE,
            vol.Optional("reference"): cv.string,
            vol.Optional("notes"): cv.string,
        }
    ),
    "log_expense": vol.Schema(
        {
            **BASE,
            vol.Required("category"): vol.In(EXPENSE_CATEGORIES),
            vol.Required("amount"): _POSITIVE,
        }
    ),
    "set_odometer": vol.Schema(
        {
            vol.Required(ATTR_VEHICLE): cv.string,
            vol.Required("odometer"): _KM,
            vol.Optional("date"): cv.date,
        }
    ),
    "update_record": vol.Schema(
        {
            vol.Required(ATTR_VEHICLE): cv.string,
            vol.Required("record_id"): cv.string,
            vol.Required("changes"): dict,
        }
    ),
    "delete_record": vol.Schema(
        {vol.Required(ATTR_VEHICLE): cv.string, vol.Required("record_id"): cv.string}
    ),
    "import_fuelio_csv": vol.Schema(
        {
            vol.Required(ATTR_VEHICLE): cv.string,
            vol.Exclusive("path", "source"): cv.string,
            vol.Exclusive("csv_data", "source"): cv.string,
        }
    ),
    "get_records": vol.Schema(
        {
            vol.Required(ATTR_VEHICLE): cv.string,
            vol.Optional("record_type", default="all"): vol.In(["all", *RECORD_LISTS]),
            vol.Optional("limit", default=50): vol.All(vol.Coerce(int), vol.Range(min=1, max=5000)),
        }
    ),
}

# Which list each logging action writes to
LIST_FOR = {
    "log_fillup": "fillups",
    "log_service": "services",
    "log_oil_change": "oil_changes",
    "log_tyres": "tyres",
    "log_part": "parts",
    "set_document": "documents",
    "log_expense": "expenses",
}
UPDATABLE = {
    "date", "odometer", "notes", "litres", "total_cost", "price_per_litre", "full_tank",
    "missed_previous", "station", "cost", "service_type", "workshop", "includes_oil_change",
    "next_service_km", "next_service_date", "oil", "action", "brand", "size", "tread_mm",
    "dot_date", "part", "interval_km", "interval_months", "document", "expiry_date",
    "reference", "category", "amount",
}


def _vehicle(hass: HomeAssistant, entry_id: str) -> VehicleLogbook:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_vehicle",
            translation_placeholders={"vehicle": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="vehicle_not_loaded",
            translation_placeholders={"vehicle": entry.title},
        )
    return entry.runtime_data


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value


def _build_record(action: str, data: dict[str, Any], vehicle: VehicleLogbook) -> dict[str, Any]:
    record = {k: _jsonable(v) for k, v in data.items() if k != ATTR_VEHICLE}
    record.setdefault("date", vehicle.today.isoformat())
    if action == "set_document":
        return record
    if record.get("odometer") is None:
        if action == "log_fillup" and vehicle.linked_odometer is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="odometer_required"
            )
        if vehicle.odometer is not None:
            record["odometer"] = vehicle.odometer
    if action == "log_fillup":
        litres = record["litres"]
        total = record.get("total_cost")
        per_litre = record.get("price_per_litre")
        if total is None and per_litre is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="price_required"
            )
        if total is None:
            record["total_cost"] = round(per_litre * litres, 2)
        elif per_litre is None:
            record["price_per_litre"] = round(total / litres, 3)
        record["source"] = "manual"
    return record


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""

    async def handle_log(call: ServiceCall) -> ServiceResponse:
        vehicle = _vehicle(hass, call.data[ATTR_VEHICLE])
        record = _build_record(call.service, dict(call.data), vehicle)
        saved = await vehicle.async_add(LIST_FOR[call.service], record)
        return {"record": saved}

    async def handle_set_odometer(call: ServiceCall) -> None:
        vehicle = _vehicle(hass, call.data[ATTR_VEHICLE])
        await vehicle.async_set_odometer(
            call.data["odometer"], call.data.get("date") or vehicle.today
        )

    async def handle_update(call: ServiceCall) -> ServiceResponse:
        vehicle = _vehicle(hass, call.data[ATTR_VEHICLE])
        changes = call.data["changes"]
        unknown = set(changes) - UPDATABLE
        if unknown:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_fields",
                translation_placeholders={"fields": ", ".join(sorted(unknown))},
            )
        updated = await vehicle.async_update(call.data["record_id"], changes)
        if updated is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="record_not_found",
                translation_placeholders={"record_id": call.data["record_id"]},
            )
        return {"record": updated}

    async def handle_delete(call: ServiceCall) -> ServiceResponse:
        vehicle = _vehicle(hass, call.data[ATTR_VEHICLE])
        removed = await vehicle.async_delete(call.data["record_id"])
        if removed is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="record_not_found",
                translation_placeholders={"record_id": call.data["record_id"]},
            )
        return {"deleted": removed}

    async def handle_import(call: ServiceCall) -> ServiceResponse:
        vehicle = _vehicle(hass, call.data[ATTR_VEHICLE])
        text = call.data.get("csv_data")
        if text is None:
            if "path" not in call.data:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="import_source_required"
                )
            path = Path(hass.config.path(call.data["path"]))
            if not hass.config.is_allowed_path(str(path)) or not path.is_relative_to(
                hass.config.config_dir
            ):
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="path_not_allowed",
                    translation_placeholders={"path": call.data["path"]},
                )

            def _read() -> str:
                if not path.is_file() or path.stat().st_size > MAX_CSV_BYTES:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="file_not_found",
                        translation_placeholders={"path": call.data["path"]},
                    )
                return path.read_text(encoding="utf-8-sig", errors="replace")

            text = await hass.async_add_executor_job(_read)
        imported = logbook.parse_fuelio_csv(text)
        added = await vehicle.async_import(imported)
        suspect = [
            {"date": r["date"], "odometer": r["odometer"], "litres": r["litres"],
             "total_cost": r["total_cost"]}
            for r in imported["fillups"] if r.get("suspect")
        ]
        return {"added": added, "suspect_fillups": suspect}

    async def handle_get(call: ServiceCall) -> ServiceResponse:
        vehicle = _vehicle(hass, call.data[ATTR_VEHICLE])
        names = RECORD_LISTS if call.data["record_type"] == "all" else [call.data["record_type"]]
        limit = call.data["limit"]
        data = vehicle.export()
        result: dict[str, Any] = {}
        for name in names:
            records = sorted(data.get(name, []), key=logbook._sort_key, reverse=True)  # noqa: SLF001
            result[name] = records[:limit]
        return {"vehicle": vehicle.name, "odometer": vehicle.odometer, "records": result}

    for action in LIST_FOR:
        hass.services.async_register(
            DOMAIN, action, handle_log, schema=SCHEMAS[action],
            supports_response=SupportsResponse.OPTIONAL,
        )
    hass.services.async_register(
        DOMAIN, "set_odometer", handle_set_odometer, schema=SCHEMAS["set_odometer"]
    )
    hass.services.async_register(
        DOMAIN, "update_record", handle_update, schema=SCHEMAS["update_record"],
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "delete_record", handle_delete, schema=SCHEMAS["delete_record"],
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "import_fuelio_csv", handle_import, schema=SCHEMAS["import_fuelio_csv"],
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "get_records", handle_get, schema=SCHEMAS["get_records"],
        supports_response=SupportsResponse.ONLY,
    )
