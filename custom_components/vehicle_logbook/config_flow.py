"""Config flow: one config entry per vehicle."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DUE_SOON_DAYS,
    CONF_DUE_SOON_KM,
    CONF_FUEL_TYPE,
    CONF_INITIAL_ODOMETER,
    CONF_MAKE,
    CONF_MODEL,
    CONF_ODOMETER_ENTITY,
    CONF_OIL_INTERVAL_KM,
    CONF_OIL_INTERVAL_MONTHS,
    CONF_REGISTRATION,
    CONF_SERVICE_INTERVAL_KM,
    CONF_SERVICE_INTERVAL_MONTHS,
    CONF_TANK_CAPACITY,
    CONF_TYRE_MAX_AGE_YEARS,
    CONF_TYRE_MAX_KM,
    CONF_TYRE_ROTATION_KM,
    CONF_YEAR,
    DEFAULT_OPTIONS,
    DOMAIN,
    FUEL_TYPES,
)

CONF_NAME = "name"


def _number(minimum: float, maximum: float, step: float = 1, unit: str | None = None) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


ODOMETER_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor")
)


def _options_schema(current: dict[str, Any]) -> vol.Schema:
    def opt(key: str) -> dict[str, Any]:
        return {"default": current.get(key, DEFAULT_OPTIONS.get(key))}

    odometer = current.get(CONF_ODOMETER_ENTITY)
    return vol.Schema(
        {
            vol.Optional(
                CONF_ODOMETER_ENTITY,
                description={"suggested_value": odometer} if odometer else None,
            ): ODOMETER_SELECTOR,
            vol.Required(CONF_SERVICE_INTERVAL_KM, **opt(CONF_SERVICE_INTERVAL_KM)): _number(1000, 100000, 500, "km"),
            vol.Required(CONF_SERVICE_INTERVAL_MONTHS, **opt(CONF_SERVICE_INTERVAL_MONTHS)): _number(1, 60, 1, "months"),
            vol.Required(CONF_OIL_INTERVAL_KM, **opt(CONF_OIL_INTERVAL_KM)): _number(1000, 100000, 500, "km"),
            vol.Required(CONF_OIL_INTERVAL_MONTHS, **opt(CONF_OIL_INTERVAL_MONTHS)): _number(1, 60, 1, "months"),
            vol.Required(CONF_TYRE_ROTATION_KM, **opt(CONF_TYRE_ROTATION_KM)): _number(1000, 50000, 500, "km"),
            vol.Required(CONF_TYRE_MAX_KM, **opt(CONF_TYRE_MAX_KM)): _number(5000, 200000, 1000, "km"),
            vol.Required(CONF_TYRE_MAX_AGE_YEARS, **opt(CONF_TYRE_MAX_AGE_YEARS)): _number(1, 10, 1, "years"),
            vol.Required(CONF_DUE_SOON_KM, **opt(CONF_DUE_SOON_KM)): _number(0, 10000, 100, "km"),
            vol.Required(CONF_DUE_SOON_DAYS, **opt(CONF_DUE_SOON_DAYS)): _number(0, 180, 1, "days"),
        }
    )


def _clean_options(user_input: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    for key, value in user_input.items():
        if key == CONF_ODOMETER_ENTITY:
            if value:
                options[key] = value
            continue
        options[key] = int(value)
    return options


class VehicleLogbookConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a vehicle."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise."""
        self._vehicle: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Vehicle details."""
        errors: dict[str, str] = {}
        if user_input is not None:
            registration = (user_input.get(CONF_REGISTRATION) or "").strip().upper()
            if registration:
                await self.async_set_unique_id(registration.replace(" ", ""))
                self._abort_if_unique_id_configured()
            name = user_input.pop(CONF_NAME).strip()
            self._vehicle = {"title": name, "data": {**user_input, CONF_REGISTRATION: registration}}
            if not name:
                errors[CONF_NAME] = "name_required"
            else:
                return await self.async_step_maintenance()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Optional(CONF_MAKE): selector.TextSelector(),
                vol.Optional(CONF_MODEL): selector.TextSelector(),
                vol.Optional(CONF_YEAR): _number(1950, 2100),
                vol.Optional(CONF_REGISTRATION): selector.TextSelector(),
                vol.Required(CONF_FUEL_TYPE, default="petrol"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=FUEL_TYPES, translation_key="fuel_type")
                ),
                vol.Optional(CONF_TANK_CAPACITY): _number(1, 300, 1, "L"),
                vol.Optional(CONF_INITIAL_ODOMETER): _number(0, 5_000_000, 1, "km"),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_maintenance(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Odometer link and maintenance intervals."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._vehicle["title"],
                data=self._vehicle["data"],
                options=_clean_options(user_input),
            )
        return self.async_show_form(
            step_id="maintenance", data_schema=_options_schema(dict(DEFAULT_OPTIONS))
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> VehicleLogbookOptionsFlow:
        """Options."""
        return VehicleLogbookOptionsFlow()


class VehicleLogbookOptionsFlow(OptionsFlow):
    """Change odometer link and intervals."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(data=_clean_options(user_input))
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema({**DEFAULT_OPTIONS, **self.config_entry.options}),
        )
