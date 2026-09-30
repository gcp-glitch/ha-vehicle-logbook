"""Pure calculation tests."""

from datetime import date

from custom_components.vehicle_logbook import logbook
from custom_components.vehicle_logbook.const import DEFAULT_OPTIONS

TODAY = date(2026, 3, 10)


def test_add_months_clamps() -> None:
    assert logbook.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert logbook.add_months(date(2025, 11, 15), 14) == date(2027, 1, 15)


def test_parse_date_variants() -> None:
    assert logbook.parse_date("2026-09-12 11:58") == date(2026, 9, 12)
    assert logbook.parse_date("12/09/2026") == date(2026, 9, 12)
    assert logbook.parse_date("") is None


def test_fuel_full_to_full() -> None:
    fills = [
        {"date": "2026-01-01", "odometer": 1000, "litres": 50, "total_cost": 1000, "full_tank": True},
        {"date": "2026-01-05", "odometer": 1300, "litres": 20, "total_cost": 400, "full_tank": False},
        {"date": "2026-01-10", "odometer": 1500, "litres": 30, "total_cost": 600, "full_tank": True},
    ]
    stats = logbook.fuel_stats(fills)
    assert stats.avg_consumption == 10.0  # 50 L over 500 km
    assert stats.last_consumption == 10.0
    assert stats.cost_per_km == 2.0  # R1000 after the first fill over 500 km


def test_suspect_fillup_excluded() -> None:
    data = logbook.empty_data()
    fuelio = (
        "\"## Log\"\n\"Data\",\"Odo (km)\",\"Fuel (litres)\",\"Full\",\"Price (optional)\",\"VolumePrice\",\"UniqueId\"\n"
        "\"2026-01-01\",\"1000\",\"50\",\"1\",\"1000\",\"20\",\"1\"\n"
        "\"2026-01-10\",\"1500\",\"500\",\"1\",\"0\",\"0\",\"2\"\n"
        "\"2026-01-20\",\"2000\",\"50\",\"1\",\"1000\",\"20\",\"3\"\n"
    )
    added = logbook.merge_import(data, logbook.parse_fuelio_csv(fuelio))
    assert added["fillups"] == 3
    stats = logbook.fuel_stats(data["fillups"])
    assert stats.suspect_count == 1
    assert stats.avg_consumption == 10.0  # only the 1500 -> 2000 segment counts


def test_service_due_by_km_and_date() -> None:
    data = logbook.empty_data()
    data["services"].append({"id": "a", "date": "2025-04-01", "odometer": 10000})
    items = {i.key: i for i in logbook.due_items(data, dict(DEFAULT_OPTIONS), 24500, TODAY)}
    service = items["service"]
    assert service.due_km == 25000
    assert service.km_remaining == 500
    assert service.due_date == date(2026, 4, 1)
    assert service.status == "due_soon"  # within 1000 km and 30 days
    # oil comes from the service (includes_oil_change defaults to True)
    assert items["oil_change"].due_km == 25000


def test_overdue_and_workshop_override() -> None:
    data = logbook.empty_data()
    data["services"].append(
        {"id": "a", "date": "2026-01-01", "odometer": 10000, "next_service_km": 12000}
    )
    items = {i.key: i for i in logbook.due_items(data, dict(DEFAULT_OPTIONS), 12100, TODAY)}
    assert items["service"].status == "overdue"


def test_documents_and_tyres() -> None:
    data = logbook.empty_data()
    data["documents"].append({"id": "d", "document": "licence_disc", "expiry_date": "2026-03-31"})
    data["tyres"].append(
        {"id": "t", "date": "2025-06-01", "odometer": 5000, "action": "new_set", "dot_date": "2021-03-01"}
    )
    items = {i.key: i for i in logbook.due_items(data, dict(DEFAULT_OPTIONS), 16000, TODAY)}
    assert items["licence_disc"].status == "due_soon"
    assert items["licence_disc"].days_remaining == 21
    assert items["tyres"].due_date == date(2026, 3, 1)  # 5 years from DOT date
    assert items["tyres"].status == "overdue"
    assert items["tyre_rotation"].status == "overdue"  # 11000 km since fitting
    assert items["battery"].status == "unknown"


def test_fuelio_sample_import(fuelio_csv: str) -> None:
    imported = logbook.parse_fuelio_csv(fuelio_csv)
    assert len(imported["fillups"]) == 4
    assert [f["date"] for f in imported["fillups"] if f["suspect"]] == ["2026-02-15"]
    assert len(imported["services"]) == 1
    assert imported["expenses"][0]["category"] == "tolls"
    data = logbook.empty_data()
    logbook.merge_import(data, imported)
    again = logbook.merge_import(data, logbook.parse_fuelio_csv(fuelio_csv))
    assert sum(again.values()) == 0
    summary = logbook.summarize(data, dict(DEFAULT_OPTIONS), None, None, TODAY)
    assert summary["odometer"] == 11000
    assert summary["fuel"].avg_consumption == 10.0  # 60 L / 600 km; typo segment skipped
    assert summary["items"]["service"].due_km == 25200


def test_km_per_day_and_estimate() -> None:
    data = logbook.empty_data()
    logbook.record_odometer(data, 10000, date(2026, 2, 8), "sensor")
    logbook.record_odometer(data, 11000, date(2026, 3, 10), "sensor")
    assert round(logbook.km_per_day(data, TODAY), 1) == 33.3
    data["services"].append({"id": "s", "date": "2026-03-10", "odometer": 10000})
    items = {i.key: i for i in logbook.due_items(data, dict(DEFAULT_OPTIONS), 11000, TODAY)}
    # 14 000 km to go at ~33 km/day -> ~420 days, but the 12-month date is sooner
    assert items["service"].effective_date == date(2027, 3, 10)


def test_monthly_costs_and_km(fuelio_csv: str) -> None:
    data = logbook.empty_data()
    logbook.merge_import(data, logbook.parse_fuelio_csv(fuelio_csv))
    months = {m["month"]: m for m in logbook.monthly_costs(data)}
    assert months["2026-02"]["fuel"] == 1200.0  # suspect 0-cost fill-up ignored
    assert months["2026-02"]["maintenance"] == 3500.0
    assert months["2026-02"]["other"] == 65.0
    assert months["2026-03"]["total"] == 1400.0
    km = {m["month"]: m["km"] for m in logbook.monthly_km(data)}
    # 9400 km (15 Jan) -> 11000 km (1 Mar) spread evenly over the days in between
    assert set(km) == {"2026-01", "2026-02", "2026-03"}
    assert sum(km.values()) == 1600.0
    stats = logbook.fuel_stats(data["fillups"])
    assert [p["price_per_litre"] for p in stats.price_history] == [20.0, 20.0, 20.0]
