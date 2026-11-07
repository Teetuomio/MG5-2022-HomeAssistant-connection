"""The climate bytes sent for a 2022 MG5."""

import base64

from saic_ismart_client_ng.api.vehicle.climate import SaicVehicleClimateApi
from saic_ismart_client_ng.api.vehicle.schema import RvcParamsId

from custom_components.mg5.profile import climate_on_command


def test_22c_omits_the_compressor_byte(run):
    captured: dict = {}

    async def capture(body, vin):
        captured["body"] = body
        captured["vin"] = vin
        return None

    api = SaicVehicleClimateApi.__new__(SaicVehicleClimateApi)
    api.send_vehicle_control_command = capture  # type: ignore[method-assign]
    command = climate_on_command(22)

    run(api.control_climate("TESTVIN0000000000", **command.as_kwargs()))

    params = {
        item.paramId: base64.b64decode(item.paramValue)
        for item in captured["body"].rvcParams
    }
    assert params[RvcParamsId.FAN_SPEED.value] == b"\x02"
    assert params[RvcParamsId.TEMPERATURE.value] == b"\x08"
    assert RvcParamsId.AC_ON_OFF.value not in params
    assert captured["body"].rvcReqType == "6"
    assert captured["vin"] == "TESTVIN0000000000"
