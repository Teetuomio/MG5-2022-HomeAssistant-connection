"""Vehicle location for the MG5."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
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
    async_add_entities([Mg5Tracker(coordinator)])


class Mg5Tracker(Mg5Entity, TrackerEntity):
    _attr_name = "Location"
    _attr_icon = "mdi:car"

    def __init__(self, coordinator: Mg5Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_location"

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.latitude

    @property
    def longitude(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.longitude

    @property
    def extra_state_attributes(self) -> dict[str, float] | None:
        if self.coordinator.data is None or self.coordinator.data.altitude_m is None:
            return None
        return {"altitude": self.coordinator.data.altitude_m}
