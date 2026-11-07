"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import Mg5Coordinator


class Mg5Entity(CoordinatorEntity[Mg5Coordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: Mg5Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.vin)},
            manufacturer=MANUFACTURER,
            model=coordinator.model_name or MODEL,
            name=f"MG5 {coordinator.vin[-4:]}",
            sw_version=coordinator.model_year,
            hw_version=coordinator.series,
        )
