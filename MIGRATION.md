# Moving to `syncenergy_ocpp` (version 2.0.0)

From version 2.0.0 this integration uses the domain `syncenergy_ocpp`
instead of `ocpp`. This page moves your setup across. It works the same way
for this project before 2.0.0 and for upstream
[lbbrhzn/ocpp](https://github.com/lbbrhzn/ocpp).

## Why the change

The Home Assistant Marketplace lists only one integration per domain, and
upstream already uses `ocpp`. A domain of its own lets this integration be
listed, and lets it be installed next to upstream.

## What carries over

The guided import was tested in the Home Assistant test environment
(Home Assistant 2026.10):

- Your central system and charger settings
- Your devices, and the entity IDs of your entities, including IDs you
  renamed yourself
- Recorder history and long-term statistics, because both are stored
  against the entity ID
- Areas, labels and names you gave devices and entities stay on the same
  registry entries

## What you must change yourself

- **Actions (services)** move to the new domain. For example,
  `ocpp.set_charge_rate` becomes `syncenergy_ocpp.set_charge_rate`.
  Update your automations and scripts.
- **The authorization event** is now `syncenergy_ocpp_authorization`
  (was `ocpp_authorization`).
- **evcc or other tools** that call Home Assistant actions by name need the
  same change. Entity IDs do not change.

## Steps

Version 2.0.0 lives in a new repository,
[jgogoes/syncenergy_ocpp](https://github.com/jgogoes/syncenergy_ocpp).
You install it next to the old integration and keep the old one until the
new one works. The old integration is only removed at the end.

The two integrations use the same websocket port, so they must never run at
the same time. Do the steps in this order.

1. **Back up Home Assistant.** Settings → System → Backups.
2. **Update the old integration** to its latest version (1.2.0), and
   restart. The import accepts only a setup saved by a current version.
3. **Install the new integration.** In the Marketplace (or HACS), add the
   repository `https://github.com/jgogoes/syncenergy_ocpp` as a custom
   repository of type **Integration** (not needed once it is listed in the
   Marketplace), then download **OCPP for Sync Energy chargers**. Do not add
   it in Devices & services yet.
4. **Check the configuration, then restart Home Assistant.** For example
   with `ha core check` before the restart.
5. **Disable the old integration.** Settings → Devices & services → OCPP →
   three dots → **Disable**. This stops it and frees the port. Its settings,
   devices and entities stay stored.
6. **Add the new integration.** Settings → Devices & services → Add
   integration → **OCPP for Sync Energy chargers**. It finds the disabled
   setup and offers **Import the old settings**. Leave it on and submit.
   - If the old integration is still enabled, the setup stops and asks you
     to disable it first.
7. **Check that the charger reconnects.** The port and path are unchanged,
   so nothing changes on the charger.
8. **Update your automations** (see above).
9. **Remove the old setup.** Delete the disabled OCPP entry, then remove
   **OCPP - BG Sync EV** in the Marketplace. Your moved devices and entities
   stay with the new integration.

Do not use the Marketplace's **Delete and uninstall** on the old
integration before step 6: it deletes the old setup, and then there is
nothing left to import.

## If something goes wrong

- To go back at any point after step 6, restore the backup from step 1.
  Do not just delete the new entry: the import moved the devices and
  entities to it, so deleting it deletes them.
- Please report problems in the
  [issue tracker](https://github.com/jgogoes/syncenergy_ocpp/issues),
  with the diagnostics file (device page → three dots → **Download
  diagnostics**).
