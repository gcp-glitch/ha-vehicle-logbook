"""Config flow, services and entities running inside Home Assistant."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.vehicle_logbook.const import DEFAULT_OPTIONS, DOMAIN
from custom_components.vehicle_logbook.diagnostics import async_get_config_entry_diagnostics

TODAY = date(2026, 3, 10)


@pytest.fixture(autouse=True)
def fixed_today():
    """Freeze the vehicle's notion of today."""
    with patch(
        "custom_components.vehicle_logbook.coordinator.VehicleLogbook.today",
        new=property(lambda self: TODAY),
    ):
        yield


async def _setup(hass: HomeAssistant, **options) -> MockConfigEntry:
    hass.config.currency = "ZAR"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Ranger",
        data={"make": "Ford", "model": "Ranger", "year": 2024, "registration": "AB12CDGP",
              "fuel_type": "diesel"},
        options={**DEFAULT_OPTIONS, **options},
        unique_id="AB12CDGP",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _eid(hass: HomeAssistant, entry: MockConfigEntry, key: str, domain: str = "sensor") -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, key
    return entity_id


async def test_config_flow_creates_vehicle(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Nadia's car", "registration": "xy 12 zz gp", "fuel_type": "petrol",
         "initial_odometer": 45000},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "maintenance"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**DEFAULT_OPTIONS, "service_interval_km": 10000}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Nadia's car"
    assert result["data"]["registration"] == "XY 12 ZZ GP"
    assert result["options"]["service_interval_km"] == 10000
    await hass.async_block_till_done()

    # Same registration cannot be added twice
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Dup", "registration": "XY12ZZGP", "fuel_type": "petrol"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**DEFAULT_OPTIONS, "due_soon_days": 45}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["due_soon_days"] == 45


async def test_logging_updates_entities(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    vid = entry.entry_id

    await hass.services.async_call(
        DOMAIN, "log_fillup",
        {"vehicle": vid, "date": "2026-02-01", "odometer": 10000, "litres": 60, "total_cost": 1200},
        blocking=True,
    )
    resp = await hass.services.async_call(
        DOMAIN, "log_fillup",
        {"vehicle": vid, "date": "2026-03-01", "odometer": 10600, "litres": 60,
         "price_per_litre": 21.5},
        blocking=True, return_response=True,
    )
    assert resp["record"]["total_cost"] == 1290.0
    await hass.async_block_till_done()

    assert hass.states.get(_eid(hass, entry, "odometer")).state == "10600.0"
    assert hass.states.get(_eid(hass, entry, "fuel_consumption")).state == "10.0"
    assert hass.states.get(_eid(hass, entry, "fuel_cost_per_km")).attributes[
        "unit_of_measurement"] == "ZAR/km"
    assert hass.states.get(_eid(hass, entry, "fuel_spend_this_month")).state == "1290.0"

    # service -> service/oil due status and next due
    await hass.services.async_call(
        DOMAIN, "log_service",
        {"vehicle": vid, "date": "2025-03-20", "odometer": 1000, "cost": 3500,
         "workshop": "Ford dealer"},
        blocking=True,
    )
    await hass.async_block_till_done()
    service = hass.states.get(_eid(hass, entry, "service_status"))
    assert service.state == "due_soon"  # 12 months after 2025-03-20 is within 30 days
    assert service.attributes["due_km"] == 16000
    assert hass.states.get(_eid(hass, entry, "service_due_date")).state == "2026-03-20"
    assert float(hass.states.get(_eid(hass, entry, "service_due_in")).state) == 5400
    assert hass.states.get(_eid(hass, entry, "needs_attention", "binary_sensor")).state == "on"
    assert hass.states.get(_eid(hass, entry, "next_due")).state in ("service", "oil_change")

    # document + part + expense
    await hass.services.async_call(
        DOMAIN, "set_document",
        {"vehicle": vid, "document": "licence_disc", "expiry_date": "2026-12-31", "cost": 650},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "log_part", {"vehicle": vid, "part": "battery", "cost": 2400}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "log_expense", {"vehicle": vid, "category": "tolls", "amount": 65}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, entry, "licence_disc_status")).state == "ok"
    battery = hass.states.get(_eid(hass, entry, "battery_status"))
    assert battery.state == "ok"
    assert battery.attributes["due_date"] == "2029-03-10"
    assert battery.attributes["last_km"] == 10600  # defaulted to current odometer

    records = await hass.services.async_call(
        DOMAIN, "get_records", {"vehicle": vid, "record_type": "fillups"},
        blocking=True, return_response=True,
    )
    newest = records["records"]["fillups"][0]
    assert newest["odometer"] == 10600

    # fix a typo, then delete
    await hass.services.async_call(
        DOMAIN, "update_record",
        {"vehicle": vid, "record_id": newest["id"], "changes": {"litres": 54}},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, entry, "fuel_consumption")).state == "9.0"
    await hass.services.async_call(
        DOMAIN, "delete_record", {"vehicle": vid, "record_id": newest["id"]}, blocking=True
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "delete_record", {"vehicle": vid, "record_id": "nope"}, blocking=True
        )


