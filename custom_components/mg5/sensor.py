"""Sensors for the MG5."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import Mg5Coordinator
from .entity import Mg5Entity
from .profile import SENSOR_SPECS, SensorSpec

_DEVICE_CLASS = {
    "battery": SensorDeviceClass.BATTERY,
    "temperature": SensorDeviceClass.TEMPERATURE,
    "voltage": SensorDeviceClass.VOLTAGE,
    "pressure": SensorDeviceClass.PRESSURE,
    "power": SensorDeviceClass.POWER,
    "current": SensorDeviceClass.CURRENT,
    "distance": SensorDeviceClass.DISTANCE,
    "energy": SensorDeviceClass.ENERGY,
    "energy_storage": SensorDeviceClass.ENERGY_STORAGE,
    "duration": SensorDeviceClass.DURATION,
    "timestamp": SensorDeviceClass.TIMESTAMP,
    "enum": SensorDeviceClass.ENUM,
}

_UNIT = {
    "%": PERCENTAGE,
    "°C": UnitOfTemperature.CELSIUS,
    "V": UnitOfElectricPotential.VOLT,
    "bar": UnitOfPressure.BAR,
    "kW": UnitOfPower.KILO_WATT,
    "A": UnitOfElectricCurrent.AMPERE,
    "km": UnitOfLength.KILOMETERS,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "min": UnitOfTime.MINUTES,
}

_STATE_CLASS = {
    "measurement": SensorStateClass.MEASUREMENT,
    "total_increasing": SensorStateClass.TOTAL_INCREASING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: object,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Mg5Coordinator = hass.data[DOMAIN][entry.entry_id]  # type: ignore[attr-defined]
    async_add_entities(Mg5Sensor(coordinator, spec) for spec in SENSOR_SPECS)


class Mg5Sensor(Mg5Entity, SensorEntity):
    def __init__(self, coordinator: Mg5Coordinator, spec: SensorSpec) -> None:
        super().__init__(coordinator)
        self._spec = spec
        self._attr_unique_id = f"{coordinator.vin}_{spec.key}"
        self._attr_name = spec.name
        self._attr_device_class = _DEVICE_CLASS.get(spec.device_class) if spec.device_class else None
        self._attr_native_unit_of_measurement = _UNIT.get(spec.unit) if spec.unit else None
        self._attr_state_class = _STATE_CLASS.get(spec.state_class) if spec.state_class else None
        if spec.icon:
            self._attr_icon = spec.icon
        if spec.options:
            self._attr_options = list(spec.options)
        if spec.translation_key:
            self._attr_translation_key = spec.translation_key

    @property
    def native_value(self):  # type: ignore[no-untyped-def]
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.sensor(self._spec.key)
