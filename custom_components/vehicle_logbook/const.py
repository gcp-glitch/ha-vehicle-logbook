"""Constants for the Vehicle Logbook integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "vehicle_logbook"
STORAGE_VERSION: Final = 1

# Config entry data (vehicle details)
CONF_MAKE: Final = "make"
CONF_MODEL: Final = "model"
CONF_YEAR: Final = "year"
CONF_REGISTRATION: Final = "registration"
CONF_FUEL_TYPE: Final = "fuel_type"
CONF_TANK_CAPACITY: Final = "tank_capacity"
CONF_INITIAL_ODOMETER: Final = "initial_odometer"

# Options
CONF_ODOMETER_ENTITY: Final = "odometer_entity"
CONF_SERVICE_INTERVAL_KM: Final = "service_interval_km"
CONF_SERVICE_INTERVAL_MONTHS: Final = "service_interval_months"
CONF_OIL_INTERVAL_KM: Final = "oil_interval_km"
CONF_OIL_INTERVAL_MONTHS: Final = "oil_interval_months"
CONF_TYRE_ROTATION_KM: Final = "tyre_rotation_km"
CONF_TYRE_MAX_KM: Final = "tyre_max_km"
CONF_TYRE_MAX_AGE_YEARS: Final = "tyre_max_age_years"
CONF_DUE_SOON_KM: Final = "due_soon_km"
CONF_DUE_SOON_DAYS: Final = "due_soon_days"

DEFAULT_OPTIONS: Final = {
    CONF_SERVICE_INTERVAL_KM: 15000,
    CONF_SERVICE_INTERVAL_MONTHS: 12,
    CONF_OIL_INTERVAL_KM: 15000,
    CONF_OIL_INTERVAL_MONTHS: 12,
    CONF_TYRE_ROTATION_KM: 10000,
    CONF_TYRE_MAX_KM: 60000,
    CONF_TYRE_MAX_AGE_YEARS: 5,
    CONF_DUE_SOON_KM: 1000,
    CONF_DUE_SOON_DAYS: 30,
}

FUEL_TYPES: Final = ["petrol", "diesel", "hybrid", "lpg"]

# Parts: key -> (default interval km, default interval months). None = not used.
PARTS: Final[dict[str, tuple[int | None, int | None]]] = {
    "battery": (None, 36),
    "brake_pads": (40000, None),
    "brake_discs": (80000, None),
    "brake_fluid": (None, 24),
    "wiper_blades": (None, 12),
    "air_filter": (30000, 24),
    "cabin_filter": (15000, 12),
    "fuel_filter": (30000, 24),
    "coolant": (60000, 48),
    "spark_plugs": (60000, None),
    "timing_belt": (100000, 60),
    "shock_absorbers": (80000, None),
    "clutch": (None, None),
    "other": (None, None),
}
# Parts that get their own status sensor (all parts are always in the due list and calendar).
SENSOR_PARTS: Final = [
    "battery",
    "brake_pads",
    "brake_fluid",
    "wiper_blades",
    "air_filter",
    "cabin_filter",
]

DOCUMENTS: Final = [
    "licence_disc",
    "insurance",
    "roadworthy",
    "warranty",
    "service_plan",
    "tracker",
]
SENSOR_DOCUMENTS: Final = ["licence_disc", "insurance", "service_plan", "warranty"]

EXPENSE_CATEGORIES: Final = [
    "insurance",
    "licence",
    "finance",
    "tolls",
    "parking",
    "wash",
    "repair",
    "accessories",
    "fine",
    "other",
]

TYRE_ACTIONS: Final = ["new_set", "rotation", "repair", "tread_check"]
SERVICE_TYPES: Final = ["minor", "major", "other"]

# Maintenance item keys (besides parts and documents)
ITEM_SERVICE: Final = "service"
ITEM_OIL: Final = "oil_change"
ITEM_TYRE_ROTATION: Final = "tyre_rotation"
ITEM_TYRES: Final = "tyres"

STATUS_OK: Final = "ok"
STATUS_DUE_SOON: Final = "due_soon"
STATUS_OVERDUE: Final = "overdue"
STATUS_UNKNOWN: Final = "unknown"
STATUSES: Final = [STATUS_OK, STATUS_DUE_SOON, STATUS_OVERDUE, STATUS_UNKNOWN]

RECORD_LISTS: Final = [
    "fillups",
    "services",
    "oil_changes",
    "tyres",
    "parts",
    "documents",
    "expenses",
]

SIGNAL_UPDATED: Final = f"{DOMAIN}_updated_{{}}"
