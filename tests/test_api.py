"""Client configuration, without contacting MG."""

from types import SimpleNamespace

from saic_ismart_client_ng.exceptions import SaicApiException

from custom_components.mg5.api import (
    REGION_URIS,
    build_configuration,
    charge_mapping,
    mask_vin,
    public_error,
)


def test_region_and_phone_country_code():
    email = build_configuration(
        "driver@example.com",
        "not-a-real-password",
        account_type="email",
        region="eu",
        country_code=None,
    )
    assert email.base_uri == REGION_URIS["eu"]
    assert email.username_is_email is True
    assert email.region == "eu"

    phone = build_configuration(
        "401234567",
        "not-a-real-password",
        account_type="phone",
        region="au",
        country_code="+61",
    )
    assert phone.base_uri == REGION_URIS["au"]
    assert phone.username_is_email is False
    assert phone.phone_country_code == "61"


def test_public_error_drops_raw_bodies():
    assert public_error(RuntimeError("access_token=secret")) == (
        "MG iSmart rejected the request"
    )
    safe = public_error(
        SaicApiException("The remote control instruction failed", return_code=4)
    )
    assert safe.startswith("return code: 4")
    assert "secret" not in safe


def test_charge_fields_from_both_blocks():
    resp = SimpleNamespace(
        rvsChargeStatus=SimpleNamespace(
            chargingGunState=0,
            powerUsageSinceLastCharge=10,
            totalBatteryCapacity=725,
        ),
        chrgMgmtData=SimpleNamespace(
            bmsPackSOCDsp=965,
            totalBatteryCapacity=725,
        ),
    )
    mapped = charge_mapping(resp)
    assert mapped["bmsPackSOCDsp"] == 965
    assert mapped["chargingGunState"] == 0
    assert mapped["powerUsageSinceLastCharge"] == 10


def test_vin_is_masked():
    assert mask_vin("LSJEXAMPLE0001234") == "…1234"
    assert "LSJEXAMPLE" not in mask_vin("LSJEXAMPLE0001234")
