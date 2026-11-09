"""Scheduled charging inside Home Assistant."""

import asyncio
import logging
from datetime import time, timedelta

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
from saic_ismart_client_ng.api.vehicle_charging.schema import ScheduledChargingMode
from saic_ismart_client_ng.exceptions import SaicApiException

from custom_components.mg5.const import DOMAIN, EVENT_COMMAND_FAILED

from .conftest import VIN, charging

SCHEDULE = {
    "bmsReserStHourDspCmd": 22,
    "bmsReserStMintueDspCmd": 30,
    "bmsReserSpHourDspCmd": 6,
    "bmsReserSpMintueDspCmd": 0,
    "bmsReserCtrlDspCmd": 1,
}


@pytest.fixture(autouse=True)
def quick_settle(monkeypatch):
    monkeypatch.setattr("custom_components.mg5.coordinator.SCHEDULE_SETTLE_SECONDS", 0.05)


def _id(hass: HomeAssistant, domain: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{VIN}_{key}")
    assert entity_id, f"{domain} {key} was not created"
    return entity_id


async def _skip(hass: HomeAssistant, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def _setup_with(hass: HomeAssistant, saic, entry, **schedule) -> None:
    saic.get_vehicle_charging_management_data.return_value = charging(**schedule)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _skip(hass, 6)


async def _set_time(hass: HomeAssistant, key: str, value: str) -> None:
    await hass.services.async_call(
        "time", "set_value", {"entity_id": _id(hass, "time", key), "time": value}, blocking=True
    )


async def _select(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _id(hass, "select", "charging_schedule"), "option": option},
        blocking=True,
    )


def _sent(saic) -> tuple[time, time, ScheduledChargingMode]:
    call = saic.set_schedule_charging.await_args
    assert call.args == (VIN,)
    return call.kwargs["start_time"], call.kwargs["end_time"], call.kwargs["mode"]


async def test_reported_schedule_is_shown(hass: HomeAssistant, saic, entry) -> None:
    await _setup_with(hass, saic, entry, **SCHEDULE)
    start = hass.states.get(_id(hass, "time", "charging_start"))
    assert start.state == "22:30:00"
    assert start.attributes["friendly_name"] == "MG5 0001 Charging start"
    assert hass.states.get(_id(hass, "time", "charging_end")).state == "06:00:00"
    select = hass.states.get(_id(hass, "select", "charging_schedule"))
    assert select.state == "until_end_time"
    assert select.attributes["options"] == ["disabled", "until_end_time", "until_target_soc"]
    assert select.attributes["friendly_name"] == "MG5 0001 Charging schedule"
    assert hass.states.get(_id(hass, "sensor", "reported_charging_start")).state == "22:30"
    assert hass.states.get(_id(hass, "sensor", "reported_charging_end")).state == "06:00"
    mode = hass.states.get(_id(hass, "sensor", "reported_charging_schedule"))
    assert mode.state == "until_end_time"
    assert mode.attributes["friendly_name"] == "MG5 0001 Reported charging schedule"
    saic.set_schedule_charging.assert_not_awaited()


async def test_no_reported_schedule_loads_as_unknown(
    hass: HomeAssistant, saic, entry, caplog
) -> None:
    caplog.set_level(logging.INFO, logger="custom_components.mg5")
    await _setup_with(hass, saic, entry)
    assert entry.state is ConfigEntryState.LOADED
    for domain, key in (
        ("time", "charging_start"),
        ("time", "charging_end"),
        ("select", "charging_schedule"),
        ("sensor", "reported_charging_start"),
        ("sensor", "reported_charging_end"),
        ("sensor", "reported_charging_schedule"),
    ):
        assert hass.states.get(_id(hass, domain, key)).state == "unknown", key
    saic.set_schedule_charging.assert_not_awaited()

    notes = [r for r in caplog.records if "no scheduled-charging fields" in r.getMessage()]
    assert len(notes) == 1
    assert "bmsPackSOCDsp" in notes[0].getMessage()
    assert VIN not in caplog.text

    await hass.services.async_call(
        "button", "press", {"entity_id": _id(hass, "button", "refresh")}, blocking=True
    )
    await _skip(hass, 11)
    assert saic.get_vehicle_status.await_count == 2
    notes = [r for r in caplog.records if "no scheduled-charging fields" in r.getMessage()]
    assert len(notes) == 1


async def test_first_schedule_can_be_set_when_the_car_reports_mode_0_and_no_times(
    hass: HomeAssistant, saic, entry
) -> None:
    await _setup_with(hass, saic, entry, bmsReserCtrlDspCmd=0)
    assert hass.states.get(_id(hass, "select", "charging_schedule")).state == "unknown"
    assert hass.states.get(_id(hass, "time", "charging_start")).state == "unknown"
    for _ in range(3):
        await _skip(hass, 31)
    saic.set_schedule_charging.assert_not_awaited()

    await _set_time(hass, "charging_start", "23:00")
    saic.set_schedule_charging.assert_awaited_once()
    assert _sent(saic) == (time(23, 0), time(6, 0), ScheduledChargingMode.DISABLED)
    assert hass.states.get(_id(hass, "time", "charging_start")).state == "23:00:00"
    assert hass.states.get(_id(hass, "time", "charging_end")).state == "06:00:00"
    assert hass.states.get(_id(hass, "select", "charging_schedule")).state == "disabled"


async def test_first_mode_choice_uses_the_default_window(hass: HomeAssistant, saic, entry) -> None:
    await _setup_with(hass, saic, entry)
    await _select(hass, "until_end_time")
    saic.set_schedule_charging.assert_awaited_once()
    assert _sent(saic) == (
        time(22, 0),
        time(6, 0),
        ScheduledChargingMode.UNTIL_CONFIGURED_TIME,
    )


async def test_start_time_sends_one_command_with_the_shown_end_and_mode(
    hass: HomeAssistant, saic, entry
) -> None:
    await _setup_with(hass, saic, entry, **SCHEDULE)
    live_reads = saic.get_vehicle_status.await_count
    await _set_time(hass, "charging_start", "23:15")
    saic.set_schedule_charging.assert_awaited_once()
    assert _sent(saic) == (time(23, 15), time(6, 0), ScheduledChargingMode.UNTIL_CONFIGURED_TIME)
    assert hass.states.get(_id(hass, "time", "charging_start")).state == "23:15:00"

    await _skip(hass, 21)
    assert saic.get_vehicle_status.await_count == live_reads + 1
    saic.set_schedule_charging.assert_awaited_once()


async def test_two_quick_edits_are_one_command(hass: HomeAssistant, saic, entry) -> None:
    await _setup_with(hass, saic, entry, **SCHEDULE)
    await asyncio.gather(
        _set_time(hass, "charging_start", "21:00"),
        _set_time(hass, "charging_end", "07:30"),
    )
    saic.set_schedule_charging.assert_awaited_once()
    assert _sent(saic) == (time(21, 0), time(7, 30), ScheduledChargingMode.UNTIL_CONFIGURED_TIME)


async def test_dragging_one_picker_twice_is_one_command(hass: HomeAssistant, saic, entry) -> None:
    await _setup_with(hass, saic, entry, **SCHEDULE)
    await asyncio.gather(
        _set_time(hass, "charging_start", "21:00"),
        _set_time(hass, "charging_start", "21:30"),
    )
    saic.set_schedule_charging.assert_awaited_once()
    assert _sent(saic)[0] == time(21, 30)


@pytest.mark.parametrize(
    ("option", "mode"),
    [
        ("disabled", ScheduledChargingMode.DISABLED),
        ("until_target_soc", ScheduledChargingMode.UNTIL_CONFIGURED_SOC),
    ],
)
async def test_mode_change_keeps_the_shown_times(
    hass: HomeAssistant, saic, entry, option, mode
) -> None:
    await _setup_with(hass, saic, entry, **SCHEDULE)
    await _select(hass, option)
    saic.set_schedule_charging.assert_awaited_once()
    assert _sent(saic) == (time(22, 30), time(6, 0), mode)
    assert hass.states.get(_id(hass, "select", "charging_schedule")).state == option


async def test_choosing_what_the_car_already_has_sends_nothing(
    hass: HomeAssistant, saic, entry
) -> None:
    await _setup_with(hass, saic, entry, **SCHEDULE)
    await _select(hass, "until_end_time")
    await _set_time(hass, "charging_start", "22:30")
    saic.set_schedule_charging.assert_not_awaited()


async def test_rejected_schedule_raises_and_shows_the_car_value(
    hass: HomeAssistant, saic, entry
) -> None:
    await _setup_with(hass, saic, entry, **SCHEDULE)
    events = async_capture_events(hass, EVENT_COMMAND_FAILED)
    saic.set_schedule_charging.side_effect = SaicApiException(
        "The remote control instruction failed, please try again later.", return_code=4
    )
    with pytest.raises(HomeAssistantError, match="return code: 4"):
        await _select(hass, "disabled")
    await hass.async_block_till_done()
    saic.set_schedule_charging.assert_awaited_once()
    assert [event.data["source"] for event in events] == ["charging_schedule"]
    assert hass.states.get(_id(hass, "select", "charging_schedule")).state == "until_end_time"


async def test_schedule_entities_do_not_poll(hass: HomeAssistant, saic, entry) -> None:
    await _setup_with(hass, saic, entry, **SCHEDULE)
    live_reads = saic.get_vehicle_status.await_count
    charging_reads = saic.get_vehicle_charging_management_data.await_count
    for _ in range(10):
        await _skip(hass, 31)
    assert saic.get_vehicle_status.await_count == live_reads
    assert saic.get_vehicle_charging_management_data.await_count == charging_reads
    saic.set_schedule_charging.assert_not_awaited()
