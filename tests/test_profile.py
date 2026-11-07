"""Decoding and the MG5 2022 entity set."""

from datetime import UTC, datetime

from custom_components.mg5.profile import (
    BOGUS_API_CAPACITY_KWH,
    SENSOR_SPECS,
    UNSUPPORTED_FEATURES,
    clean_temperature,
    climate_is_on,
    climate_on_command,
    decode_snapshot,
    entity_keys,
    hvac_mode_name,
    is_mg5,
    merge_cached,
    pack_kwh,
    temperature_action,
    temperature_index,
)

# Telemetry from a public 2022 MG5 log. The GPS fix is synthetic so this
# repo does not republish that car's location.
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
CHARGE = {
    "bmsPackSOCDsp": 965,
    "bmsEstdElecRng": 243,
    "bmsOnBdChrgTrgtSOCDspCmd": 5,
    "bmsPackCrnt": 20000,
    "bmsPackVol": 1597,
    "bmsChrgSts": 0,
    "chrgngRmnngTime": 1023,
    "chrgngRmnngTimeV": 1,
    "chargingGunState": 0,
    "mileageSinceLastCharge": 0,
    "powerUsageSinceLastCharge": 10,
    "totalBatteryCapacity": 725,
}


def _snapshot(**overrides):
    basic = dict(BASIC)
    charge = dict(CHARGE)
    basic.update(overrides.pop("basic", {}))
    charge.update(overrides.pop("charge", {}))
    return decode_snapshot(
        basic=basic,
        charge=charge,
        gps_latitude=overrides.get("gps_latitude", 51234567),
        gps_longitude=overrides.get("gps_longitude", -1234567),
        gps_altitude=overrides.get("gps_altitude", 12),
        gps_status=overrides.get("gps_status", 2),
        status_time=overrides.get("status_time", 1790884969),
        pack="long_range",
        api_capacity_raw=725,
        source="live",
    )


def test_anonymized_2022_status_scales_and_overrides_capacity():
    snap = _snapshot()
    assert snap.soc == 96.5
    assert snap.estimated_range_km == 243
    assert snap.aux_voltage == 13.7
    assert snap.odometer_km == 48465.0
    assert snap.latitude == 51.234567
    assert snap.longitude == -1.234567
    assert snap.battery_capacity_kwh == 61.1
    assert snap.battery_capacity_kwh != BOGUS_API_CAPACITY_KWH
    assert snap.battery_energy_kwh == round(96.5 / 100 * 61.1, 2)
    assert snap.battery_energy_kwh != round(96.5 / 100 * BOGUS_API_CAPACITY_KWH, 2)
    assert snap.interior_c == 19
    assert snap.exterior_c is None
    assert snap.target_soc == 80
    assert snap.charge_current_a == 0
    assert snap.charge_voltage_v == 399.25
    assert snap.charge_power_kw == 0
    assert snap.remaining_charge_min is None
    assert snap.energy_since_charge_kwh == 1.0
    assert snap.distance_since_charge_km == 0
    assert snap.tyre_front_left == 2.04
    assert snap.locked is True
    assert snap.driver_door_open is False
    assert snap.charging is False
    assert snap.cable_connected is False
    assert snap.last_contact == datetime.fromtimestamp(1790884969, tz=UTC)
    assert pack_kwh("long_range", 725) == 61.1
    assert pack_kwh("standard", 725) == 50.3


def test_status_2_is_climate_on_not_fan_only():
    assert climate_is_on(2) is True
    assert climate_is_on(0) is False
    assert hvac_mode_name(climate_on=climate_is_on(2)) == "heat_cool"
    assert hvac_mode_name(climate_on=climate_is_on(0)) == "off"
    assert hvac_mode_name(climate_on=True) != "fan_only"
    assert _snapshot().climate_on is True
    off = _snapshot(basic={"remoteClimateStatus": 0})
    assert off.climate_on is False


def test_invalid_temperatures_are_dropped():
    assert clean_temperature(-128) is None
    assert clean_temperature(87) is None
    assert clean_temperature(19) == 19
    snap = _snapshot(basic={"interiorTemperature": 87, "exteriorTemperature": 87})
    assert snap.interior_c is None
    assert snap.exterior_c is None


def test_no_gps_fix_is_not_a_location():
    snap = _snapshot(gps_status=0)
    assert snap.latitude is None
    assert snap.longitude is None


def test_mg5_config_does_not_create_dead_controls():
    config = {
        "HeatedSeat": "0",
        "WINDOW": "0000",
        "Sunroof": "0",
        "S35": "0",
        "SBH": "0",
        "BHI": "0",
        "T11": "1",
        "S61": "1",
    }
    keys = entity_keys(config)
    for forbidden in UNSUPPORTED_FEATURES:
        assert forbidden not in keys
        assert not any(forbidden in key for key in keys)
    # A stray "equipped" flag still does not create them.
    equipped = dict(config)
    equipped["HeatedSeat"] = "1"
    equipped["WINDOW"] = "1111"
    assert entity_keys(equipped) == keys
    assert "soc" in keys
    assert "lock" in keys
    assert "climate" in keys
    assert "charge_limit" in keys
    for spec in SENSOR_SPECS:
        assert spec.key in keys


def test_only_an_mg5_is_accepted():
    assert is_mg5("MG5 Electric", "EP22 UK") is True
    assert is_mg5(None, "EP21") is True
    assert is_mg5("MG4", "EH32") is False
    assert is_mg5("MGS5 EV", "MZS3E") is False
    assert is_mg5("MG S5", None) is False


def test_temperature_index_and_when_a_slider_sends():
    assert temperature_index(22) == 8
    assert temperature_index(25) == 11
    assert temperature_index(16) == 2
    assert temperature_index(28) == 14
    command = climate_on_command(22)
    assert command.fan_speed == 2
    assert command.ac_on is None
    assert command.temperature_idx == 8
    assert temperature_action(climate_on=False) == "store"
    assert temperature_action(climate_on=True) == "send"


def test_charging_power_is_positive_while_current_is_negative():
    snap = _snapshot(charge={"bmsPackCrnt": 18000, "bmsPackVol": 1600, "bmsChrgSts": 1})
    assert snap.charge_current_a == -100
    assert snap.charge_voltage_v == 400
    assert snap.charge_power_kw == 40
    assert snap.charging is True


def test_cached_read_keeps_state_of_charge():
    live = _snapshot()
    cached = decode_snapshot(
        basic=BASIC,
        charge=None,
        gps_latitude=51234567,
        gps_longitude=-1234567,
        gps_status=2,
        status_time=1790884969,
        pack="long_range",
        api_capacity_raw=725,
        source="cached",
    )
    assert cached.soc is None
    merged = merge_cached(live, cached)
    assert merged.soc == 96.5
    assert merged.battery_energy_kwh == live.battery_energy_kwh
    assert merged.target_soc == 80
    assert merged.charging is False
