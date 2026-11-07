"""Door lock for the MG5."""

from __future__ import annotations

from homeassistant.components.lock import LockEntity
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
    async_add_entities([Mg5Lock(coordinator)])


class Mg5Lock(Mg5Entity, LockEntity):
    _attr_name = "Lock"

    def __init__(self, coordinator: Mg5Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_lock"

    @property
    def is_locked(self) -> bool | None:
        return self.coordinator.locked

    async def async_lock(self, **kwargs: object) -> None:
        await self.coordinator.async_lock()

    async def async_unlock(self, **kwargs: object) -> None:
        await self.coordinator.async_unlock()
