"""Polling policy and the command gap."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.mg5.schedule import (
    CACHED_INTERVAL,
    COMMAND_GAP,
    LIVE_INTERVAL,
    CommandQueue,
    ExpectedValue,
    choose_fetch,
    needs_initial_live,
    session_is_active,
)


def test_first_read_is_cached_and_live_is_reserved_for_a_reason():
    assert (
        choose_fetch(
            now=0,
            has_snapshot=False,
            last_cached=None,
            last_live=None,
            pending_live_at=None,
            active=False,
        )
        == "cached"
    )
    assert (
        choose_fetch(
            now=10,
            has_snapshot=True,
            last_cached=0,
            last_live=None,
            pending_live_at=None,
            active=False,
        )
        == "skip"
    )
    assert (
        choose_fetch(
            now=CACHED_INTERVAL,
            has_snapshot=True,
            last_cached=0,
            last_live=None,
            pending_live_at=None,
            active=False,
        )
        == "cached"
    )
    assert (
        choose_fetch(
            now=50,
            has_snapshot=True,
            last_cached=0,
            last_live=None,
            pending_live_at=100,
            active=False,
        )
        == "skip"
    )
    assert (
        choose_fetch(
            now=100,
            has_snapshot=True,
            last_cached=0,
            last_live=None,
            pending_live_at=100,
            active=False,
        )
        == "live"
    )
    assert (
        choose_fetch(
            now=LIVE_INTERVAL,
            has_snapshot=True,
            last_cached=LIVE_INTERVAL,
            last_live=0,
            pending_live_at=None,
            active=True,
        )
        == "live"
    )


def test_stale_climate_flag_does_not_keep_waking_the_car():
    now = datetime(2026, 10, 26, tzinfo=UTC)
    assert (
        session_is_active(
            charging=False,
            climate_on=True,
            last_contact=now - timedelta(hours=2),
            now=now,
        )
        is False
    )
    assert (
        session_is_active(
            charging=True,
            climate_on=False,
            last_contact=now - timedelta(minutes=1),
            now=now,
        )
        is True
    )
    assert needs_initial_live(soc=None, tried=False) is True
    assert needs_initial_live(soc=96.5, tried=False) is False
    assert needs_initial_live(soc=None, tried=True) is False


def test_commands_wait_25_seconds_and_a_rejection_is_reported(run):
    clock = {"now": 100.0}
    sleeps: list[float] = []
    events: list[tuple[str, str]] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    queue = CommandQueue(min_gap=COMMAND_GAP, clock=lambda: clock["now"], sleep=sleep)

    async def ok():
        return "ok"

    async def rejected():
        raise RuntimeError(
            "return code: 4, message: The remote control instruction failed"
        )

    async def scenario():
        await queue.run("lock", ok, lambda name, err: events.append((name, str(err))))
        with pytest.raises(RuntimeError, match="return code: 4"):
            await queue.run(
                "climate",
                rejected,
                lambda name, err: events.append((name, str(err))),
            )
        await queue.run("unlock", ok, lambda name, err: events.append((name, str(err))))

    run(scenario())
    assert sleeps == [COMMAND_GAP, COMMAND_GAP]
    assert events == [
        ("climate", "return code: 4, message: The remote control instruction failed")
    ]


def test_expected_state_clears_when_the_car_agrees():
    expected = ExpectedValue()
    expected.set(True, now=0, ttl=90)
    assert expected.resolve(False, now=10) is True
    assert expected.resolve(True, now=20) is True
    assert expected.resolve(False, now=30) is False


def test_manual_mode_reads_nothing_on_its_own():
    """Manual mode: no background polls, even when the cached status is stale."""
    assert (
        choose_fetch(
            now=CACHED_INTERVAL * 10,
            has_snapshot=True,
            last_cached=0,
            last_live=0,
            pending_live_at=None,
            active=True,
            manual_only=True,
        )
        == "skip"
    )
    # The first read still happens, so the entities are not empty after setup.
    assert (
        choose_fetch(
            now=0,
            has_snapshot=False,
            last_cached=None,
            last_live=None,
            pending_live_at=None,
            active=False,
            manual_only=True,
        )
        == "cached"
    )
    # Refresh and post-command reads still work.
    assert (
        choose_fetch(
            now=10,
            has_snapshot=True,
            last_cached=0,
            last_live=0,
            pending_live_at=5,
            active=False,
            manual_only=True,
        )
        == "live"
    )
