"""Tests for Sync Energy detection and the Sync-specific vendor keys.

A Sync charger must work without the user editing any file: detection runs on
the reported vendor and model family, and each Sync-specific entity is offered only when the charger returned its key.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.syncenergy_ocpp.chargepoint import _model_family
from custom_components.syncenergy_ocpp.const import (
    CONF_CPID,
    CONF_CPIDS,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
    SYNCEV_VENDOR_KEYS,
)
from custom_components.syncenergy_ocpp.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.syncenergy_ocpp.enums import HAChargerDetails as cdet, Profiles
from custom_components.syncenergy_ocpp.ocppv16 import ChargePoint as ChargePointV16

from .const import MOCK_CONFIG_CP, MOCK_CONFIG_CS


def _metric(value):
    metric = MagicMock()
    metric.value = value
    return metric


def _charge_point(vendor=None, model=None):
    """Build a 1.6 charge point with only what detection reads."""
    cp = object.__new__(ChargePointV16)
    cp.id = "CP_TEST"
    cp._metrics = {
        (0, cdet.vendor.value): _metric(vendor),
        (0, cdet.model.value): _metric(model),
    }
    cp.vendor_keys = set()
    return cp


@pytest.mark.parametrize(
    ("model", "family"),
    [
        ("EVSC7S", "EVSC7S"),
        ("evwc2t7g-03", "EVWC2T7G"),
        ("EVT77G-02", "EVT77G"),
        ("EVWC2T7GG", "EVWC2T7GG"),
        (" EVL7PS ", "EVL7PS"),
        ("AB-CD", "AB-CD"),  # a non-numeric suffix is part of the name
        ("-03", "-03"),
        ("", ""),
        (None, ""),
    ],
)
def test_model_family_drops_only_a_numeric_revision(model, family):
    """Sync part numbers carry a "-NN" revision that the model list omits."""
    assert _model_family(model) == family


@pytest.mark.parametrize(
    ("vendor", "model", "expected"),
    [
        ("Sync Energy", "ANYTHING", True),
        ("Wallbox", "EVWC2T7G-02", True),  # model fallback, suffix ignored
        ("Wallbox", "EVWC2T7G", True),
        (None, "EVSC7S", True),
        ("Wallbox", "Pulsar", False),
        (None, None, False),
    ],
)
def test_auto_detects_on_vendor_then_model_family(vendor, model, expected):
    """Auto mode needs no file edit for a new revision of a known model."""
    assert _charge_point(vendor, model).is_sync_charger is expected


def test_has_vendor_key_needs_both_sync_and_the_key():
    """An entity shows only on a Sync charger that returned its key."""
    cp = _charge_point("Sync Energy")
    cp.vendor_keys = {"ChargerMode"}
    assert cp.has_vendor_key("ChargerMode") is True
    assert cp.has_vendor_key("LightIntensity") is False

    generic = _charge_point("Wallbox")
    generic.vendor_keys = {"ChargerMode"}
    assert generic.has_vendor_key("ChargerMode") is False


def _config_response(*keys):
    return SimpleNamespace(
        configuration_key=[{"key": k, "value": "1", "readonly": False} for k in keys],
        unknown_key=None,
    )


async def test_probe_records_only_keys_the_charger_returns():
    """Unknown keys and timeouts leave their entities hidden."""
    cp = _charge_point("Sync Energy", "EVSC7S")
    answers = {
        "LightIntensity": _config_response("LightIntensity"),
        "ChargerMode": SimpleNamespace(
            configuration_key=[], unknown_key=["ChargerMode"]
        ),
        "GetCTClampValue": TimeoutError(),
    }

    async def fake_call(req):
        answer = answers[req.key[0]]
        if isinstance(answer, Exception):
            raise answer
        return answer

    cp.call = AsyncMock(side_effect=fake_call)
    cp.configure = AsyncMock()

    await cp.apply_vendor_configuration()

    assert cp.vendor_keys == {"LightIntensity"}
    # One request per key, each by name.
    assert [c.args[0].key for c in cp.call.await_args_list] == [
        [key] for key in SYNCEV_VENDOR_KEYS
    ]
    # LightIntensity is found, so the LED brightness is reasserted.
    cp.configure.assert_awaited_once_with("LightIntensity", "100")


async def test_probe_without_light_intensity_does_not_write_it():
    """The LED default is written only to a charger that has the key."""
    cp = _charge_point("Sync Energy")
    cp.call = AsyncMock(return_value=_config_response())
    cp.configure = AsyncMock()

    await cp.apply_vendor_configuration()

    assert cp.vendor_keys == set()
    cp.configure.assert_not_awaited()


async def test_probe_sends_nothing_to_a_generic_charger():
    """A non-Sync charger gets no extra requests and no vendor entities."""
    cp = _charge_point("Wallbox", "Pulsar")
    cp.vendor_keys = {"stale"}
    cp.call = AsyncMock()
    cp.configure = AsyncMock()

    await cp.apply_vendor_configuration()

    cp.call.assert_not_awaited()
    cp.configure.assert_not_awaited()
    assert cp.vendor_keys == set()


async def test_diagnostics_hide_ids_and_credentials(hass):
    """The charge point id is often the serial number, so it never appears."""
    secret_id = "SERIAL123456"
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            **MOCK_CONFIG_CS,
            CONF_USERNAME: "diag-login-x",
            CONF_PASSWORD: "diag-secret-y",
            CONF_CPIDS: [{secret_id: {**MOCK_CONFIG_CP, CONF_CPID: secret_id}}],
        },
        entry_id="diag_entry",
    )
    entry.add_to_hass(hass)

    cp = _charge_point("Sync Energy", "EVWC2T7G-03")
    cp.status = "ok"
    cp._ocpp_version = "1.6"
    cp._metrics[(0, cdet.firmware_version.value)] = _metric("V1")
    cp._metrics[(0, cdet.serial.value)] = _metric(secret_id)
    cp.vendor_keys = {"ChargerMode"}
    cp.num_connectors = 1
    cp._attr_supported_features = Profiles.CORE | Profiles.SMART
    cp.post_connect_success = True
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(
        charge_points={secret_id: cp}
    )

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert secret_id not in repr(result)
    assert "diag-login-x" not in repr(result)
    assert "diag-secret-y" not in repr(result)
    charger = result["chargers"]["charger_1"]
    assert charger["charger"]["vendor"] == "Sync Energy"
    assert charger["charger"]["model_family"] == "EVWC2T7G"
    assert charger["charger"]["is_sync_charger"] is True
    assert charger["charger"]["sync_vendor_keys_found"] == ["ChargerMode"]
    assert charger["charger"]["supported_features"] == ["CORE", "SMART"]
    assert result["integration_version"]


async def test_diagnostics_for_a_charger_that_never_connected(hass):
    """A configured but offline charger still gets its settings reported."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**MOCK_CONFIG_CS, CONF_CPIDS: [{"CP_X": dict(MOCK_CONFIG_CP)}]},
        entry_id="diag_offline",
    )
    entry.add_to_hass(hass)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["chargers"]["charger_1"]["charger"] is None
    assert "CP_X" not in repr(result)


