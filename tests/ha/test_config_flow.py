"""Config, reauth and options flows."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from saic_ismart_client_ng.api.vehicle.schema import VehicleListResp, VinInfo
from saic_ismart_client_ng.exceptions import SaicApiException

from custom_components.mg5.const import CONF_BATTERY, CONF_VIN, DOMAIN

from .conftest import MG4_VIN, VIN

USER_INPUT = {
    "account_type": "email",
    "username": " driver@example.com ",
    "password": "not-a-real-password",
    "region": "eu",
    "country_code": "",
    "battery_pack": "standard",
}


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_only_the_mg5_is_offered(hass: HomeAssistant, saic) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "vehicle"
    choices = result["data_schema"].schema[CONF_VIN].container
    assert list(choices) == [VIN]
    assert MG4_VIN not in choices

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VIN: VIN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["username"] == "driver@example.com"
    assert result["data"]["vin"] == VIN
    assert result["options"] == {CONF_BATTERY: "standard"}
    saic.close.assert_awaited()
    await hass.async_block_till_done()


async def test_account_without_mg5_aborts(hass: HomeAssistant, saic) -> None:
    saic.vehicle_list.return_value = VehicleListResp(
        vinList=[VinInfo(vin=MG4_VIN, modelName="MG4 Electric", series="EH32")]
    )
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_mg5"


async def test_wrong_password_and_no_network_are_different(hass: HomeAssistant, saic) -> None:
    saic.is_logged_in = False
    saic.login.side_effect = SaicApiException(
        "Failed to get an access token, please check your credentials"
    )
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "invalid_auth"}

    saic.login.side_effect = SaicApiException(
        "API call POST /oauth/token failed unexpectedly", return_code=500
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_phone_needs_country_code(hass: HomeAssistant, saic) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**USER_INPUT, "account_type": "phone", "username": "040 123 4567"},
    )
    assert result["errors"] == {"base": "country_code"}
    saic.vehicle_list.assert_not_awaited()


async def test_same_car_twice_aborts(hass: HomeAssistant, saic, entry) -> None:
    entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VIN: VIN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_change_battery_and_reload(hass: HomeAssistant, saic, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_BATTERY: "standard"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_BATTERY] == "standard"
    assert entry.state is config_entries.ConfigEntryState.LOADED
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.pack == "standard"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_reauth_updates_password(hass: HomeAssistant, saic, entry) -> None:
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-password"
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
