"""Binary sensors for the MG5."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import Mg5Coordinator
from .entity import Mg5Entity
from .profile import BINARY_SPECS, BinarySpec

_DEVICE_CLASS = {
    "door": BinarySensorDeviceClass.DOOR,
    "battery_charging": BinarySensorDeviceClass.BATTERY_CHARGING,
    "plug": BinarySensorDeviceClass.PLUG,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: object,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Mg5Coordinator = hass.data[DOMAIN][entry.entry_id]  # type: ignore[attr-defined]
    async_add_entities(Mg5BinarySensor(coordinator, spec) for spec in BINARY_SPECS)


class Mg5BinarySensor(Mg5Entity, BinarySensorEntity):
    def __init__(self, coordinator: Mg5Coordinator, spec: BinarySpec) -> None:
        super().__init__(coordinator)
        self._spec = spec
        self._attr_unique_id = f"{coordinator.vin}_{spec.key}"
        self._attr_name = spec.name
        if spec.device_class:
            self._attr_device_class = _DEVICE_CLASS[spec.device_class]
        if spec.icon:
            self._attr_icon = spec.icon

    @property
    def is_on(self) -> bool | None:
        if self._spec.key == "locked":
            return self.coordinator.locked
        if self._spec.key == "climate_active":
            return self.coordinator.climate_on
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.binary(self._spec.key)
