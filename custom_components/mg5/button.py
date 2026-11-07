"""Buttons for the MG5."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    async_add_entities([Mg5FindCarButton(coordinator), Mg5RefreshButton(coordinator)])


class Mg5FindCarButton(Mg5Entity, ButtonEntity):
    _attr_name = "Find car"
    _attr_icon = "mdi:car-search"

    def __init__(self, coordinator: Mg5Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_find_car"

    async def async_press(self) -> None:
        await self.coordinator.async_find_car()


class Mg5RefreshButton(Mg5Entity, ButtonEntity):
    _attr_name = "Refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: Mg5Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_refresh"

    async def async_press(self) -> None:
        await self.coordinator.async_request_live()
