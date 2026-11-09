"""Scheduled-charging start and end times for the MG5.

The car keeps one daily window as hour and minute. There is no date or
weekday: the window repeats every day until it is changed or disabled.
"""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
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
    async_add_entities([Mg5ChargingStart(coordinator), Mg5ChargingEnd(coordinator)])


class Mg5ChargingStart(Mg5Entity, TimeEntity):
    """Daily start of scheduled charging. Hour and minute only, no date."""

    _attr_translation_key = "charging_start"
    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator: Mg5Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_charging_start"

    @property
    def native_value(self) -> time | None:
        return self.coordinator.charge_schedule.start

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set_schedule(start=value)


class Mg5ChargingEnd(Mg5Entity, TimeEntity):
    """Daily end of scheduled charging. Hour and minute only, no date."""

    _attr_translation_key = "charging_end"
    _attr_icon = "mdi:clock-end"

    def __init__(self, coordinator: Mg5Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_charging_end"

    @property
    def native_value(self) -> time | None:
        return self.coordinator.charge_schedule.end

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set_schedule(end=value)