def _entity(cls, description, cp):
    """Build an entity with only what availability reads."""
    entity = object.__new__(cls)
    entity.entity_description = description
    entity.cpid = "test_cpid"
    central = MagicMock()
    central.cpids = {"test_cpid": "CP_TEST"}
    central.charge_points = {"CP_TEST": cp} if cp is not None else {}
    central.get_available.return_value = True
    entity.central_system = central
    entity.connector_id = None
    entity._op_connector_id = 0
    return entity


def _description(items, key):
    return next(d for d in items if d.ocpp_key == key)


@pytest.mark.parametrize(
    ("key", "found", "vendor", "expected"),
    [
        ("ChargerMode", {"ChargerMode"}, "Sync Energy", True),
        ("ChargerMode", set(), "Sync Energy", False),
        ("GetCTClampValue", {"GetCTClampValue"}, "Sync Energy", True),
        # Previously the CT clamp switch showed on every charger.
        ("GetCTClampValue", {"GetCTClampValue"}, "Wallbox", False),
    ],
)
def test_vendor_switch_availability(key, found, vendor, expected):
    """Sync-specific switches follow the probe, not the model list."""
    from custom_components.syncenergy_ocpp.switch import SWITCHES, ChargePointSwitch

    cp = _charge_point(vendor, "Pulsar")
    cp.vendor_keys = set(found)
    entity = _entity(ChargePointSwitch, _description(SWITCHES, key), cp)
    assert entity.available is expected


def test_vendor_switch_unavailable_without_a_charger():
    """No connected charger means no vendor switch."""
    from custom_components.syncenergy_ocpp.switch import SWITCHES, ChargePointSwitch

    entity = _entity(ChargePointSwitch, _description(SWITCHES, "ChargerMode"), None)
    assert entity.available is False


def test_standard_ocpp_switch_is_not_gated():
    """A standard OCPP key stays available on any connected charger."""
    from custom_components.syncenergy_ocpp.switch import SWITCHES, ChargePointSwitch

    desc = _description(SWITCHES, "UnlockConnectorOnEVSideDisconnect")
    entity = _entity(ChargePointSwitch, desc, _charge_point("Wallbox"))
    assert entity.available is True


@pytest.mark.parametrize(
    ("found", "expected"), [({"LightIntensity"}, True), (set(), False)]
)
def test_led_brightness_number_follows_the_probe(found, expected):
    """The LED number shows on any Sync model that has the key."""
    from custom_components.syncenergy_ocpp.number import NUMBERS, ChargePointNumber

    cp = _charge_point("Sync Energy", "EVWC2T7G-03")
    cp.vendor_keys = set(found)
    entity = _entity(ChargePointNumber, _description(NUMBERS, "LightIntensity"), cp)
    assert entity.available is expected


