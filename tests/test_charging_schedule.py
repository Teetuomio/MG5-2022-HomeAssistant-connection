"""The scheduled-charging window: what the car reports and what is sent."""

from datetime import time

import pytest
from saic_ismart_client_ng.api.vehicle_charging import SaicVehicleChargingApi
from saic_ismart_client_ng.api.vehicle_charging.schema import ScheduledChargingRequest
from saic_ismart_client_ng.exceptions import SaicApiException

from custom_components.mg5.api import Mg5Client
from custom_components.mg5.profile import (
    SCHEDULE_DISABLED,
    SCHEDULE_UNTIL_END_TIME,
    SCHEDULE_UNTIL_TARGET_SOC,
    ChargeSchedule,
    decode_schedule,
    decode_snapshot,
    fill_schedule,
    merge_cached,
    schedule_clock,
)

REPORTED = {
    "bmsReserStHourDspCmd": 22,
    "bmsReserStMintueDspCmd": 30,
    "bmsReserSpHourDspCmd": 6,
    "bmsReserSpMintueDspCmd": 0,
    "bmsReserCtrlDspCmd": 1,
}


def _snapshot(charge, *, source="live"):
    return decode_snapshot(
        basic={"mileage": 484650},
        charge=charge,
        pack="long_range",
        source=source,
    )


def test_reported_window_and_mode_are_decoded():
    schedule = decode_schedule(REPORTED)
    assert schedule == ChargeSchedule(time(22, 30), time(6, 0), SCHEDULE_UNTIL_END_TIME)
    assert decode_schedule({**REPORTED, "bmsReserCtrlDspCmd": 2}).mode == SCHEDULE_DISABLED
    assert decode_schedule({**REPORTED, "bmsReserCtrlDspCmd": 3}).mode == (
        SCHEDULE_UNTIL_TARGET_SOC
    )


def test_reported_schedule_reaches_the_sensors():
    snap = _snapshot(REPORTED)
    assert snap.sensor("reported_charging_start") == "22:30"
    assert snap.sensor("reported_charging_end") == "06:00"
    assert snap.sensor("reported_charging_schedule") == SCHEDULE_UNTIL_END_TIME


def test_no_reported_schedule_is_unknown_not_an_error():
    for charge in (None, {}, dict.fromkeys(REPORTED)):
        snap = _snapshot(charge)
        assert snap.charge_schedule == ChargeSchedule(None, None, None)
        assert snap.sensor("reported_charging_start") is None
        assert snap.sensor("reported_charging_end") is None
        assert snap.sensor("reported_charging_schedule") is None


def test_impossible_clock_values_and_unknown_modes_are_dropped():
    assert schedule_clock(24, 0) is None
    assert schedule_clock(7, 60) is None
    assert schedule_clock(-1, 0) is None
    assert schedule_clock(7, None) is None
    assert schedule_clock(0, 0) == time(0, 0)
    assert decode_schedule({**REPORTED, "bmsReserCtrlDspCmd": 0}).mode is None
    assert decode_schedule({**REPORTED, "bmsReserCtrlDspCmd": 9}).mode is None


def test_unreported_parts_fill_with_disabled_and_22_to_06():
    assert fill_schedule(ChargeSchedule(None, None, None)) == ChargeSchedule(
        time(22, 0), time(6, 0), SCHEDULE_DISABLED
    )
    assert fill_schedule(ChargeSchedule(time(23, 0), None, None)) == ChargeSchedule(
        time(23, 0), time(6, 0), SCHEDULE_DISABLED
    )
    reported = ChargeSchedule(time(0, 0), time(5, 0), SCHEDULE_UNTIL_TARGET_SOC)
    assert fill_schedule(reported) == reported


def test_cached_read_keeps_the_reported_schedule():
    live = _snapshot(REPORTED)
    cached = _snapshot(None, source="cached")
    assert merge_cached(live, cached).charge_schedule == live.charge_schedule


class _FakeApi:
    """The real request builder from the client, with the HTTP call captured."""

    is_logged_in = True
    set_schedule_charging = SaicVehicleChargingApi.set_schedule_charging

    def __init__(self) -> None:
        self.calls: list[tuple[str, ScheduledChargingRequest]] = []

    async def send_vehicle_charging_reservation(self, vin, body):
        self.calls.append((vin, body))


def _client() -> tuple[Mg5Client, _FakeApi]:
    client = Mg5Client.__new__(Mg5Client)
    api = _FakeApi()
    client._api = api  # type: ignore[attr-defined]
    return client, api


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        (SCHEDULE_UNTIL_END_TIME, 1),
        (SCHEDULE_DISABLED, 2),
        (SCHEDULE_UNTIL_TARGET_SOC, 3),
    ],
)
def test_schedule_payload(run, mode, code):
    client, api = _client()
    run(
        client.set_schedule(
            "TESTVIN0000000000",
            ChargeSchedule(time(23, 15, 42), time(5, 45), mode),
        )
    )
    assert len(api.calls) == 1
    vin, body = api.calls[0]
    assert vin == "TESTVIN0000000000"
    assert body.rsvanStHour == 23
    assert body.rsvanStMintue == 15
    assert body.rsvanSpHour == 5
    assert body.rsvanSpMintue == 45
    assert body.tboxReserCtrlReq == code
    assert body.tboxAdpPubChrgSttnReq == 1


def test_incomplete_schedule_is_not_sent(run):
    client, api = _client()
    with pytest.raises(SaicApiException, match="start time"):
        run(client.set_schedule("TESTVIN0000000000", ChargeSchedule(None, time(6, 0), "disabled")))
    assert api.calls == []
