"""Charging switch for the MG5.

The switch follows the car. Turning it on asks the car to start, but the
state stays off until a live read says current is flowing. Start commands
are often accepted and then ignored.
"""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities([Mg5ChargingSwitch(coordinator)])


class Mg5ChargingSwitch(Mg5Entity, SwitchEntity):
    _attr_name = "Charging"
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator: Mg5Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_charging_switch"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.charging

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_charging(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_charging(False)
