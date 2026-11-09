"""When to talk to the car, and how far apart commands must be.

A live status read wakes the MG5. Doing that on a short timer flattens the
12 V battery. Cached reads do not wake it. Commands are queued because the
car rejects a second instruction sent a few seconds after the first.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

CACHED_INTERVAL = 30 * 60
LIVE_INTERVAL = 5 * 60
COMMAND_GAP = 25.0
ACTIVE_FRESH_SECONDS = 20 * 60
POST_COMMAND_DELAY = 20.0
TEMP_DEBOUNCE_SECONDS = 3.0
SCHEDULE_SETTLE_SECONDS = 3.0

FetchKind = str  # "live", "cached", or "skip"


def session_is_active(
    *,
    charging: bool | None,
    climate_on: bool | None,
    last_contact: datetime | None,
    now: datetime,
) -> bool:
    """True only while a fresh status says the car is charging or conditioning."""
    if not charging and not climate_on:
        return False
    if last_contact is None:
        return False
    age = (now - last_contact).total_seconds()
    return age < ACTIVE_FRESH_SECONDS


def choose_fetch(
    *,
    now: float,
    has_snapshot: bool,
    last_cached: float | None,
    last_live: float | None,
    pending_live_at: float | None,
    active: bool,
) -> FetchKind:
    """Pick the next read. The first read is cached so setup does not wake the car."""
    if not has_snapshot:
        return "cached"
    if pending_live_at is not None and now >= pending_live_at:
        return "live"
    if active and (last_live is None or now - last_live >= LIVE_INTERVAL):
        return "live"
    last_quiet = last_cached if last_cached is not None else last_live
    if last_quiet is None or now - last_quiet >= CACHED_INTERVAL:
        return "cached"
    return "skip"


def needs_initial_live(*, soc: float | None, tried: bool) -> bool:
    """One live read after setup, so SOC exists, and not again if it failed."""
    return soc is None and not tried


class CommandQueue:
    """Run car commands one at a time, at least COMMAND_GAP seconds apart."""

    def __init__(
        self,
        *,
        min_gap: float = COMMAND_GAP,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[Any]] | None = None,
    ) -> None:
        self._min_gap = min_gap
        self._clock = clock or _monotonic
        self._sleep = sleep or asyncio.sleep
        self._lock = asyncio.Lock()
        self._last: float | None = None

    async def run(
        self,
        name: str,
        action: Callable[[], Awaitable[Any]],
        on_failure: Callable[[str, BaseException], None],
    ) -> Any:
        async with self._lock:
            if self._last is not None:
                wait = self._min_gap - (self._clock() - self._last)
                if wait > 0:
                    await self._sleep(wait)
            try:
                result = await action()
            except Exception as err:
                self._last = self._clock()
                on_failure(name, err)
                raise
            self._last = self._clock()
            return result


def _monotonic() -> float:
    return time.monotonic()


class ExpectedValue:
    """Hold a command result until the car reports it, then drop it.

    Charging is deliberately not an expected value. Start is unreliable, so
    the switch stays where the car last reported until a live read says otherwise.
    """

    def __init__(self) -> None:
        self._value: Any = None
        self._until = 0.0
        self._active = False

    def set(self, value: Any, now: float, ttl: float = 90.0) -> None:
        self._value = value
        self._until = now + ttl
        self._active = True

    def clear(self) -> None:
        self._active = False
        self._value = None

    def resolve(self, actual: Any, now: float) -> Any:
        if not self._active or now >= self._until:
            self.clear()
            return actual
        if actual == self._value:
            self.clear()
            return actual
        return self._value
