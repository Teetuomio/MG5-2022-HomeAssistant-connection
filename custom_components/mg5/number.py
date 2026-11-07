"""Charge limit for the MG5."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import Mg5Coordinator
from .entity import Mg5Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: object,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Mg5Coordinator = hass.data[DOMAIN][entry.entry_id]  # type: ignore[attr-defined]
    async_add_entities([Mg5ChargeLimit(coordinator)])


class Mg5ChargeLimit(Mg5Entity, NumberEntity):
    _attr_name = "Charge limit"
    _attr_icon = "mdi:battery-charging-80"
    _attr_native_min_value = 40
    _attr_native_max_value = 100
    _attr_native_step = 10
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: Mg5Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_charge_limit"

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.target_soc
        if value is None:
            return None
        return float(value)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_target_soc(int(value))
