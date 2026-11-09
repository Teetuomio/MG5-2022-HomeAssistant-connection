# MG5 2022 for Home Assistant

A Home Assistant integration for the **MG5 Electric (2022)**, series EP21 and EP22, via the MG iSmart account.

The generic MG SAIC custom integration has no profile for this car. It still offers heated seats, windows, a sunroof and battery heating, and it turns the cabin climate on with the compressor forced. On a 2022 MG5 those commands are accepted by the cloud and then do nothing, or the climate card snaps to “fan only” because the car reports “running” as status `2`.

This integration only creates the controls that car can run, and it starts the climate the way the MG5 expects: fan speed 2, temperature index `celsius - 14` (22°C is index 8), and no compressor byte.

## What you can control

- Lock and unlock
- Cabin climate: heat/cool or off, 16–28°C. The car heats or cools toward that setpoint. There is no fan slider.
- Charge limit, in steps of 10 from 40 to 100
- Start and stop charging. The switch stays off until the car reports that current is flowing. Start is unreliable on this API, and a rejection is shown instead of a switch that pretends it worked.
- Scheduled charging: start time, end time, and mode (Disabled, Until end time, Until target SOC). The car stores hour and minute only, repeated daily; there is no date or weekday.
- Find the car (horn and lights)
- Refresh, which wakes the car for one live read
- State of charge, range, odometer, temperatures, 12 V battery, tyre pressures, charge power, and location

Heated seats, windows, sunroof, steering-wheel heat, front and rear defrost, and battery heating are not created. The 2022 car reports those as not fitted.

State of charge and range come from the car. The battery you pick at setup (50.3 kWh Standard Range or 61.1 kWh Long Range) is only used for the battery-energy sensor. The API’s 72.5 kWh figure is wrong for an MG5 and is ignored.

## Install

You need Home Assistant **2025.1 or newer** with access to the `/config` folder (Home Assistant OS, Supervised, Container or Core all work). The integration installs its one Python dependency, `saic-ismart-client-ng`, by itself on first start.

### 1. Make a secondary iSmart account

iSmart allows one session per account. If Home Assistant signs in with the account on your phone, the phone app is logged out, and the other way round. Give Home Assistant its own account:

1. Register a new account in the **MG iSmart** app (a second email address is enough), then log out of it.
2. In your own account, open the car's **Driver / Share** settings and share the MG5 with the new account.
3. Log in once with the new account and accept the share. Check that the car appears and shows its battery level.
4. Log back in with your own account on the phone. Use the new account only in Home Assistant.

### 2. Remove the old MG SAIC integration

If the generic MG SAIC integration is configured for the same car, remove it under **Settings → Devices & services**. Two integrations polling the same car wake it more often, and they log each other out.

### 3. Install the integration

**With HACS (recommended, gets updates):**

1. In Home Assistant open **HACS → Integrations**.
2. Open the **⋮** menu (top right) → **Custom repositories**.
3. Paste `https://github.com/Teetuomio/MG5-2022-HomeAssistant-connection`, choose category **Integration**, and add it.
4. Find **MG5** in the HACS integration list and choose **Download**.
5. Restart Home Assistant.

**Manually (no HACS):**

Copy the folder `custom_components/mg5` from this repository so that it ends up at `/config/custom_components/mg5/`. The `manifest.json` file must be directly inside that folder:

```text
/config/
└── custom_components/
    └── mg5/
        ├── __init__.py
        ├── manifest.json
        ├── translations/
        └── ...
```

Pick one way:

- **Samba share add-on:** open `\\homeassistant.local\config` (Windows) or `smb://homeassistant.local/config` (macOS), create `custom_components` if it does not exist, and drag the `mg5` folder into it.
- **Studio Code Server or File editor add-on:** create `custom_components/mg5` and upload the files into it (the editor's upload button takes the whole folder).
- **SSH / Terminal add-on:**

  ```bash
  cd /config
  mkdir -p custom_components
  # from a clone or downloaded copy of this repository:
  cp -r /path/to/repo/custom_components/mg5 custom_components/
  ```

A manual install does not update itself: repeat the copy for each new release.

### 4. Restart

Go to **Settings → System → top-right power icon → Restart Home Assistant**. A plain "reload YAML" is not enough for a new integration.

After the restart, **Settings → System → Logs** shows the warning `We found a custom integration mg5 which has not been tested by Home Assistant`. That warning is normal for every custom integration.

### 5. Add the integration

1. Go to **Settings → Devices & services → Add integration** and search for **MG5**. If it is not listed, refresh the browser (Ctrl+F5); if it is still missing, the folder is in the wrong place.
2. Fill in the form:
   - **Account:** Email or Phone, matching the secondary account.
   - **Email or phone number** and **Password** of the secondary account.
   - **Region:** Europe for Finland and the rest of Europe. Australia / New Zealand and Türkiye are the other gateways.
   - **Country code:** only for a phone account, digits without the plus (`358` for Finland).
   - **Battery:** Standard Range (50.3 kWh, about 320 km WLTP) or Long Range (61.1 kWh, about 400 km WLTP). The sales documents or the "Long Range" badge tell you which one. It only affects the battery-energy sensor, and you can change it later with **Configure**.
3. If the account has more than one MG5, choose the car. Other MG models on the account are hidden.

The device appears as **MG5 1234**, where 1234 is the end of the VIN. Entity ids follow that name, for example `climate.mg5_1234_climate` and `lock.mg5_1234_lock`.

### 6. Check that it works

- The first state appears within a few seconds from SAIC's stored status. State of charge can stay *unknown* until one live read about 5 seconds later.
- Press **Refresh** on the device page. **Last contact** should move to now.
- Try each control once while you can see the car: **Find car**, **Lock**, then **Climate** (set the temperature first, then turn it on). Leave about 30 seconds between commands; the integration queues them anyway.

### Dashboard and automation example

Pre-heat on weekday mornings:

```yaml
automation:
  - alias: "MG5 pre-heat"
    triggers:
      - trigger: time
        at: "07:15:00"
    conditions:
      - condition: time
        weekday: [mon, tue, wed, thu, fri]
    actions:
      - action: climate.set_temperature
        target:
          entity_id: climate.mg5_1234_climate
        data:
          temperature: 22
      - action: climate.set_hvac_mode
        target:
          entity_id: climate.mg5_1234_climate
        data:
          hvac_mode: heat_cool
```

Get a phone notification when the car rejects a command:

```yaml
automation:
  - alias: "MG5 command failed"
    triggers:
      - trigger: event
        event_type: mg5_command_failed
    actions:
      - action: notify.notify
        data:
          message: "MG5 {{ trigger.event.data.source }} failed: {{ trigger.event.data.error }}"
```

### Troubleshooting

Turn on debug logging by adding this to `configuration.yaml` and restarting:

```yaml
logger:
  default: warning
  logs:
    custom_components.mg5: debug
    saic_ismart_client_ng: debug
```

Logs are under **Settings → System → Logs → Show raw logs**. The integration masks the VIN; still check the log before you paste it anywhere.

| Message | What to do |
| --- | --- |
| *Could not sign in* | Wrong email, phone format or password. Try the same login in the iSmart app. A phone account needs the country code. |
| *MG iSmart did not respond* / *took too long* | The MG cloud is down or the car is asleep. Wait a minute and try again. |
| *This account has no MG5 Electric* | The car is not shared with this account yet, or the share was not accepted. |
| *... was rejected by the car: return code 4* | Too many commands in a short time, or the car has used its remote commands since the last drive. Wait, or drive the car once. |
| *MG5 password* repair notice | The password was changed. Open the notice and enter the new one. |
| Phone app keeps logging out | Home Assistant is using your phone account. Set up the secondary account (step 1). |
| 12 V battery warning in the car | Avoid automations that press **Refresh** often. Normal polling does not wake the car. |

### Update or remove

- **Update:** replace the `/config/custom_components/mg5` folder with the new version (or press **Update** in HACS) and restart.
- **Remove:** **Settings → Devices & services → MG5 → ⋮ → Delete**, then delete `/config/custom_components/mg5` and restart.

## 12 V battery

A live status read wakes the car. Waking it all the time flattens the 12 V battery, and then the car will not start.

Routine updates, about every 30 minutes, read the status SAIC already stored. That does not wake the car. A live read happens:

- once after setup, so state of charge appears
- when you press **Refresh**
- about 20 seconds after a command
- every 5 minutes while a recent status says the car is charging or the climate is running

If that “running” flag is hours old, it is ignored.

## Commands

The car accepts about three remote commands between key cycles, and it rejects a second command sent a few seconds after the first (`return code 4`). Commands are queued at least 25 seconds apart.

Set the climate temperature first, then turn it on. The on command includes that temperature. Moving the slider while the climate is already on sends one command after the slider settles. Moving it while the climate is off does not spend a command.

The charging schedule is one command for the whole window. Changing the start, the end or the mode sends all three, using the values currently shown for the other two. Changes within 3 seconds of each other are sent together, and picking what the car already reports sends nothing. Until the car has reported a schedule (after the first live read), the schedule entities show *unknown*. You can still set the first schedule from Home Assistant: whatever the car has not reported is filled in as mode *Disabled* and the window 22:00–06:00, and nothing is sent until you change one of the three entities.

A rejected command raises an error in Home Assistant and fires `mg5_command_failed` with `source` and `error`. The event does not include the account or the full VIN.

## Development

The climate command bytes, the status-to-mode mapping and the command queue were worked out against a real 2022 MG5 with debug logs from the iSmart API, then checked against the generic MG SAIC integration's behaviour on the same car.

This codebase was written with AI assistance (Grok 4.7 for the first implementation, Claude Opus 5.5 for the rewrite) and reviewed line by line, then tested on the car, by the repository owner. The tests, the protocol notes and the profile logic are part of that review. If you reuse the protocol findings, they were verified on one car — an EP21/EP22 series MG5 Electric.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

On Python 3.12 or 3.13 that runs the decoding, command-byte and scheduling tests. On Python 3.14 the same file also installs the pinned Home Assistant test harness (`pytest-homeassistant-custom-component==0.13.375`, Home Assistant 2026.10.4), and `pytest` runs the Home Assistant tests in `tests/ha` too (setup, config flow, re-auth, every control against a mocked iSmart API). CI runs both, and a failure in either fails the build.

The tests use an anonymized 2022 MG5 status (state of charge, voltages, climate status 2, the bogus 72.5 kWh capacity) and check the climate bytes against the iSmart client. They do not contact MG. Lock, climate and charging still have to be tried once on your own car.

Tested on Home Assistant **2026.10.4** with an MG5 Electric 2022 (Long Range, 61.1 kWh). The minimum version in `hacs.json` (2025.1) is the author's stated floor, not something every release has been run against.