async def test_fillup_needs_odometer_and_price(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "log_fillup", {"vehicle": entry.entry_id, "litres": 50, "total_cost": 900},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "log_fillup",
            {"vehicle": entry.entry_id, "litres": 50, "odometer": 1000}, blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "log_fillup",
            {"vehicle": "not-a-vehicle", "litres": 50, "odometer": 1, "total_cost": 1},
            blocking=True,
        )


async def test_linked_odometer_sensor(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.ford_odometer", "20000", {"unit_of_measurement": "km"})
    entry = await _setup(hass, odometer_entity="sensor.ford_odometer")
    odo = _eid(hass, entry, "odometer")
    assert hass.states.get(odo).state == "20000.0"
    hass.states.async_set("sensor.ford_odometer", "20150", {"unit_of_measurement": "km"})
    await hass.async_block_till_done()
    assert hass.states.get(odo).state == "20150.0"
    hass.states.async_set("sensor.ford_odometer", "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(odo).state == "20150.0"

    # With a linked odometer the fill-up odometer is optional
    resp = await hass.services.async_call(
        DOMAIN, "log_fillup", {"vehicle": entry.entry_id, "litres": 40, "total_cost": 800},
        blocking=True, return_response=True,
    )
    assert resp["record"]["odometer"] == 20150.0


async def test_fuelio_import_service(hass: HomeAssistant, fuelio_csv: str) -> None:
    entry = await _setup(hass)
    resp = await hass.services.async_call(
        DOMAIN, "import_fuelio_csv", {"vehicle": entry.entry_id, "csv_data": fuelio_csv},
        blocking=True, return_response=True,
    )
    assert resp["added"]["fillups"] == 4
    assert resp["suspect_fillups"][0]["litres"] == 700.0
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, entry, "fuel_consumption")).state == "10.0"
    resp = await hass.services.async_call(
        DOMAIN, "import_fuelio_csv", {"vehicle": entry.entry_id, "csv_data": fuelio_csv},
        blocking=True, return_response=True,
    )
    assert sum(resp["added"].values()) == 0

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "import_fuelio_csv", {"vehicle": entry.entry_id, "path": "../etc/passwd"},
            blocking=True,
        )


async def test_data_survives_reload(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "set_odometer", {"vehicle": entry.entry_id, "odometer": 33333}, blocking=True
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, entry, "odometer")).state == "33333.0"


async def test_calendar_events(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    await hass.services.async_call(
        DOMAIN, "set_document",
        {"vehicle": entry.entry_id, "document": "insurance", "expiry_date": "2026-04-01"},
        blocking=True,
    )
    await hass.async_block_till_done()
    cal = _eid(hass, entry, "vehicle_care", "calendar")
    state = hass.states.get(cal)
    assert state.attributes["message"] == "Test Ranger: Insurance due"
    resp = await hass.services.async_call(
        "calendar", "get_events",
        {"start_date_time": "2026-03-01 00:00:00", "end_date_time": "2026-05-01 00:00:00"},
        target={"entity_id": cal}, blocking=True, return_response=True,
    )
    assert [e["summary"] for e in resp[cal]["events"]] == ["Test Ranger: Insurance due"]


async def test_diagnostics_redacts(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["data"]["registration"] == "**REDACTED**"
