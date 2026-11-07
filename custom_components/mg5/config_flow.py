"""Config flow for the MG5."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from saic_ismart_client_ng.exceptions import SaicApiException

from .api import VehicleInfo, is_connection_error, public_error
from .const import (
    ACCOUNT_EMAIL,
    ACCOUNT_PHONE,
    CONF_ACCOUNT_TYPE,
    CONF_BATTERY,
    CONF_COLOR,
    CONF_COUNTRY_CODE,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SERIES,
    CONF_USERNAME,
    CONF_VIN,
    CONF_YEAR,
    DEFAULT_BATTERY,
    DEFAULT_REGION,
    DOMAIN,
    PACK_LONG_RANGE,
    PACK_STANDARD,
    REGION_AU,
    REGION_EU,
    REGION_TR,
)
from .coordinator import async_create_client
from .profile import is_mg5

_LOGGER = logging.getLogger(__name__)

_PROBE_TIMEOUT = 90

_ACCOUNT_TYPES = {ACCOUNT_EMAIL: "Email", ACCOUNT_PHONE: "Phone"}
_REGIONS = {REGION_EU: "Europe", REGION_AU: "Australia and New Zealand", REGION_TR: "Türkiye"}
_PACKS = {
    PACK_LONG_RANGE: "Long Range, 61.1 kWh",
    PACK_STANDARD: "Standard Range, 50.3 kWh",
}


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_ACCOUNT_TYPE, default=defaults.get(CONF_ACCOUNT_TYPE, ACCOUNT_EMAIL)
            ): vol.In(_ACCOUNT_TYPES),
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_REGION, default=defaults.get(CONF_REGION, DEFAULT_REGION)): vol.In(
                _REGIONS
            ),
            vol.Optional(CONF_COUNTRY_CODE, default=defaults.get(CONF_COUNTRY_CODE, "")): str,
            vol.Required(
                CONF_BATTERY, default=defaults.get(CONF_BATTERY, DEFAULT_BATTERY)
            ): vol.In(_PACKS),
        }
    )


def _normalise(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    username = str(data[CONF_USERNAME]).strip()
    if data[CONF_ACCOUNT_TYPE] == ACCOUNT_PHONE:
        username = "".join(ch for ch in username if ch.isdigit())
    data[CONF_USERNAME] = username
    code = str(data.get(CONF_COUNTRY_CODE) or "").strip().removeprefix("+")
    data[CONF_COUNTRY_CODE] = code
    return data


def _validate(data: dict[str, Any]) -> str | None:
    if data[CONF_ACCOUNT_TYPE] == ACCOUNT_EMAIL and "@" not in data[CONF_USERNAME]:
        return "invalid_email"
    if data[CONF_ACCOUNT_TYPE] == ACCOUNT_PHONE:
        if not data[CONF_COUNTRY_CODE].isdigit():
            return "country_code"
        if not data[CONF_USERNAME]:
            return "invalid_phone"
    if not str(data.get(CONF_PASSWORD) or ""):
        return "invalid_auth"
    return None


async def _list_mg5(hass: HomeAssistant, data: dict[str, Any]) -> list[VehicleInfo]:
    client = await async_create_client(hass, data)
    try:
        vehicles = await asyncio.wait_for(client.list_vehicles(), _PROBE_TIMEOUT)
    finally:
        await client.close()
    return [car for car in vehicles if is_mg5(car.model_name, car.series)]


async def _probe(hass: HomeAssistant, data: dict[str, Any]) -> tuple[list[VehicleInfo], str | None]:
    """Sign in and list MG5s. Returns the cars and an error key."""
    try:
        return await _list_mg5(hass, data), None
    except TimeoutError:
        return [], "timeout"
    except SaicApiException as err:
        _LOGGER.warning("MG5 sign-in failed: %s", public_error(err))
        if is_connection_error(err):
            return [], "cannot_connect"
        return [], "invalid_auth"
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("MG5 sign-in failed: %s", public_error(err))
        return [], "cannot_connect"


class Mg5ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in, then pick the MG5 on the account."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._cars: list[VehicleInfo] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _normalise(user_input)
            error = _validate(data)
            if error is None:
                cars, error = await _probe(self.hass, data)
                if error is None:
                    if not cars:
                        return self.async_abort(reason="no_mg5")
                    self._data = data
                    self._cars = cars
                    return await self.async_step_vehicle()
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
        )

    async def async_step_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        choices = {car.vin: car.label for car in self._cars}
        if user_input is not None:
            vin = user_input[CONF_VIN]
            car = next(item for item in self._cars if item.vin == vin)
            await self.async_set_unique_id(vin)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=car.label,
                data={
                    CONF_ACCOUNT_TYPE: self._data[CONF_ACCOUNT_TYPE],
                    CONF_USERNAME: self._data[CONF_USERNAME],
                    CONF_PASSWORD: self._data[CONF_PASSWORD],
                    CONF_REGION: self._data[CONF_REGION],
                    CONF_COUNTRY_CODE: self._data.get(CONF_COUNTRY_CODE) or "",
                    CONF_VIN: vin,
                    CONF_MODEL: car.model_name,
                    CONF_YEAR: car.model_year,
                    CONF_SERIES: car.series,
                    CONF_COLOR: car.color,
                },
                options={CONF_BATTERY: self._data[CONF_BATTERY]},
            )
        return self.async_show_form(
            step_id="vehicle",
            data_schema=vol.Schema({vol.Required(CONF_VIN): vol.In(choices)}),
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = dict(entry.data)
            data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
            _cars, error = await _probe(self.hass, data)
            if error is None:
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> Mg5OptionsFlow:
        return Mg5OptionsFlow()


class Mg5OptionsFlow(OptionsFlow):
    """Change the battery pack without signing in again."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_BATTERY, DEFAULT_BATTERY)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_BATTERY, default=current): vol.In(_PACKS)}
            ),
        )
