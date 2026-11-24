"""Moving a setup from the old "ocpp" domain to sync_energy_ocpp.

The handoff must never run both integrations (they bind the same port), must
copy the settings before the old entry is removed, and must keep entity IDs so
recorder history carries on. These tests run the real config flow and setup
against a registry and recorder holding an old "ocpp" setup.
"""

from datetime import timedelta

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.components.recorder import history, statistics
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.sync_energy_ocpp.const import (
    CONF_CPIDS,
    CONF_PORT,
    DOMAIN,
    sensor_unique_id,
)
from custom_components.sync_energy_ocpp.legacy import (
    CONF_IMPORTED_FROM,
    LEGACY_DOMAIN,
    migrate_unique_id,
)

from .const import MOCK_CONFIG_CP_APPEND, MOCK_CONFIG_DATA


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Start the recorder before hass, as the recorder fixture requires."""
    yield


PORT = 9431
CP_ID = "CP_LEGACY"
CPID = MOCK_CONFIG_CP_APPEND["cpid"]
# A user-chosen entity ID, so a regenerated default ID cannot pass for a kept one.
SENSOR_ENTITY_ID = "sensor.my_garage_charger_vendor"
SWITCH_ENTITY_ID = "switch.my_garage_charger_charge_control"
ENERGY_ENTITY_ID = "sensor.my_garage_charger_energy"
ENERGY_METRIC = "Energy.Active.Import.Register"


def _legacy_unique_id(new_unique_id: str) -> str:
    """Return the unique_id the old "ocpp" domain gave the same entity."""
    return new_unique_id.replace(DOMAIN, LEGACY_DOMAIN, 1)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("ocpp.test_cpid.vendor.sensor", "sync_energy_ocpp.test_cpid.vendor.sensor"),
        (
            "switch.ocpp.test_cpid.charge_control",
            "switch.sync_energy_ocpp.test_cpid.charge_control",
        ),
        (
            "number.ocpp.test_cpid.conn1.maximum_current",
            "number.sync_energy_ocpp.test_cpid.conn1.maximum_current",
        ),
        ("button.ocpp.test_cpid.reset", "button.sync_energy_ocpp.test_cpid.reset"),
        ("something.else", "something.else"),
        ("sensor.ocppx.test", "sensor.ocppx.test"),
    ],
)
def test_migrate_unique_id_changes_only_the_domain_segment(old, new):
    """Every platform's unique_id format is covered."""
    assert migrate_unique_id(old) == new


def _legacy_entry(hass, *, disabled=True, version=(2, 3), port=PORT):
    data = {
        **MOCK_CONFIG_DATA,
        CONF_PORT: port,
        CONF_CPIDS: [{CP_ID: dict(MOCK_CONFIG_CP_APPEND)}],
    }
    entry = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        data=data,
        title="old_central",
        version=version[0],
        minor_version=version[1],
        disabled_by=config_entries.ConfigEntryDisabler.USER if disabled else None,
    )
    entry.add_to_hass(hass)
    return entry


def _register_legacy_objects(hass, legacy):
    """Put the old setup's devices and entities in the registries."""
    dev_reg = dr.async_get(hass)
    charger = dev_reg.async_get_or_create(
        config_entry_id=legacy.entry_id,
        identifiers={(LEGACY_DOMAIN, CP_ID), (LEGACY_DOMAIN, CPID)},
        name=CPID,
    )
    ent_reg = er.async_get(hass)
    sensor_uid = _legacy_unique_id(sensor_unique_id(CPID, "Vendor"))
    ent_reg.async_get_or_create(
        "sensor",
        LEGACY_DOMAIN,
        sensor_uid,
        config_entry=legacy,
        device_id=charger.id,
        suggested_object_id="my_garage_charger_vendor",
    )
    ent_reg.async_get_or_create(
        "switch",
        LEGACY_DOMAIN,
        f"switch.{LEGACY_DOMAIN}.{CPID}.charge_control",
        config_entry=legacy,
        device_id=charger.id,
        suggested_object_id="my_garage_charger_charge_control",
    )
    ent_reg.async_get_or_create(
        "sensor",
        LEGACY_DOMAIN,
        _legacy_unique_id(sensor_unique_id(CPID, ENERGY_METRIC)),
        config_entry=legacy,
        device_id=charger.id,
        suggested_object_id="my_garage_charger_energy",
    )
    assert ent_reg.async_get(SENSOR_ENTITY_ID) is not None
    assert ent_reg.async_get(SWITCH_ENTITY_ID) is not None
    assert ent_reg.async_get(ENERGY_ENTITY_ID) is not None
    # What a user may have customised on the old entities and device.
    ent_reg.async_update_entity(
        ENERGY_ENTITY_ID, name="My energy", area_id="garage", labels={"ev"}
    )
    dev_reg.async_update_device(
        charger.id, name_by_user="Drive charger", area_id="garage"
    )
    return charger


def _import_energy_statistics(hass):
    """Store two hours of long-term statistics, as the old integration would have."""
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(
        hours=3
    )
    statistics.async_import_statistics(
        hass,
        {
            "mean_type": StatisticMeanType.NONE,
            "has_sum": True,
            "name": None,
            "source": "recorder",
            "statistic_id": ENERGY_ENTITY_ID,
            "unit_class": "energy",
            "unit_of_measurement": "kWh",
        },
        [
            {"start": start, "state": 10.0, "sum": 10.0},
            {"start": start + timedelta(hours=1), "state": 12.5, "sum": 12.5},
        ],
    )
    return start


