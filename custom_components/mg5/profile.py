"""MG5 Electric (2022, series EP21/EP22) decoding and command profile.

The generic MG SAIC integration has no profile for this car. It forces the
air-conditioning compressor on, labels climate status 2 as fan-only, and still
offers heated seats, windows and a sunroof. A 2022 MG5 reports those as absent
and ignores the forced-compressor command, so a higher temperature never heats.

Parameter 20 value 0x08 is 22°C on an MG5 (index = celsius - 14). The plain
"AC on" command is fan speed 2 with the compressor byte omitted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, time
from typing import Any, Mapping

PACK_KWH = {
    "standard": 50.3,
    "long_range": 61.1,
}

# The charging endpoint reports 725 (72.5 kWh) for this car. That figure is
# shared with other SAIC models and is not an MG5 pack.
BOGUS_API_CAPACITY_KWH = 72.5

TEMP_MIN = 16
TEMP_MAX = 28
TEMP_INDEX_OFFSET = 14

# Status values the car actually reports. 0 is off. 2 is running, not fan-only.
CLIMATE_OFF = 0

# Tyre raw value 70 is about 2.8 bar. raw * 4 = kPa.
TYRE_BAR_FACTOR = 0.04

GPS_SCALE = 1_000_000

INVALID_TEMPERATURES = frozenset({-128, 87})

# BMS charging-status codes that mean current is flowing into the battery.
_CHARGING_CODES = frozenset({1, 3, 10, 11, 12})
# Plugged in, including done, scheduled, and paused. 0 is unplugged.
_PLUGGED_CODES = frozenset({1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13})

# Features this model does not have. Present so a config flag cannot turn them on.
UNSUPPORTED_FEATURES = frozenset(
    {
        "heated_seat",
        "heated_seats",
        "window",
        "windows",
        "sunroof",
        "steering_heat",
        "steering_wheel_heat",
        "front_defrost",
        "rear_defrost",
        "battery_heating",
    }
)

_MG5_SERIES = ("EP21", "EP22")


def is_mg5(model_name: str | None, series: str | None) -> bool:
    """True for an MG5 Electric, including series EP21 and EP22.

    MGS5 and MG S5 are different cars and must not match.
    """
    series_name = (series or "").upper().strip()
    if series_name.startswith(_MG5_SERIES):
        return True
    compact = "".join((model_name or "").upper().split())
    return "MG5" in compact


def pack_kwh(pack: str, api_capacity_raw: int | None = None) -> float:
    """Return the real pack size. The API capacity is ignored."""
    del api_capacity_raw
    try:
        return PACK_KWH[pack]
    except KeyError as err:
        msg = f"Unknown MG5 battery pack: {pack}"
        raise ValueError(msg) from err


def clamp_temperature(celsius: float) -> int:
    rounded = int(round(celsius))
    return max(TEMP_MIN, min(TEMP_MAX, rounded))


def temperature_index(celsius: float) -> int:
    """Map a cabin setpoint to the MG5 parameter-20 index. 22°C is 8."""
    return clamp_temperature(celsius) - TEMP_INDEX_OFFSET


def clean_temperature(value: int | float | None) -> float | None:
    if value is None:
        return None
    if value in INVALID_TEMPERATURES or value < -40 or value > 60:
        return None
    return float(value)


def climate_is_on(remote_climate_status: int | None) -> bool | None:
    """Status 2 is running. The generic integration calls 2 fan-only; this car does not."""
    if remote_climate_status is None:
        return None
    return remote_climate_status != CLIMATE_OFF


def hvac_mode_name(*, climate_on: bool | None) -> str | None:
    """heat_cool or off. There is no fan-only mode on this car."""
    if climate_on is None:
        return None
    if climate_on:
        return "heat_cool"
    return "off"


def temperature_action(*, climate_on: bool) -> str:
    """Changing the slider while the cabin is off must not spend a command."""
    if climate_on:
        return "send"
    return "store"


@dataclass(frozen=True)
class ClimateCommand:
    """Arguments for SaicVehicleClimateApi.control_climate."""

    fan_speed: int
    ac_on: bool | None
    temperature_idx: int

    def as_kwargs(self) -> dict[str, Any]:
        return {
            "fan_speed": self.fan_speed,
            "ac_on": self.ac_on,
            "temperature_idx": self.temperature_idx,
        }


def climate_on_command(celsius: float) -> ClimateCommand:
    """Start cabin climate without forcing the compressor byte.

    ac_on None omits parameter 22. Sending that byte as on forces cooling,
    which is why a warmer setpoint does nothing on this car.
    """
    return ClimateCommand(
        fan_speed=2,
        ac_on=None,
        temperature_idx=temperature_index(celsius),
    )


def climate_off_command() -> ClimateCommand:
    return ClimateCommand(fan_speed=0, ac_on=False, temperature_idx=0)


MAX_ODOMETER_KM = 2_000_000.0


def _tenths(value: int | float | None) -> float | None:
    if value is None:
        return None
    return float(value) / 10


def _odometer_km(value: int | float | None) -> float | None:
    """Mileage in km, or None when the API returns a value the car cannot have.

    The iSmart cloud occasionally answers with a negative or absurd mileage
    (a raw -128 was seen on a real car, which became -12.8 km). Publishing that
    would show a wrong number and, because the sensor is total_increasing,
    corrupt long-term statistics.
    """
    if value is None:
        return None
    km = float(value) / 10
    if km < 0 or km > MAX_ODOMETER_KM:
        return None
    return km


def _aux_voltage(raw: int | float | None) -> float | None:
    if raw is None or raw <= 0:
        return None
    return float(raw) / 10


def _tyre_bar(raw: int | float | None) -> float | None:
    if raw is None or raw <= 0 or raw >= 255:
        return None
    return round(float(raw) * TYRE_BAR_FACTOR, 2)


def _gps(raw: int | float | None, gps_status: int | None) -> float | None:
    if raw is None or gps_status == 0:
        return None
    scaled = float(raw) / GPS_SCALE
    if scaled == 0:
        return None
    return scaled


def _soc(raw: int | float | None) -> float | None:
    if raw is None or raw < 0 or raw > 1000:
        return None
    return float(raw) / 10


def _range_km(bms_km: int | float | None, cluster_raw: int | float | None) -> float | None:
    if bms_km is not None and 0 < bms_km < 2000:
        return float(bms_km)
    if cluster_raw is not None and cluster_raw > 0:
        return float(cluster_raw) / 10
    return None


def _pack_current_a(raw: int | float | None) -> float | None:
    if raw is None:
        return None
    return float(raw) * 0.05 - 1000.0


def _pack_voltage_v(raw: int | float | None) -> float | None:
    if raw is None or raw <= 0:
        return None
    return float(raw) * 0.25


def _target_soc(code: int | None) -> int | None:
    # 1=40 ... 7=100. 0 means "leave unchanged" and is not a setpoint.
    if code is None or code <= 0:
        return None
    percent = 30 + code * 10
    if percent < 40 or percent > 100:
        return None
    return percent


SCHEDULE_DISABLED = "disabled"
SCHEDULE_UNTIL_END_TIME = "until_end_time"
SCHEDULE_UNTIL_TARGET_SOC = "until_target_soc"

# ScheduledChargingMode values in saic-ismart-client-ng. The same codes come
# back in bmsReserCtrlDspCmd.
SCHEDULE_MODE_CODES: dict[str, int] = {
    SCHEDULE_UNTIL_END_TIME: 1,
    SCHEDULE_DISABLED: 2,
    SCHEDULE_UNTIL_TARGET_SOC: 3,
}
_SCHEDULE_MODE_NAMES = {code: name for name, code in SCHEDULE_MODE_CODES.items()}
SCHEDULE_MODES: tuple[str, ...] = (
    SCHEDULE_DISABLED,
    SCHEDULE_UNTIL_END_TIME,
    SCHEDULE_UNTIL_TARGET_SOC,
)


def schedule_clock(hour: int | None, minute: int | None) -> time | None:
    """Hour and minute of the charging window, or None when the car sent nothing usable.

    The car stores a time of day only. There is no date or weekday: the window
    repeats every day until it is changed or disabled.
    """
    if hour is None or minute is None:
        return None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return time(hour=int(hour), minute=int(minute))


def schedule_mode_name(code: int | None) -> str | None:
    if code is None:
        return None
    return _SCHEDULE_MODE_NAMES.get(int(code))


@dataclass(frozen=True)
class ChargeSchedule:
    """The daily charging window. Hour and minute only; no date, no weekday."""

    start: time | None
    end: time | None
    mode: str | None

    @property
    def complete(self) -> bool:
        return self.start is not None and self.end is not None and self.mode is not None


# Used only to build the first command when the car has reported no window.
# A typical overnight off-peak window; hour and minute, repeated daily.
DEFAULT_SCHEDULE_START = time(22, 0)
DEFAULT_SCHEDULE_END = time(6, 0)


def fill_schedule(schedule: ChargeSchedule) -> ChargeSchedule:
    """Complete a window the car has not fully reported, so it can be sent.

    A missing mode becomes disabled, so filling in never starts a schedule on
    its own. Missing times become 22:00 and 06:00. Hour and minute only; there
    is no date or weekday.
    """
    return ChargeSchedule(
        start=DEFAULT_SCHEDULE_START if schedule.start is None else schedule.start,
        end=DEFAULT_SCHEDULE_END if schedule.end is None else schedule.end,
        mode=SCHEDULE_DISABLED if schedule.mode is None else schedule.mode,
    )


@dataclass(frozen=True)
class ScheduleCommand:
    start: time
    end: time
    mode_code: int


def schedule_command(schedule: ChargeSchedule) -> ScheduleCommand:
    start, end, mode = schedule.start, schedule.end, schedule.mode
    if start is None or end is None or mode is None:
        raise ValueError("A charging schedule needs a start time, an end time and a mode")
    if mode not in SCHEDULE_MODE_CODES:
        raise ValueError(f"Unknown charging schedule mode: {mode}")
    return ScheduleCommand(
        start=start.replace(second=0, microsecond=0),
        end=end.replace(second=0, microsecond=0),
        mode_code=SCHEDULE_MODE_CODES[mode],
    )


def _remaining_minutes(value: int | None, valid_flag: int | None) -> int | None:
    if value is None or value >= 1023 or valid_flag == 1:
        return None
    if value < 0:
        return None
    return int(value)


def _open(value: int | None) -> bool | None:
    if value is None:
        return None
    if value == 1:
        return True
    if value == 0:
        return False
    return None


def _locked(value: int | None) -> bool | None:
    if value is None:
        return None
    if value == 1:
        return True
    if value == 0:
        return False
    return None


def _is_charging(code: int | None) -> bool | None:
    if code is None:
        return None
    return code in _CHARGING_CODES


def _cable_connected(gun: int | None, bms_code: int | None) -> bool | None:
    if gun is not None:
        return gun not in (0,)
    if bms_code is None:
        return None
    return bms_code in _PLUGGED_CODES


@dataclass(frozen=True)
class SensorSpec:
    key: str
    name: str
    device_class: str | None = None
    unit: str | None = None
    state_class: str | None = None
    icon: str | None = None
    options: tuple[str, ...] | None = None
    translation_key: str | None = None


SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec("soc", "State of charge", "battery", "%", "measurement"),
    SensorSpec("estimated_range", "Estimated range", "distance", "km", "measurement"),
    SensorSpec("odometer", "Odometer", "distance", "km", "total_increasing"),
    SensorSpec("interior_temperature", "Interior temperature", "temperature", "°C", "measurement"),
    SensorSpec("exterior_temperature", "Exterior temperature", "temperature", "°C", "measurement"),
    SensorSpec("aux_voltage", "12V battery", "voltage", "V", "measurement", "mdi:car-battery"),
    SensorSpec("tyre_front_left", "Front left tyre", "pressure", "bar", "measurement"),
    SensorSpec("tyre_front_right", "Front right tyre", "pressure", "bar", "measurement"),
    SensorSpec("tyre_rear_left", "Rear left tyre", "pressure", "bar", "measurement"),
    SensorSpec("tyre_rear_right", "Rear right tyre", "pressure", "bar", "measurement"),
    SensorSpec("charge_power", "Charging power", "power", "kW", "measurement"),
    SensorSpec("charge_current", "Charging current", "current", "A", "measurement"),
    SensorSpec("charge_voltage", "Charging voltage", "voltage", "V", "measurement"),
    SensorSpec("remaining_charge", "Remaining charge time", "duration", "min", "measurement"),
    SensorSpec("target_soc", "Target state of charge", "battery", "%", "measurement"),
    SensorSpec("distance_since_charge", "Distance since charge", "distance", "km", "total_increasing"),
    SensorSpec("energy_since_charge", "Energy since charge", "energy", "kWh", "total_increasing"),
    SensorSpec("battery_energy", "Battery energy", "energy_storage", "kWh", "measurement"),
    SensorSpec("last_contact", "Last contact", "timestamp", None, None, "mdi:update"),
    SensorSpec(
        "reported_charging_start", "Reported charging start", None, None, None, "mdi:clock-start"
    ),
    SensorSpec(
        "reported_charging_end", "Reported charging end", None, None, None, "mdi:clock-end"
    ),
    SensorSpec(
        "reported_charging_schedule",
        "Reported charging schedule",
        "enum",
        None,
        None,
        "mdi:calendar-clock",
        options=SCHEDULE_MODES,
        translation_key="charging_schedule",
    ),
)


@dataclass(frozen=True)
class BinarySpec:
    key: str
    name: str
    device_class: str | None = None
    icon: str | None = None


BINARY_SPECS: tuple[BinarySpec, ...] = (
    BinarySpec("locked", "Locked", None, "mdi:lock"),
    BinarySpec("driver_door", "Driver door", "door"),
    BinarySpec("passenger_door", "Passenger door", "door"),
    BinarySpec("rear_left_door", "Rear left door", "door"),
    BinarySpec("rear_right_door", "Rear right door", "door"),
    BinarySpec("bonnet", "Bonnet", "door", "mdi:car"),
    BinarySpec("boot", "Boot", "door", "mdi:car-back"),
    BinarySpec("charging", "Charging", "battery_charging"),
    BinarySpec("charge_cable", "Charge cable", "plug"),
    BinarySpec("climate_active", "Climate running", None, "mdi:air-conditioner"),
)

CONTROL_KEYS = frozenset(
    {
        "lock",
        "climate",
        "charge_limit",
        "charging_switch",
        "find_car",
        "refresh",
        "location",
        "charging_start",
        "charging_end",
        "charging_schedule",
    }
)


def entity_keys(configuration: Mapping[str, str] | None = None) -> set[str]:
    """Entity keys created for this car.

    configuration is the iSmart vehicleModelConfiguration map. Heated seats,
    windows, sunroof and battery heating stay absent even if a flag says 1.
    """
    del configuration
    keys = {spec.key for spec in SENSOR_SPECS}
    keys.update(spec.key for spec in BINARY_SPECS)
    keys.update(CONTROL_KEYS)
    return keys


@dataclass(frozen=True)
class Mg5Snapshot:
    soc: float | None
    estimated_range_km: float | None
    odometer_km: float | None
    interior_c: float | None
    exterior_c: float | None
    aux_voltage: float | None
    tyre_front_left: float | None
    tyre_front_right: float | None
    tyre_rear_left: float | None
    tyre_rear_right: float | None
    charge_power_kw: float | None
    charge_current_a: float | None
    charge_voltage_v: float | None
    remaining_charge_min: int | None
    target_soc: int | None
    distance_since_charge_km: float | None
    energy_since_charge_kwh: float | None
    battery_energy_kwh: float | None
    battery_capacity_kwh: float
    last_contact: datetime | None
    locked: bool | None
    driver_door_open: bool | None
    passenger_door_open: bool | None
    rear_left_door_open: bool | None
    rear_right_door_open: bool | None
    bonnet_open: bool | None
    boot_open: bool | None
    charging: bool | None
    cable_connected: bool | None
    climate_on: bool | None
    latitude: float | None
    longitude: float | None
    altitude_m: float | None
    source: str
    charge_schedule: ChargeSchedule = ChargeSchedule(None, None, None)

    def sensor(self, key: str) -> Any:
        return _SENSOR_VALUES[key](self)

    def binary(self, key: str) -> bool | None:
        return _BINARY_VALUES[key](self)


def _energy(soc: float | None, pack: float) -> float | None:
    if soc is None:
        return None
    return round(soc / 100 * pack, 2)


def decode_snapshot(
    *,
    basic: Mapping[str, Any],
    charge: Mapping[str, Any] | None = None,
    gps_latitude: int | float | None = None,
    gps_longitude: int | float | None = None,
    gps_altitude: int | float | None = None,
    gps_status: int | None = None,
    status_time: int | None = None,
    pack: str,
    api_capacity_raw: int | None = None,
    source: str,
) -> Mg5Snapshot:
    """Decode one SAIC status payload into display units."""
    has_charge = charge is not None
    charge = charge or {}
    capacity = pack_kwh(pack, api_capacity_raw)
    soc = _soc(charge.get("bmsPackSOCDsp"))
    current = _pack_current_a(charge.get("bmsPackCrnt"))
    voltage = _pack_voltage_v(charge.get("bmsPackVol"))
    power = None
    if current is not None and voltage is not None:
        # Charging current is negative in this encoding. Show draw as a positive kW.
        power = round(abs(current * voltage / 1000.0), 2)
        current = round(current, 2)
        voltage = round(voltage, 2)
    last_contact = None
    if status_time:
        last_contact = datetime.fromtimestamp(int(status_time), tz=UTC)
    bms_code = charge.get("bmsChrgSts")
    return Mg5Snapshot(
        soc=soc,
        estimated_range_km=_range_km(
            charge.get("bmsEstdElecRng"),
            basic.get("fuelRangeElec"),
        ),
        odometer_km=_odometer_km(basic.get("mileage")),
        interior_c=clean_temperature(basic.get("interiorTemperature")),
        exterior_c=clean_temperature(basic.get("exteriorTemperature")),
        aux_voltage=_aux_voltage(basic.get("batteryVoltage")),
        tyre_front_left=_tyre_bar(basic.get("frontLeftTyrePressure")),
        tyre_front_right=_tyre_bar(basic.get("frontRightTyrePressure")),
        tyre_rear_left=_tyre_bar(basic.get("rearLeftTyrePressure")),
        tyre_rear_right=_tyre_bar(basic.get("rearRightTyrePressure")),
        charge_power_kw=power,
        charge_current_a=current,
        charge_voltage_v=voltage,
        remaining_charge_min=_remaining_minutes(
            charge.get("chrgngRmnngTime"),
            charge.get("chrgngRmnngTimeV"),
        ),
        target_soc=_target_soc(charge.get("bmsOnBdChrgTrgtSOCDspCmd")),
        distance_since_charge_km=_tenths(charge.get("mileageSinceLastCharge")),
        energy_since_charge_kwh=_tenths(charge.get("powerUsageSinceLastCharge")),
        battery_energy_kwh=_energy(soc, capacity),
        battery_capacity_kwh=capacity,
        last_contact=last_contact,
        locked=_locked(basic.get("lockStatus")),
        driver_door_open=_open(basic.get("driverDoor")),
        passenger_door_open=_open(basic.get("passengerDoor")),
        rear_left_door_open=_open(basic.get("rearLeftDoor")),
        rear_right_door_open=_open(basic.get("rearRightDoor")),
        bonnet_open=_open(basic.get("bonnetStatus")),
        boot_open=_open(basic.get("bootStatus")),
        charging=_is_charging(bms_code) if has_charge else None,
        cable_connected=_cable_connected(charge.get("chargingGunState"), bms_code)
        if has_charge
        else None,
        climate_on=climate_is_on(basic.get("remoteClimateStatus")),
        latitude=_gps(gps_latitude, gps_status),
        longitude=_gps(gps_longitude, gps_status),
        altitude_m=None if gps_altitude is None else float(gps_altitude),
        source=source,
        charge_schedule=decode_schedule(charge),
    )


SCHEDULE_FIELDS: tuple[str, ...] = (
    "bmsReserStHourDspCmd",
    "bmsReserStMintueDspCmd",
    "bmsReserSpHourDspCmd",
    "bmsReserSpMintueDspCmd",
    "bmsReserCtrlDspCmd",
)


def decode_schedule(charge: Mapping[str, Any] | None) -> ChargeSchedule:
    """The window the car reports in its charging management data."""
    charge = charge or {}
    return ChargeSchedule(
        start=schedule_clock(
            charge.get("bmsReserStHourDspCmd"), charge.get("bmsReserStMintueDspCmd")
        ),
        end=schedule_clock(
            charge.get("bmsReserSpHourDspCmd"), charge.get("bmsReserSpMintueDspCmd")
        ),
        mode=schedule_mode_name(charge.get("bmsReserCtrlDspCmd")),
    )


def keep_odometer(previous: Mg5Snapshot | None, current: Mg5Snapshot) -> Mg5Snapshot:
    """An odometer never runs backwards or disappears: keep the last good value."""
    if previous is None or previous.odometer_km is None:
        return current
    if current.odometer_km is None:
        return replace(current, odometer_km=previous.odometer_km)
    if current.odometer_km < previous.odometer_km:
        return replace(current, odometer_km=previous.odometer_km)
    return current


def merge_cached(previous: Mg5Snapshot | None, cached: Mg5Snapshot) -> Mg5Snapshot:
    """Keep charging fields a cached read cannot see, so we do not wipe SOC."""
    if previous is None or cached.soc is not None:
        return cached
    soc = previous.soc
    return replace(
        cached,
        soc=soc,
        charge_power_kw=previous.charge_power_kw,
        charge_current_a=previous.charge_current_a,
        charge_voltage_v=previous.charge_voltage_v,
        remaining_charge_min=previous.remaining_charge_min,
        target_soc=previous.target_soc,
        distance_since_charge_km=previous.distance_since_charge_km
        if cached.distance_since_charge_km is None
        else cached.distance_since_charge_km,
        energy_since_charge_kwh=previous.energy_since_charge_kwh,
        battery_energy_kwh=_energy(soc, cached.battery_capacity_kwh),
        charging=previous.charging,
        cable_connected=previous.cable_connected,
        charge_schedule=previous.charge_schedule,
        estimated_range_km=cached.estimated_range_km
        if cached.estimated_range_km is not None
        else previous.estimated_range_km,
    )


_SENSOR_VALUES = {
    "soc": lambda snap: snap.soc,
    "estimated_range": lambda snap: snap.estimated_range_km,
    "odometer": lambda snap: snap.odometer_km,
    "interior_temperature": lambda snap: snap.interior_c,
    "exterior_temperature": lambda snap: snap.exterior_c,
    "aux_voltage": lambda snap: snap.aux_voltage,
    "tyre_front_left": lambda snap: snap.tyre_front_left,
    "tyre_front_right": lambda snap: snap.tyre_front_right,
    "tyre_rear_left": lambda snap: snap.tyre_rear_left,
    "tyre_rear_right": lambda snap: snap.tyre_rear_right,
    "charge_power": lambda snap: snap.charge_power_kw,
    "charge_current": lambda snap: snap.charge_current_a,
    "charge_voltage": lambda snap: snap.charge_voltage_v,
    "remaining_charge": lambda snap: snap.remaining_charge_min,
    "target_soc": lambda snap: snap.target_soc,
    "distance_since_charge": lambda snap: snap.distance_since_charge_km,
    "energy_since_charge": lambda snap: snap.energy_since_charge_kwh,
    "battery_energy": lambda snap: snap.battery_energy_kwh,
    "last_contact": lambda snap: snap.last_contact,
    "reported_charging_start": lambda snap: _clock_text(snap.charge_schedule.start),
    "reported_charging_end": lambda snap: _clock_text(snap.charge_schedule.end),
    "reported_charging_schedule": lambda snap: snap.charge_schedule.mode,
}


def _clock_text(value: time | None) -> str | None:
    return None if value is None else value.strftime("%H:%M")

_BINARY_VALUES = {
    "locked": lambda snap: snap.locked,
    "driver_door": lambda snap: snap.driver_door_open,
    "passenger_door": lambda snap: snap.passenger_door_open,
    "rear_left_door": lambda snap: snap.rear_left_door_open,
    "rear_right_door": lambda snap: snap.rear_right_door_open,
    "bonnet": lambda snap: snap.bonnet_open,
    "boot": lambda snap: snap.boot_open,
    "charging": lambda snap: snap.charging,
    "charge_cable": lambda snap: snap.cable_connected,
    "climate_active": lambda snap: snap.climate_on,
}
