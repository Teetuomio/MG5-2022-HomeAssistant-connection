"""Scheduled-charging mode for the MG5.

Changing the mode resends the daily window with the start and end times the
car last reported, or 22:00 to 06:00 if it has reported none. The window is
hour and minute only, with no date.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import Mg5Coordinator
from .entity import Mg5Entity
from .profile import SCHEDULE_MODES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: object,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Mg5Coordinator = hass.data[DOMAIN][entry.entry_id]  # type: ignore[attr-defined]
    async_add_entities([Mg5ChargingSchedule(coordinator)])


class Mg5ChargingSchedule(Mg5Entity, SelectEntity):
    """Disabled, charge until the end time, or charge until the target SOC."""

    _attr_translation_key = "charging_schedule"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: Mg5Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_charging_schedule"
        self._attr_options = list(SCHEDULE_MODES)

    @property
    def current_option(self) -> str | None:
        return self.coordinator.charge_schedule.mode

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_schedule(mode=option)
