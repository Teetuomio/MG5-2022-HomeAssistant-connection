"""MG5 Electric (2022) integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import mask_vin
from .const import (
    CONF_BATTERY,
    CONF_MODEL,
    CONF_SERIES,
    CONF_VIN,
    CONF_YEAR,
    CONF_MANUAL_ONLY,
    DEFAULT_BATTERY,
    DEFAULT_MANUAL_ONLY,
    DOMAIN,
)
from .coordinator import Mg5Coordinator, async_create_client

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.LOCK,
    Platform.CLIMATE,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.DEVICE_TRACKER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = await async_create_client(hass, dict(entry.data))
    coordinator = Mg5Coordinator(
        hass,
        entry,
        client,
        vin=entry.data[CONF_VIN],
        pack=entry.options.get(CONF_BATTERY, entry.data.get(CONF_BATTERY, DEFAULT_BATTERY)),
        model_name=entry.data.get(CONF_MODEL),
        model_year=entry.data.get(CONF_YEAR),
        series=entry.data.get(CONF_SERIES),
        manual_only=bool(
            entry.options.get(
                CONF_MANUAL_ONLY, entry.data.get(CONF_MANUAL_ONLY, DEFAULT_MANUAL_ONLY)
            )
        ),
    )
    try:
        await coordinator.async_config_entry_first_refresh()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        await coordinator.async_close()
        raise
    entry.async_on_unload(entry.add_update_listener(_reload))
    _LOGGER.info("MG5 %s connected", mask_vin(entry.data[CONF_VIN]))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    coordinator: Mg5Coordinator | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        await coordinator.async_close()
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
