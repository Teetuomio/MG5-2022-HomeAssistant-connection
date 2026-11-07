"""Data update coordinator.

Reads use SAIC's cached status unless something the car is doing right now
needs a live wake: the first load of battery data, a refresh, a command, or
an active charge / climate session.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from functools import partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    Mg5Client,
    charge_mapping,
    gps_parts,
    is_auth_error,
    is_connection_error,
    mask_vin,
    public_error,
    public_vars,
)
from .const import (
    CONF_ACCOUNT_TYPE,
    CONF_COUNTRY_CODE,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_USERNAME,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
    EVENT_COMMAND_FAILED,
)
from .profile import Mg5Snapshot, decode_snapshot, merge_cached
from .schedule import (
    POST_COMMAND_DELAY,
    TEMP_DEBOUNCE_SECONDS,
    CommandQueue,
    ExpectedValue,
    choose_fetch,
    needs_initial_live,
    session_is_active,
)

_LOGGER = logging.getLogger(__name__)

_CHECK_EVERY = timedelta(seconds=30)


async def async_create_client(hass: HomeAssistant, data: dict[str, Any]) -> Mg5Client:
    """Build the client in the executor; creating its HTTPS pool reads CA files."""
    return await hass.async_add_executor_job(
        partial(
            Mg5Client,
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            account_type=data[CONF_ACCOUNT_TYPE],
            region=data[CONF_REGION],
            country_code=data.get(CONF_COUNTRY_CODE) or None,
        )
    )


class Mg5Coordinator(DataUpdateCoordinator[Mg5Snapshot]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: Mg5Client,
        *,
        vin: str,
        pack: str,
        model_name: str | None,
        model_year: str | None,
        series: str | None,
        manual_only: bool = False,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {mask_vin(vin)}",
            update_interval=_CHECK_EVERY,
            always_update=False,
        )
        self._client = client
        self.vin = vin
        self.pack = pack
        self.model_name = model_name
        self.model_year = model_year
        self.series = series
        self.manual_only = manual_only
        self.desired_temperature = DEFAULT_TARGET_TEMP
        self._queue = CommandQueue()
        self._api_lock = asyncio.Lock()
        self._last_cached: float | None = None
        self._last_live: float | None = None
        self._pending_live_at: float | None = None
        self._tried_initial_live = False
        self._live_read_unsub: Any = None
        self._debounce_unsub: Any = None
        self._closed = False
        self._lock_expect = ExpectedValue()
        self._climate_expect = ExpectedValue()
        self._target_expect = ExpectedValue()

    async def async_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_live_read()
        self.cancel_climate_debounce()
        await self._client.close()

    def _cancel_live_read(self) -> None:
        if self._live_read_unsub is not None:
            self._live_read_unsub()
            self._live_read_unsub = None

    def cancel_climate_debounce(self) -> None:
        if self._debounce_unsub is not None:
            self._debounce_unsub()
            self._debounce_unsub = None

    def schedule_climate_debounce(self) -> None:
        """One climate command after the slider settles, not one per degree."""
        self.cancel_climate_debounce()

        @callback
        def _fire(_now: datetime) -> None:
            self._debounce_unsub = None
            self.hass.async_create_task(self._async_start_climate_logged())

        self._debounce_unsub = async_call_later(
            self.hass, TEMP_DEBOUNCE_SECONDS, _fire
        )

    async def _async_update_data(self) -> Mg5Snapshot:
        now = time.monotonic()
        active = False
        if self.data is not None:
            active = session_is_active(
                charging=self.data.charging,
                climate_on=self.climate_on,
                last_contact=self.data.last_contact,
                now=datetime.now(tz=UTC),
            )
        kind = choose_fetch(
            now=now,
            has_snapshot=self.data is not None,
            last_cached=self._last_cached,
            last_live=self._last_live,
            pending_live_at=self._pending_live_at,
            active=active,
            manual_only=self.manual_only,
        )
        if kind == "skip" and self.data is not None:
            return self.data
        # Stamp the attempt, not the success, so a failing live read is not
        # retried on every 30 s tick.
        self._stamp(kind)
        try:
            snapshot = await self._fetch(kind)
        except Exception as err:
            if is_auth_error(err):
                raise ConfigEntryAuthFailed(public_error(err)) from err
            if self.data is not None:
                _LOGGER.warning("MG5 update failed, keeping last data: %s", public_error(err))
                return self.data
            if kind == "live" or is_connection_error(err):
                raise UpdateFailed(public_error(err)) from err
            # Cached status was refused but MG answered. Try one live read.
            self._stamp("live")
            try:
                snapshot = await self._fetch("live")
            except Exception as live_err:
                if is_auth_error(live_err):
                    raise ConfigEntryAuthFailed(public_error(live_err)) from live_err
                raise UpdateFailed(public_error(live_err)) from live_err
        return self._maybe_arm_initial_live(snapshot)

    def _stamp(self, kind: str) -> None:
        now = time.monotonic()
        self._last_cached = now
        if kind == "live":
            self._last_live = now
            self._pending_live_at = None
            self._tried_initial_live = True

    def _maybe_arm_initial_live(self, snapshot: Mg5Snapshot) -> Mg5Snapshot:
        if needs_initial_live(soc=snapshot.soc, tried=self._tried_initial_live):
            self._pending_live_at = time.monotonic()
            self._schedule_live_read(5)
        return snapshot

    def _schedule_live_read(self, delay: float) -> None:
        self._cancel_live_read()

        @callback
        def _fire(_now: datetime) -> None:
            self._live_read_unsub = None
            # Timers can fire marginally early; the read is due now regardless.
            if self._pending_live_at is not None:
                self._pending_live_at = time.monotonic()
            self.hass.async_create_task(self.async_request_refresh())

        self._live_read_unsub = async_call_later(self.hass, delay, _fire)

    async def async_request_live(self) -> None:
        """Wake the car once and read it. Used by the refresh button."""
        self._pending_live_at = time.monotonic()
        await self.async_request_refresh()

    async def _fetch(self, kind: str) -> Mg5Snapshot:
        async with self._api_lock:
            if kind == "live":
                status = await self._client.live_status(self.vin)
                try:
                    charging = await self._client.charging(self.vin)
                except Exception as err:
                    _LOGGER.warning(
                        "MG5 charging data was not returned: %s", public_error(err)
                    )
                    charging = None
                snapshot = self._decode(status, charging, source="live")
                if charging is None:
                    snapshot = merge_cached(self.data, snapshot)
                return snapshot
            status = await self._client.cached_status(self.vin)
            snapshot = self._decode(status, None, source="cached")
            return merge_cached(self.data, snapshot)

    def _decode(self, status: Any, charging: Any, *, source: str) -> Mg5Snapshot:
        basic = public_vars(getattr(status, "basicVehicleStatus", None))
        charge = charge_mapping(charging) if charging is not None else None
        lat, lon, alt, gps_status = gps_parts(status)
        capacity_raw = None if charge is None else charge.get("totalBatteryCapacity")
        return decode_snapshot(
            basic=basic,
            charge=charge,
            gps_latitude=lat,
            gps_longitude=lon,
            gps_altitude=alt,
            gps_status=gps_status,
            status_time=getattr(status, "statusTime", None),
            pack=self.pack,
            api_capacity_raw=capacity_raw,
            source=source,
        )

    def _fail(self, name: str, err: BaseException) -> None:
        self.hass.bus.async_fire(
            EVENT_COMMAND_FAILED,
            {"source": name, "error": public_error(err)},
        )

    async def _command(self, name: str, action: Any) -> Any:
        if self._closed:
            raise HomeAssistantError("MG5 is shutting down")

        async def _run() -> Any:
            async with self._api_lock:
                return await action()

        try:
            result = await self._queue.run(name, _run, self._fail)
        except Exception as err:
            raise HomeAssistantError(
                f"{name} was rejected by the car: {public_error(err)}"
            ) from err
        self._pending_live_at = time.monotonic() + POST_COMMAND_DELAY
        self._schedule_live_read(POST_COMMAND_DELAY)
        return result

    @property
    def climate_on(self) -> bool | None:
        actual = None if self.data is None else self.data.climate_on
        return self._climate_expect.resolve(actual, time.monotonic())

    @property
    def locked(self) -> bool | None:
        actual = None if self.data is None else self.data.locked
        return self._lock_expect.resolve(actual, time.monotonic())

    @property
    def target_soc(self) -> int | None:
        actual = None if self.data is None else self.data.target_soc
        return self._target_expect.resolve(actual, time.monotonic())

    def _expect(self, holder: ExpectedValue, value: Any) -> None:
        holder.set(value, time.monotonic())
        self.async_update_listeners()

    async def async_lock(self) -> None:
        await self._command("lock", lambda: self._client.lock(self.vin))
        self._expect(self._lock_expect, True)

    async def async_unlock(self) -> None:
        await self._command("unlock", lambda: self._client.unlock(self.vin))
        self._expect(self._lock_expect, False)

    async def async_start_climate(self) -> None:
        self.cancel_climate_debounce()

        async def _start() -> None:
            # Read the setpoint when the command actually leaves the queue.
            await self._client.start_climate(self.vin, self.desired_temperature)

        await self._command("climate", _start)
        self._expect(self._climate_expect, True)

    async def _async_start_climate_logged(self) -> None:
        try:
            await self.async_start_climate()
        except HomeAssistantError as err:
            _LOGGER.warning("MG5 climate temperature change failed: %s", err)

    async def async_stop_climate(self) -> None:
        self.cancel_climate_debounce()
        await self._command("climate", lambda: self._client.stop_climate(self.vin))
        self._expect(self._climate_expect, False)

    async def async_find_car(self) -> None:
        await self._command("find_car", lambda: self._client.find_car(self.vin))

    async def async_set_target_soc(self, percent: int) -> None:
        async def _set() -> int:
            return await self._client.set_target_soc(self.vin, percent)

        applied = await self._command("charge_limit", _set)
        self._expect(self._target_expect, applied)

    async def async_set_charging(self, start: bool) -> None:
        # No local override. A start the car ignores must stay off.
        await self._command(
            "charging",
            lambda: self._client.set_charging(self.vin, start=start),
        )