def _energy_sums(hass, start):
    rows = statistics.statistics_during_period(
        hass, start, None, {ENERGY_ENTITY_ID}, "hour", None, {"sum"}
    )
    return [row["sum"] for row in rows.get(ENERGY_ENTITY_ID, [])]


async def _start_flow(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_import_keeps_entity_ids_history_and_survives_old_entry_delete(
    recorder_mock, hass, socket_enabled
):
    """The full staged handoff, end to end."""
    legacy = _legacy_entry(hass)
    charger = _register_legacy_objects(hass, legacy)

    # History recorded under the old integration.
    hass.states.async_set(SENSOR_ENTITY_ID, "Sync Energy")
    await async_wait_recording_done(hass)
    hass.states.async_remove(SENSOR_ENTITY_ID)
    stats_start = _import_energy_statistics(hass)
    await async_wait_recording_done(hass)
    assert await recorder_mock.async_add_executor_job(
        _energy_sums, hass, stats_start
    ) == [10.0, 12.5]

    result = await _start_flow(hass)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "import_legacy"
    assert CP_ID in result["description_placeholders"]["chargers"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"import": True}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    entry = result["result"]
    await hass.async_block_till_done()

    # Settings copied, and the one-off marker cleared after adoption.
    assert entry.data[CONF_PORT] == PORT
    assert entry.data[CONF_CPIDS] == legacy.data[CONF_CPIDS]
    assert CONF_IMPORTED_FROM not in entry.data

    ent_reg = er.async_get(hass)
    for entity_id in (SENSOR_ENTITY_ID, SWITCH_ENTITY_ID, ENERGY_ENTITY_ID):
        moved = ent_reg.async_get(entity_id)
        assert moved is not None, entity_id
        assert moved.platform == DOMAIN
        assert moved.config_entry_id == entry.entry_id
        assert moved.unique_id == migrate_unique_id(moved.unique_id)
        assert moved.device_id == charger.id
        assert moved.disabled_by is None
        # The new integration reused the moved entry; no "_2" duplicate.
        assert ent_reg.async_get(f"{entity_id}_2") is None
    energy = ent_reg.async_get(ENERGY_ENTITY_ID)
    assert (energy.name, energy.area_id, energy.labels) == (
        "My energy",
        "garage",
        {"ev"},
    )
    assert ent_reg.async_get(SENSOR_ENTITY_ID).unique_id == sensor_unique_id(
        CPID, "Vendor"
    )

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(charger.id)
    assert device is not None
    assert device.identifiers == {(DOMAIN, CP_ID), (DOMAIN, CPID)}
    assert device.config_entry_id == entry.entry_id
    assert (device.name_by_user, device.area_id) == ("Drive charger", "garage")

    # History recorded before the move is still found under the same entity ID.
    states = await recorder_mock.async_add_executor_job(
        history.get_significant_states,
        hass,
        dt_util.utcnow() - timedelta(hours=1),
        None,
        [SENSOR_ENTITY_ID],
    )
    assert any(s.state == "Sync Energy" for s in states[SENSOR_ENTITY_ID])

    # Step 6 of the handoff: deleting the old entry removes nothing that moved.
    assert await hass.config_entries.async_remove(legacy.entry_id)
    await hass.async_block_till_done()
    assert ent_reg.async_get(SENSOR_ENTITY_ID) is not None
    assert ent_reg.async_get(SWITCH_ENTITY_ID) is not None
    assert dev_reg.async_get(charger.id) is not None

    # Long-term statistics are stored against the entity ID, so they carry on
    # after the move and after the old entry is deleted.
    await async_wait_recording_done(hass)
    assert await recorder_mock.async_add_executor_job(
        _energy_sums, hass, stats_start
    ) == [10.0, 12.5]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_flow_refuses_while_old_integration_is_enabled(hass):
    """Both integrations must never bind the port together."""
    _legacy_entry(hass, disabled=False)

    result = await _start_flow(hass)

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "legacy_active"


async def test_flow_refuses_an_old_entry_newer_than_supported(hass):
    """A format this import does not know is refused, not guessed at."""
    _legacy_entry(hass, version=(2, 4))

    result = await _start_flow(hass)

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "legacy_unsupported"


async def test_flow_refuses_an_outdated_old_entry(hass):
    """An old entry in an older format must be updated by the old integration first."""
    _legacy_entry(hass, version=(2, 1))

    result = await _start_flow(hass)

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "legacy_outdated"


async def test_declining_the_import_shows_the_normal_setup(hass):
    """The user can start fresh instead."""
    _legacy_entry(hass)

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"import": False}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_no_old_setup_shows_the_normal_setup(hass):
    """A new user never sees the import step."""
    result = await _start_flow(hass)

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_an_imported_old_entry_is_not_offered_again(hass):
    """After an import, adding another central system starts fresh."""
    legacy = _legacy_entry(hass)
    MockConfigEntry(
        domain=DOMAIN,
        data={**legacy.data, CONF_IMPORTED_FROM: legacy.entry_id},
    ).add_to_hass(hass)

    result = await _start_flow(hass)

    assert result["step_id"] == "user"
