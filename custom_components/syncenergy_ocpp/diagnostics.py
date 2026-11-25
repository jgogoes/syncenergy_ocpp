"""Diagnostics support for OCPP.

BG Sync fork: lets a user share what their charger reports, with one click
("Download diagnostics" on the integration or device page), for compatibility
reports. Charge point ids and serial numbers are replaced, because Sync
chargers are often set up with their serial number as the charge point id.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OK
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.loader import async_get_integration

from .const import (
    CONF_CPID,
    CONF_CPIDS,
    CONF_PASSWORD,
    CONF_SSL_CERTFILE_PATH,
    CONF_SSL_KEYFILE_PATH,
    CONF_USERNAME,
    DOMAIN,
)
from .enums import HAChargerDetails as cdet, Profiles

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SSL_CERTFILE_PATH,
    CONF_SSL_KEYFILE_PATH,
    CONF_CPID,
}


def _metric_value(cp, key: str):
    """Return a charger-level metric value, or None."""
    metric = cp._metrics.get((0, key))
    return metric.value if metric is not None else None


def _charger_report(cp) -> dict[str, Any]:
    """Return the facts that matter for a compatibility report."""
    from .chargepoint import _model_family  # local: avoids an import cycle

    model = _metric_value(cp, cdet.model.value)
    features = getattr(cp, "supported_features", 0) or 0
    return {
        "connected": cp.status == STATE_OK,
        "ocpp_version": getattr(cp, "_ocpp_version", None),
        "vendor": _metric_value(cp, cdet.vendor.value),
        "model": model,
        "model_family": _model_family(model),
        "firmware_version": _metric_value(cp, cdet.firmware_version.value),
        "num_connectors": getattr(cp, "num_connectors", None),
        "supported_features": [
            flag.name for flag in Profiles if flag.name and features & flag
        ],
        "is_sync_charger": cp.is_sync_charger,
        "sync_vendor_keys_found": sorted(getattr(cp, "vendor_keys", set())),
        "post_connect_success": getattr(cp, "post_connect_success", None),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    central = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    charge_points = getattr(central, "charge_points", {}) or {}

    chargers: dict[str, Any] = {}
    index = 0
    for item in entry.data.get(CONF_CPIDS, []):
        for cp_id, settings in item.items():
            index += 1
            label = f"charger_{index}"
            stored = async_redact_data(dict(settings), TO_REDACT)
            cp = charge_points.get(cp_id)
            chargers[label] = {
                "settings": stored,
                "charger": _charger_report(cp) if cp is not None else None,
            }

    central_settings = {
        key: value for key, value in entry.data.items() if key != CONF_CPIDS
    }
    integration = await async_get_integration(hass, DOMAIN)
    return {
        "integration_version": str(integration.version),
        "central_system": async_redact_data(central_settings, TO_REDACT),
        "chargers": chargers,
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a charger device.

    The report covers the whole config entry: it is small, and it holds no
    ids that would let the device be matched back to a charger record.
    """
    return await async_get_config_entry_diagnostics(hass, entry)
