"""Move a setup from the old "ocpp" domain to this integration.

Earlier releases of this project, and upstream lbbrhzn/ocpp, use the "ocpp"
domain. The handoff is staged so the two never run at the same time (both
would bind the same websocket port):

1. The user disables the old OCPP config entry. Its settings stay stored, and
   its entities and devices stay in the registries, unloaded.
2. The config flow of this integration offers to import that disabled entry.
   It refuses while any old entry is still enabled.
3. On first setup of the imported entry, its entities and devices are moved
   from the old entry to the new one. Entity IDs are kept, so the recorder
   history that is stored against them carries on.
4. The user then deletes the old entry and removes the old integration.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

LEGACY_DOMAIN = "ocpp"
# Set on an imported entry until its first setup has adopted the old entities.
CONF_IMPORTED_FROM = "imported_from"
# Only an old entry at this config entry version can be imported as it is.
# Older ones must first be updated by the old integration's own migration.
LEGACY_VERSION = (2, 3)


@callback
def legacy_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return the config entries of the old "ocpp" domain, ignored ones left out."""
    return hass.config_entries.async_entries(LEGACY_DOMAIN, include_ignore=False)


def migrate_unique_id(unique_id: str) -> str:
    """Return the unique_id this integration gives the same entity.

    The domain is part of every unique_id: "<platform>.ocpp.<cpid>..." for
    buttons, numbers and switches, and "ocpp.<cpid>...sensor" for sensors.
    Only that domain segment changes.
    """
    if unique_id.startswith(f"{LEGACY_DOMAIN}."):
        return f"{DOMAIN}.{unique_id[len(LEGACY_DOMAIN) + 1 :]}"
    platform, sep, rest = unique_id.partition(".")
    if sep and rest.startswith(f"{LEGACY_DOMAIN}."):
        return f"{platform}.{DOMAIN}.{rest[len(LEGACY_DOMAIN) + 1 :]}"
    return unique_id


@callback
def async_adopt_legacy(
    hass: HomeAssistant, entry: ConfigEntry, legacy_entry_id: str
) -> tuple[int, int]:
    """Move the old entry's devices and entities to entry.

    Returns how many devices and entities were moved. The old entry must not
    be loaded; the config flow only imports a disabled one.
    """
    # Entities first: moving a device off the old entry makes the registry
    # remove the old entry's entities that are still on that device.
    ent_reg = er.async_get(hass)
    entities = 0
    for entity in er.async_entries_for_config_entry(ent_reg, legacy_entry_id):
        if entity.platform != LEGACY_DOMAIN:
            continue
        new_unique_id = migrate_unique_id(entity.unique_id)
        if ent_reg.async_get_entity_id(entity.domain, DOMAIN, new_unique_id):
            _LOGGER.warning(
                "Not moving %s: this integration already has an entity for it",
                entity.entity_id,
            )
            continue
        ent_reg.async_update_entity_platform(
            entity.entity_id,
            DOMAIN,
            new_config_entry_id=entry.entry_id,
            new_unique_id=new_unique_id,
        )
        # Disabling the old entry disabled its entities with it. They now
        # belong to an enabled entry, so that reason no longer applies. An
        # entity the user disabled by hand stays disabled.
        if entity.disabled_by is er.RegistryEntryDisabler.CONFIG_ENTRY:
            ent_reg.async_update_entity(entity.entity_id, disabled_by=None)
        entities += 1

    dev_reg = dr.async_get(hass)
    devices = 0
    for device in dr.async_entries_for_config_entry(dev_reg, legacy_entry_id):
        identifiers = {
            (DOMAIN, value) if domain == LEGACY_DOMAIN else (domain, value)
            for domain, value in device.identifiers
        }
        dev_reg.async_update_device(
            device.id,
            new_config_entry_id=entry.entry_id,
            new_identifiers=identifiers,
        )
        devices += 1

    _LOGGER.info(
        "Moved %d devices and %d entities from the old OCPP integration",
        devices,
        entities,
    )
    return devices, entities
