# Changelog

## 0.3.0 — 2026-11-09

### Added

- Scheduled charging, as in the MG iSmart app: **Charging start** and **Charging end** time entities and a **Charging schedule** select (Disabled / Until end time / Until target SOC). The window is hour and minute only and repeats daily; the car has no date or weekday for it.
- Read-only **Reported charging start**, **Reported charging end** and **Reported charging schedule** sensors with what the car last reported.

### Changed

- The first schedule can be set from Home Assistant even if the car reports no window (or mode 0): unreported parts are filled as mode Disabled and 22:00–06:00. Nothing is sent until you change the start, end or mode.
- Changing the start, end or mode sends the whole window once. Edits made within 3 seconds of each other are sent as one command, and choosing what the car already has sends nothing. Commands still go through the 25-second queue and are followed by one live read.
- If a live charging read has none of the schedule fields, the integration logs the fields the car did send, once per start, so the real field names can be checked.

No existing entity, unique id, polling interval or command-queue behaviour changed.

## 0.2.1 — 2026-11-07

### Fixed

- The odometer ignores the sentinel and absurd mileage values the iSmart cloud sometimes returns (a raw -128 became -12.8 km), and keeps the last good reading instead of running backwards.

## 0.2.0 — 2026-11-07

### Added

- First release for the 2022 MG5 Electric (EP21/EP22): lock, cabin climate with the MG5 command bytes, charge limit, charging switch, find car, refresh, status sensors and location.
- Cached status reads by default, a live read only when needed, and remote commands queued at least 25 seconds apart.
