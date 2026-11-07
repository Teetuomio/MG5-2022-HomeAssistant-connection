"""Thin client around the MG iSmart API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saic_ismart_client_ng import SaicApi
from saic_ismart_client_ng.api.vehicle_charging.schema import TargetBatteryCode
from saic_ismart_client_ng.exceptions import SaicApiException, SaicLogoutException
from saic_ismart_client_ng.model import (
    MG_AU_BASE_URI,
    MG_EU_BASE_URI,
    MG_TR_BASE_URI,
    SaicApiConfiguration,
)

from .profile import ClimateCommand, climate_off_command, climate_on_command

READ_TIMEOUT = 45.0

_PRESETS = {
    "eu": SaicApiConfiguration.mg_eu,
    "au": SaicApiConfiguration.mg_au,
    "tr": SaicApiConfiguration.mg_tr,
}

REGION_URIS = {
    "eu": MG_EU_BASE_URI,
    "au": MG_AU_BASE_URI,
    "tr": MG_TR_BASE_URI,
}


def mask_vin(vin: str) -> str:
    if len(vin) < 4:
        return "****"
    return f"…{vin[-4:]}"


def public_error(err: BaseException) -> str:
    """A message safe to show and to log. Drops raw HTTP bodies."""
    text = str(err).strip()
    if text.startswith("return code:"):
        return text
    if is_connection_error(err):
        return "MG iSmart could not be reached"
    return "MG iSmart rejected the request"


def is_connection_error(err: BaseException) -> bool:
    """The client wraps network failures as return code 500, not a login error."""
    if isinstance(err, (TimeoutError, OSError)):
        return True
    if isinstance(err, SaicApiException) and "failed unexpectedly" in str(err):
        return True
    return isinstance(err.__cause__, (TimeoutError, OSError)) or (
        type(err.__cause__).__module__.startswith("httpx")
        if err.__cause__ is not None
        else False
    )


def is_auth_error(err: BaseException) -> bool:
    """A bad password or an expired account, which needs a new password."""
    if isinstance(err, SaicLogoutException):
        return True
    text = str(err).lower()
    return "credentials" in text or "password" in text


def build_configuration(
    username: str,
    password: str,
    *,
    account_type: str,
    region: str,
    country_code: str | None,
) -> SaicApiConfiguration:
    try:
        preset = _PRESETS[region]
    except KeyError as err:
        msg = f"Unsupported MG region: {region}"
        raise ValueError(msg) from err
    kwargs: dict[str, Any] = {"read_timeout": READ_TIMEOUT}
    if account_type == "phone":
        if not country_code:
            raise ValueError("A country code is required for a phone account")
        kwargs["username_is_email"] = False
        kwargs["phone_country_code"] = country_code.removeprefix("+")
    elif account_type != "email":
        msg = f"Unsupported account type: {account_type}"
        raise ValueError(msg)
    return preset(username, password, **kwargs)


@dataclass(frozen=True)
class VehicleInfo:
    vin: str
    model_name: str | None
    model_year: str | None
    series: str | None
    color: str | None

    @property
    def label(self) -> str:
        name = self.model_name or "MG5"
        year = f" {self.model_year}" if self.model_year else ""
        return f"{name}{year} ({self.vin[-4:]})"


def public_vars(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    return {
        key: value
        for key, value in vars(obj).items()
        if not key.startswith("_")
    }


def charge_mapping(resp: Any) -> dict[str, Any]:
    """Merge BMS management data with the charge summary.

    Energy since charge and the plug state live on the summary. SOC, target
    and pack voltage live on the management object, which wins on a clash.
    """
    data = public_vars(getattr(resp, "rvsChargeStatus", None))
    data.update(public_vars(getattr(resp, "chrgMgmtData", None)))
    return data


def gps_parts(status: Any) -> tuple[Any, Any, Any, Any]:
    gps = getattr(status, "gpsPosition", None)
    way = getattr(gps, "wayPoint", None) if gps is not None else None
    position = getattr(way, "position", None) if way is not None else None
    return (
        getattr(position, "latitude", None) if position is not None else None,
        getattr(position, "longitude", None) if position is not None else None,
        getattr(position, "altitude", None) if position is not None else None,
        getattr(gps, "gpsStatus", None) if gps is not None else None,
    )


class Mg5Client:
    """One signed-in iSmart session."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        account_type: str,
        region: str,
        country_code: str | None,
    ) -> None:
        self._api = SaicApi(
            build_configuration(
                username,
                password,
                account_type=account_type,
                region=region,
                country_code=country_code,
            )
        )

    async def close(self) -> None:
        await self._api.close()

    async def _call(self, method: Any, *args: Any, **kwargs: Any) -> Any:
        if not self._api.is_logged_in:
            await self._api.login()
        try:
            return await method(*args, **kwargs)
        except SaicLogoutException:
            await self._api.login()
            return await method(*args, **kwargs)

    async def list_vehicles(self) -> list[VehicleInfo]:
        resp = await self._call(self._api.vehicle_list)
        vehicles: list[VehicleInfo] = []
        for item in resp.vinList:
            if not item.vin:
                continue
            vehicles.append(
                VehicleInfo(
                    vin=item.vin,
                    model_name=item.modelName,
                    model_year=item.modelYear,
                    series=item.series,
                    color=item.colorName,
                )
            )
        return vehicles

    async def cached_status(self, vin: str) -> Any:
        return await self._call(self._api.get_vehicle_status_cached, vin)

    async def live_status(self, vin: str) -> Any:
        return await self._call(self._api.get_vehicle_status, vin)

    async def charging(self, vin: str) -> Any:
        return await self._call(self._api.get_vehicle_charging_management_data, vin)

    async def lock(self, vin: str) -> None:
        await self._call(self._api.lock_vehicle, vin)

    async def unlock(self, vin: str) -> None:
        await self._call(self._api.unlock_vehicle, vin)

    async def start_climate(self, vin: str, celsius: float) -> ClimateCommand:
        command = climate_on_command(celsius)
        await self._call(self._api.control_climate, vin, **command.as_kwargs())
        return command

    async def stop_climate(self, vin: str) -> ClimateCommand:
        command = climate_off_command()
        await self._call(self._api.stop_ac, vin)
        return command

    async def find_car(self, vin: str) -> None:
        await self._call(
            self._api.control_find_my_car,
            vin,
            should_stop=False,
            with_horn=True,
            with_lights=True,
        )

    async def set_target_soc(self, vin: str, percent: int) -> int:
        try:
            code = TargetBatteryCode.from_percentage(int(percent))
        except ValueError as err:
            raise SaicApiException(str(err)) from err
        await self._call(self._api.set_target_battery_soc, vin, code)
        return code.percentage

    async def set_charging(self, vin: str, *, start: bool) -> None:
        await self._call(self._api.control_charging, vin, stop_charging=not start)