async def test_switch_refresh_skips_a_key_the_charger_lacks():
    """Reading an unknown key raises an HA notification, so it is not read."""
    from custom_components.syncenergy_ocpp.switch import SWITCHES, ChargePointSwitch

    cp = _charge_point("Wallbox")
    cp.get_configuration = AsyncMock()
    entity = _entity(ChargePointSwitch, _description(SWITCHES, "GetCTClampValue"), cp)

    await entity._ocpp_refresh()

    cp.get_configuration.assert_not_awaited()


async def test_device_diagnostics_match_the_entry_report(hass):
    """Download diagnostics works from the charger's device page too."""
    from custom_components.syncenergy_ocpp.diagnostics import (
        async_get_device_diagnostics,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**MOCK_CONFIG_CS, CONF_CPIDS: [{"CP_X": dict(MOCK_CONFIG_CP)}]},
        entry_id="diag_device",
    )
    entry.add_to_hass(hass)

    assert await async_get_device_diagnostics(
        hass, entry, MagicMock()
    ) == await async_get_config_entry_diagnostics(hass, entry)


# --- End to end: a Sync charger that reconnects without rebooting -----------
#
# Found on a real Home Assistant (early test build): a charger that reconnects
# without rebooting sends no BootNotification on its own, so the vendor is not
# known when the connection setup checks the Sync keys. The check must run
# after the BootNotification the setup asks for, or when one arrives later.

import asyncio  # noqa: E402
import contextlib  # noqa: E402

import websockets  # noqa: E402
from ocpp.routing import after, on  # noqa: E402
from ocpp.v16 import call as v16call, call_result as v16result  # noqa: E402
from ocpp.v16.enums import Action, RegistrationStatus  # noqa: E402

from .charge_point_test import wait_ready  # noqa: E402
from .test_charge_point_v16 import ChargePoint as SimCharger  # noqa: E402


class _SyncChargerNoBoot(SimCharger):
    """Answers the Sync keys and sends a BootNotification only when asked."""

    @on(Action.get_configuration)
    def on_get_configuration(self, key, **kwargs):
        if key and key[0] in SYNCEV_VENDOR_KEYS:
            return v16result.GetConfiguration(
                configuration_key=[{"key": key[0], "readonly": False, "value": "1"}]
            )
        return SimCharger.on_get_configuration(self, key, **kwargs)

    @after(Action.trigger_message)
    async def after_trigger_message(self, requested_message, **kwargs):
        if requested_message == "BootNotification":
            resp = await self.call(
                v16call.BootNotification(
                    charge_point_model="EVSC7S", charge_point_vendor="Sync Energy"
                )
            )
            assert resp.status == RegistrationStatus.accepted


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "setup_config_entry",
    [{"port": 9471, "cp_id": "CP_sync_noboot", "cms": "cms_sync_noboot"}],
    indirect=True,
)
@pytest.mark.parametrize("cp_id", ["CP_sync_noboot"])
@pytest.mark.parametrize("port", [9471])
async def test_sync_keys_found_when_charger_reconnects_without_boot(
    hass, socket_enabled, cp_id, port, setup_config_entry
):
    """The Sync keys are found although no BootNotification came first."""
    cs = setup_config_entry
    async with websockets.connect(
        f"ws://127.0.0.1:{port}/{cp_id}", subprotocols=["ocpp1.6"]
    ) as ws:
        client = _SyncChargerNoBoot(f"{cp_id}_client", ws)
        task = asyncio.create_task(client.start())
        try:
            # No BootNotification from the charger: it only answers requests.
            while cp_id not in cs.charge_points:
                await asyncio.sleep(0.05)
            server = cs.charge_points[cp_id]
            await asyncio.wait_for(wait_ready(server), timeout=30)
            for _ in range(100):
                if server.vendor_keys:
                    break
                await asyncio.sleep(0.1)
            assert server.is_sync_charger is True
            assert server.vendor_keys == set(SYNCEV_VENDOR_KEYS)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await ws.close()


async def test_late_boot_notification_runs_the_key_check():
    """A BootNotification after setup checks the keys of a Sync charger once."""
    cp = _charge_point()

    async def store_info(info):
        cp._metrics[(0, cdet.vendor.value)] = _metric(info["charge_point_vendor"])

    cp.async_update_device_info_v16 = store_info
    cp.run_vendor_probe = AsyncMock()

    await cp._device_info_then_vendor_probe({"charge_point_vendor": "Sync Energy"})
    cp.run_vendor_probe.assert_awaited_once()

    # Keys already found: a later BootNotification does not ask again.
    cp.run_vendor_probe.reset_mock()
    cp.vendor_keys = {"LightIntensity"}
    await cp._device_info_then_vendor_probe({"charge_point_vendor": "Sync Energy"})
    cp.run_vendor_probe.assert_not_awaited()

    # A non-Sync charger is never asked.
    other = _charge_point()

    async def other_info(info):
        other._metrics[(0, cdet.vendor.value)] = _metric("Wallbox")

    other.async_update_device_info_v16 = other_info
    other.run_vendor_probe = AsyncMock()
    await other._device_info_then_vendor_probe({"charge_point_vendor": "Wallbox"})
    other.run_vendor_probe.assert_not_awaited()
