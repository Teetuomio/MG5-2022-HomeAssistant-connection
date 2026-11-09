"""Home Assistant fixtures with the MG iSmart cloud replaced by a fake."""

from __future__ import annotations

from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from saic_ismart_client_ng.api.schema import GpsPosition
from saic_ismart_client_ng.api.vehicle.schema import (
    BasicVehicleStatus,
    VehicleListResp,
    VehicleStatusCacheResp,
    VehicleStatusResp,
    VinInfo,
)
from saic_ismart_client_ng.api.vehicle_charging.schema import (
    ChrgMgmtData,
    ChrgMgmtDataResp,
    RvsChargeStatus,
)

from custom_components.mg5.const import (
    CONF_ACCOUNT_TYPE,
    CONF_BATTERY,
    CONF_COUNTRY_CODE,
    CONF_MODEL,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SERIES,
    CONF_USERNAME,
    CONF_VIN,
    CONF_YEAR,
    DOMAIN,
)
from custom_components.mg5.schedule import CommandQueue

VIN = "LSJTEST0000000001"
MG4_VIN = "LSJTEST0000000002"

BASIC = {
    "batteryVoltage": 137,
    "interiorTemperature": 19,
    "exteriorTemperature": -128,
    "mileage": 484650,
    "lockStatus": 1,
    "remoteClimateStatus": 2,
    "driverDoor": 0,
    "passengerDoor": 0,
    "rearLeftDoor": 0,
    "rearRightDoor": 0,
    "bonnetStatus": 0,
    "bootStatus": 0,
    "frontLeftTyrePressure": 51,
    "frontRightTyrePressure": 50,
    "rearLeftTyrePressure": 52,
    "rearRightTyrePressure": 49,
    "fuelRangeElec": 3010,
}


def gps() -> GpsPosition:
    return GpsPosition(
        gpsStatus=2,
        timeStamp=1790884968,
        wayPoint=GpsPosition.WayPoint(
            position=GpsPosition.WayPoint.Position(
                altitude=12, latitude=51234567, longitude=-1234567
            )
        ),
    )


def cached_status(**overrides) -> VehicleStatusCacheResp:
    basic = dict(BASIC)
    basic.update(overrides)
    return VehicleStatusCacheResp(
        basicVehicleStatus=BasicVehicleStatus(**basic),
        gpsPosition=gps(),
        statusTime=1790884969,
    )


def live_status(**overrides) -> VehicleStatusResp:
    basic = dict(BASIC)
    basic.update(overrides)
    return VehicleStatusResp(
        basicVehicleStatus=BasicVehicleStatus(**basic),
        gpsPosition=gps(),
        statusTime=1790884969,
    )


def charging(**mgmt) -> ChrgMgmtDataResp:
    fields = {
        "bmsPackSOCDsp": 965,
        "bmsEstdElecRng": 243,
        "bmsOnBdChrgTrgtSOCDspCmd": 5,
        "bmsPackCrnt": 20000,
        "bmsPackVol": 1597,
        "bmsChrgSts": 0,
        "chrgngRmnngTime": 1023,
        "chrgngRmnngTimeV": 1,
    }
    fields.update(mgmt)
    return ChrgMgmtDataResp(
        chrgMgmtData=ChrgMgmtData(**fields),
        rvsChargeStatus=RvsChargeStatus(
            chargingGunState=0,
            mileageSinceLastCharge=0,
            powerUsageSinceLastCharge=10,
            totalBatteryCapacity=725,
        ),
    )


def vehicles() -> VehicleListResp:
    return VehicleListResp(
        vinList=[
            VinInfo(
                vin=MG4_VIN, modelName="MG4 Electric", modelYear="2023", series="EH32"
            ),
            VinInfo(
                vin=VIN,
                modelName="MG5 Electric",
                modelYear="2022",
                series="EP22 UK",
                colorName="Clever Grey",
            ),
        ]
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def saic():
    """The fake iSmart client. Every API method is an AsyncMock."""
    api = MagicMock()
    api.is_logged_in = True
    for name in (
        "login",
        "close",
        "lock_vehicle",
        "unlock_vehicle",
        "control_climate",
        "stop_ac",
        "control_find_my_car",
        "set_target_battery_soc",
        "control_charging",
        "set_schedule_charging",
    ):
        setattr(api, name, AsyncMock(return_value=None))
    api.vehicle_list = AsyncMock(return_value=vehicles())
    api.get_vehicle_status_cached = AsyncMock(return_value=cached_status())
    api.get_vehicle_status = AsyncMock(return_value=live_status())
    api.get_vehicle_charging_management_data = AsyncMock(return_value=charging())
    with (
        patch("custom_components.mg5.api.SaicApi", return_value=api),
        patch(
            "custom_components.mg5.coordinator.CommandQueue",
            partial(CommandQueue, min_gap=0),
        ),
    ):
        yield api


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=VIN,
        title="MG5 Electric 2022 (0001)",
        data={
            CONF_ACCOUNT_TYPE: "email",
            CONF_USERNAME: "driver@example.com",
            CONF_PASSWORD: "not-a-real-password",
            CONF_REGION: "eu",
            CONF_COUNTRY_CODE: "",
            CONF_VIN: VIN,
            CONF_MODEL: "MG5 Electric",
            CONF_YEAR: "2022",
            CONF_SERIES: "EP22 UK",
        },
        options={CONF_BATTERY: "long_range"},
    )
