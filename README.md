![OCPP for Sync Energy chargers](custom_components/sync_energy_ocpp/brand/icon.png)

# OCPP for Sync Energy chargers (BG SyncEV)

A Home Assistant integration for **Sync Energy** EV chargers, also sold as
**BG SyncEV** and **SyncEV**. It talks to the charger directly over OCPP, on
your own network, with no cloud account needed.

It is based on [lbbrhzn/ocpp](https://github.com/lbbrhzn/ocpp), with fixes and
extra controls for Sync Energy hardware. Everything upstream does, this does too.

> **This is a community project.** It is not made, endorsed or supported by
> Sync Energy, BG Electrical or Luceco. Product names are used only to say
> which chargers it works with.

> **New name, new domain (version 2.0.0).** This project was called
> "OCPP - BG Sync EV" and used the `ocpp` domain, the same as upstream. Two
> integrations with the same domain cannot both be in the Home Assistant
> Marketplace, so from 2.0.0 the domain is `sync_energy_ocpp`. This lets the
> integration be listed in the Marketplace, and lets you install it next to
> upstream. It also moved to this new repository; the old one was
> [jgogoes/hass_ocpp_bg_sync_ev](https://github.com/jgogoes/hass_ocpp_bg_sync_ev).
> Existing users: see **[MIGRATION.md](MIGRATION.md)**. A guided import keeps
> your settings and entity IDs.

### New in 2.0.0

- **Works with your Sync charger without file edits.** The charger is
  recognised automatically from what it reports, including newer revisions
  such as `-02` and `-03`.
- **Only the controls your charger has.** LED brightness, Charge When Plugged
  In and Enable CT Clamp appear only if your charger supports them. The CT
  Clamp switch no longer appears on other chargers.
- **One-click diagnostics** for support and compatibility reports, with no
  charge point id, serial number or password in the file.
- **Guided import** from the old `ocpp` setup.

> Developed and measured against a **SyncEV EVSC7S** (firmware
> `RD0045-V1.02-S1.01`) driven by evcc. Base: upstream **v0.12.3** (main at `c514238`).

## Why this fork

On stock upstream, **charge-rate control does not work on this charger**. Three
separate causes, all confirmed on real hardware:

| Problem | Effect |
|---|---|
| The charger rejects the stack level upstream sends. It reports `ChargeProfileMaxStackLevel` 5 and refuses every profile at 5, accepting 0–4. | The ceiling and the in-session profile **never applied at all**. |
| OCPP requires charge limits be a multiple of 0.1 A, and upstream sends raw floats. | evcc's values (e.g. `11.653986956521738`) were rejected before leaving Home Assistant, surfacing as **HTTP 500 errors**. |
| The station ceiling was rewritten to the live target on every change. | A stale lower value silently **capped the session** — a 6 A ceiling held a 16 A limit down to 6 A. |

All three are fixed. The charger also floors requests to whole amps (10.9 A
behaves as 10 A), so requests that cannot change anything are no longer sent —
which matters when a solar controller recalculates every few seconds.

## What you get beyond upstream

**Extra controls**, for settings the charger supports but upstream never exposed:

- Max Current (hardware limit), Overvoltage Protection Limit, Connection Timeout,
  Meter Reading Interval
- Indicator LED Brightness
- Auto-Unlock on Unplug
- Enable CT Clamp
- Charge When Plugged In — the charger authorises itself on plug-in, no server
  needed. Note this competes with smart charging rather than complementing it.

**Extra sensors:** House Current and House Voltage from the charger's CT clamp,
which upstream receives and discards.

**Tidier dashboard:** sensors get readable names ("Charging Current" rather than
`Current.Import`), and metrics this charger physically cannot report are hidden
by default instead of sitting permanently `unavailable`.

**Fewer surprises:** no more persistent notification on every restart about a
read-only setting, and reconnecting mid-session no longer interrupts a charge —
that used to trip a `C1249 Too Many Wake-Up Requests` fault on a VW ID.3.

## Installing

Until the Marketplace listing is approved, add it as a custom repository:

1. HACS → three-dot menu → **Custom repositories**
2. Add `https://github.com/jgogoes/sync_energy_ocpp`, type **Integration**
3. Search for **Sync Energy**, download it, then restart Home Assistant
4. **Settings → Devices & services → Add integration → OCPP for Sync Energy chargers**

Or copy `custom_components/sync_energy_ocpp/` into your
`config/custom_components/` folder and restart.

Moving from the old `ocpp` domain (this project before 2.0.0, or upstream)?
Follow **[MIGRATION.md](MIGRATION.md)**: install this one next to the old one,
then import. Do not run both on the same port.

## Will this work on my charger?

You do not need to edit any files. On connect the integration checks if the
charger is Sync Energy hardware, and turns on the Sync fixes and controls
automatically:

- **Detection:** the vendor the charger reports (the EVSC7S reports
  `Sync Energy`), or a known Sync model family. A revision suffix such as
  `-02` or `-03` is ignored.
- **Controls:** each Sync-only control (LED brightness, Charge When Plugged In,
  Enable CT Clamp) appears only if your charger has that setting.

On non-Sync hardware the Sync controls do not appear and no extra requests are
sent. The charging-profile fixes are general.

| Model | Status |
|---|---|
| EVSC7S | Confirmed (developed and measured on it) |
| EVWC2T7G | Reported working by a user |
| EVT77G, EVT77GG, EVWC2T7GG, EVL7PS(G), EVL7MS(G), EVLR7MS(G), EVLS7MS(G) | Expected to work, untested |

**Sync charger not detected, or not in the table?** Please help by sending a
[compatibility report](https://github.com/jgogoes/sync_energy_ocpp/issues/new?template=compatibility.yml).
It takes two minutes: on the charger's device page (or the OCPP integration entry), select
**⋮ → Download diagnostics** and attach the file. The diagnostics file
contains no charge point id, serial number or password.

## Documentation

- **[MIGRATION.md](MIGRATION.md)**: moving from the old `ocpp` domain
- **[FORK.md](FORK.md)** — what changed and why, including things deliberately
  *not* changed
- **[HARDWARE-FINDINGS.md](HARDWARE-FINDINGS.md)** — the raw measurements every
  fix is based on, so you can check the reasoning rather than trust it

For general OCPP setup, upstream's docs still apply:
[home-assistant-ocpp.readthedocs.io](https://home-assistant-ocpp.readthedocs.io)

## Credit

All the real work is [lbbrhzn](https://github.com/lbbrhzn)'s and the
[contributors](https://github.com/lbbrhzn/ocpp/graphs/contributors) to upstream,
built on the [Python OCPP package](https://github.com/mobilityhouse/ocpp). This
fork is a thin layer of hardware-specific fixes on top.

If you find it useful, consider buying the upstream author a coffee:

<a href="https://www.buymeacoffee.com/lbbrhzn" target="_blank">
  <img src="https://cdn.buymeacoffee.com/buttons/default-black.png" alt="Buy Me A Coffee" width="150px">
</a>
