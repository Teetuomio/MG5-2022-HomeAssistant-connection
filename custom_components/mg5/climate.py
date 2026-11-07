"""Cabin climate for the MG5.

Only heat/cool and off. There is no fan slider and no separate heat mode:
the car heats or cools toward the setpoint when the compressor byte is left
out. Status 2 means the system is running.
"""

from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import Mg5Coordinator
from .entity import Mg5Entity
from .profile import TEMP_MAX, TEMP_MIN, clamp_temperature, hvac_mode_name, temperature_action


async def async_setup_entry(
    hass: HomeAssistant,
    entry: object,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: Mg5Coordinator = hass.data[DOMAIN][entry.entry_id]  # type: ignore[attr-defined]
    async_add_entities([Mg5Climate(coordinator)])


class Mg5Climate(Mg5Entity, RestoreEntity, ClimateEntity):
    _attr_name = "Climate"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_min_temp = TEMP_MIN
    _attr_max_temp = TEMP_MAX
    _attr_target_temperature_step = 1
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: Mg5Coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_climate"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        raw = last.attributes.get(ATTR_TEMPERATURE)
        if raw is None:
            return
        try:
            self.coordinator.desired_temperature = clamp_temperature(float(raw))
        except (TypeError, ValueError):
            return

    @property
    def hvac_mode(self) -> HVACMode | None:
        name = hvac_mode_name(climate_on=self.coordinator.climate_on)
        if name == "heat_cool":
            return HVACMode.HEAT_COOL
        if name == "off":
            return HVACMode.OFF
        return None

    @property
    def current_temperature(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.interior_c

    @property
    def target_temperature(self) -> float | None:
        return float(self.coordinator.desired_temperature)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_stop_climate()
            return
        if hvac_mode == HVACMode.HEAT_COOL:
            await self.coordinator.async_start_climate()
            return
        raise HomeAssistantError("This MG5 only supports heat/cool or off")

    async def async_set_temperature(self, **kwargs: object) -> None:
        raw = kwargs.get(ATTR_TEMPERATURE)
        if raw is None:
            return
        self.coordinator.desired_temperature = clamp_temperature(float(raw))  # type: ignore[arg-type]
        self.async_write_ha_state()
        running = self.hvac_mode == HVACMode.HEAT_COOL
        if temperature_action(climate_on=running) == "store":
            self.coordinator.cancel_climate_debounce()
            return
        self.coordinator.schedule_climate_debounce()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT_COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        raise HomeAssistantError("The 2022 MG5 has no remote fan control")

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        raise HomeAssistantError("The 2022 MG5 has no remote climate presets")
