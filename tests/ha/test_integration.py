"""The integration running inside Home Assistant."""

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)
from saic_ismart_client_ng.exceptions import SaicApiException

from custom_components.mg5.const import DOMAIN, EVENT_COMMAND_FAILED

from .conftest import VIN, cached_status, live_status


def _id(hass: HomeAssistant, domain: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{VIN}_{key}")
    assert entity_id, f"{domain} {key} was not created"
    return entity_id


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _skip(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_setup_reads_cached_then_one_live_read(hass: HomeAssistant, saic, entry) -> None:
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    saic.get_vehicle_status_cached.assert_awaited_once()
    saic.get_vehicle_status.assert_not_awaited()

    soc = _id(hass, "sensor", "soc")
    assert hass.states.get(soc).state == "unknown"

    await _skip(hass, 6)
    saic.get_vehicle_status.assert_awaited_once()
    assert hass.states.get(soc).state == "96.5"
    assert hass.states.get(_id(hass, "sensor", "battery_energy")).state == "58.96"
    assert hass.states.get(_id(hass, "sensor", "aux_voltage")).state == "13.7"
    assert hass.states.get(_id(hass, "sensor", "exterior_temperature")).state == "unknown"
    assert hass.states.get(_id(hass, "number", "charge_limit")).state == "80.0"
    assert hass.states.get(_id(hass, "lock", "lock")).state == "locked"
    tracker = hass.states.get(_id(hass, "device_tracker", "location"))
    assert tracker.attributes["latitude"] == 51.234567

    # Quiet car: the 30 s ticks must not wake it again.
    for _ in range(10):
        await _skip(hass, 31)
    assert saic.get_vehicle_status.await_count == 1

    await _unload(hass, entry)
    saic.close.assert_awaited()


async def test_only_supported_controls_exist(hass: HomeAssistant, saic, entry) -> None:
    await _setup(hass, entry)
    created = [
        item.unique_id
        for item in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    ]
    for word in ("seat", "window", "sunroof", "defrost", "steering", "heating", "fan"):
        assert not any(word in uid for uid in created), word
    for key in ("lock", "climate", "charge_limit", "charging_switch", "find_car", "refresh"):
        assert f"{VIN}_{key}" in created
    await _unload(hass, entry)


async def test_status_2_shows_heat_cool(hass: HomeAssistant, saic, entry) -> None:
    await _setup(hass, entry)
    state = hass.states.get(_id(hass, "climate", "climate"))
    assert state.state == "heat_cool"
    assert state.attributes["hvac_modes"] == ["off", "heat_cool"]
    assert "fan_modes" not in state.attributes
    await _unload(hass, entry)


async def test_climate_sends_the_mg5_command(hass: HomeAssistant, saic, entry) -> None:
    saic.get_vehicle_status_cached.return_value = cached_status(remoteClimateStatus=0)
    saic.get_vehicle_status.return_value = live_status(remoteClimateStatus=0)
    await _setup(hass, entry)
    climate = _id(hass, "climate", "climate")
    assert hass.states.get(climate).state == "off"

    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": climate, "temperature": 25}, blocking=True
    )
    await _skip(hass, 5)
    saic.control_climate.assert_not_awaited()
    assert hass.states.get(climate).attributes["temperature"] == 25

    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": climate, "hvac_mode": "heat_cool"}, blocking=True
    )
    saic.control_climate.assert_awaited_once_with(
        VIN, fan_speed=2, ac_on=None, temperature_idx=11
    )
    assert hass.states.get(climate).state == "heat_cool"

    await hass.services.async_call(
        "climate", "turn_off", {"entity_id": climate}, blocking=True
    )
    saic.stop_ac.assert_awaited_once_with(VIN)
    assert hass.states.get(climate).state == "off"
    await _unload(hass, entry)


async def test_slider_while_running_sends_one_command(hass: HomeAssistant, saic, entry) -> None:
    await _setup(hass, entry)
    climate = _id(hass, "climate", "climate")
    for temp in (23, 24, 26):
        await hass.services.async_call(
            "climate", "set_temperature", {"entity_id": climate, "temperature": temp}, blocking=True
        )
    saic.control_climate.assert_not_awaited()
    await _skip(hass, 4)
    saic.control_climate.assert_awaited_once_with(
        VIN, fan_speed=2, ac_on=None, temperature_idx=12
    )
    await _unload(hass, entry)


async def test_rejected_command_raises_and_fires_event(hass: HomeAssistant, saic, entry) -> None:
    await _setup(hass, entry)
    events = async_capture_events(hass, EVENT_COMMAND_FAILED)
    saic.unlock_vehicle.side_effect = SaicApiException(
        "The remote control instruction failed, please try again later.", return_code=4
    )
    lock = _id(hass, "lock", "lock")
    with pytest.raises(HomeAssistantError, match="return code: 4"):
        await hass.services.async_call("lock", "unlock", {"entity_id": lock}, blocking=True)
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["source"] == "unlock"
    assert "return code: 4" in events[0].data["error"]
    assert VIN not in str(events[0].data)
    assert hass.states.get(lock).state == "locked"
    await _unload(hass, entry)


async def test_command_triggers_one_live_read(hass: HomeAssistant, saic, entry) -> None:
    await _setup(hass, entry)
    await _skip(hass, 6)
    before = saic.get_vehicle_status.await_count
    await hass.services.async_call(
        "button", "press", {"entity_id": _id(hass, "button", "find_car")}, blocking=True
    )
    saic.control_find_my_car.assert_awaited_once()
    await _skip(hass, 21)
    assert saic.get_vehicle_status.await_count == before + 1
    await _unload(hass, entry)


async def test_charge_limit_and_charging_switch(hass: HomeAssistant, saic, entry) -> None:
    await _setup(hass, entry)
    await _skip(hass, 6)
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": _id(hass, "number", "charge_limit"), "value": 90},
        blocking=True,
    )
    code = saic.set_target_battery_soc.await_args.args[1]
    assert code.percentage == 90
    assert hass.states.get(_id(hass, "number", "charge_limit")).state == "90.0"

    switch = _id(hass, "switch", "charging_switch")
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    saic.control_charging.assert_awaited_once_with(VIN, stop_charging=False)
    assert hass.states.get(switch).state == "off"
    await _unload(hass, entry)


async def test_failing_live_read_is_not_retried_every_tick(hass: HomeAssistant, saic, entry) -> None:
    await _setup(hass, entry)
    saic.get_vehicle_status.side_effect = SaicApiException("car asleep", return_code=4)
    await _skip(hass, 6)
    assert saic.get_vehicle_status.await_count == 1
    for _ in range(10):
        await _skip(hass, 31)
    assert saic.get_vehicle_status.await_count == 1
    assert entry.state is ConfigEntryState.LOADED
    await _unload(hass, entry)


async def test_wrong_password_asks_for_reauth(hass: HomeAssistant, saic, entry) -> None:
    saic.is_logged_in = False
    saic.login.side_effect = SaicApiException(
        "Failed to get an access token, please check your credentials"
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    saic.close.assert_awaited()


async def test_cloud_down_retries_later(hass: HomeAssistant, saic, entry) -> None:
    saic.get_vehicle_status_cached.side_effect = SaicApiException(
        "API call GET /vehicle/status/cache failed unexpectedly", return_code=500
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    saic.get_vehicle_status.assert_not_awaited()
    saic.close.assert_awaited()
