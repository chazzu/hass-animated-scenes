# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Changed

- Modernized the runtime, validation, diagnostics, tests, and release tooling.
  - Upgrade: Requires Home Assistant 2026.3+. Config entries migrate one way to version 2.
  - Defaults: New UI scenes use the same defaults as `start_animation` (`priority: 100`, `restore_power: true`, `change_amount: 1`).
  - Runtime: Stopping a scene restores the lights to their original state. Restarting a scene carries the original state forward without restoring in between. Light commands are sent without waiting for the light, so a slow device can still apply an earlier command last. `change_frequency` now allows up to 3600 seconds (the UI previously stopped at 60). Repeating frequencies must be at least 0.1 seconds, and existing ranges that start at `0` now start at `0.1`.
  - Validation: All services validate their payloads at registration, and service and YAML inputs are checked strictly. A `transition` outside 0-6553 (previously clamped), a fractional `change_amount` or `brightness`, and a range list that is not exactly two values are now rejected. `change_frequency` in services and YAML previously accepted any number or list length; a single value must now be `0` (one-shot) or 0.1 to 3600 seconds. A range must have exactly two values, each from 0.1 to 3600 seconds (a lower bound of `0` becomes 0.1); a reversed range is sorted. Priority outside -1,000,000,000 to 1,000,000,000 is rejected (previously any integer in services and YAML, and -100 to 100 in the UI). Random color mode rejects color weights that sum to zero (previously this crashed at the first update). Color temperatures above 1,000,000 are rejected.
  - Scene names: Names are trimmed of surrounding spaces and must be unique across scenes. Rename existing scenes with duplicate names. Saving the options of a scene with a padded name stores the trimmed name, so update automations or service calls that used the padded name. Saving the options of a scene with a duplicate name asks for a rename.
  - Events and names: Scene switches and the activity sensor now belong to a shared "Animated Scenes" device, so their friendly names change (for example "Animated Scenes Spooky" and "Animated Scenes Activity"); entity IDs are unchanged. The `animated_scenes_change` event no longer fires `stopped` between the old and new run when a scene is restarted. A restart into a repeating scene fires only `started`, and a restart into a one-shot scene (`change_frequency: 0`) fires only `stopped`. A new `updated` state fires when lights are added to or removed from a running scene. Removing the last light fires `stopped`, then `updated`.

## 2.1.1

### Fixed

- ignore_off logic was inverted

## 2.1.0

### Fixed

- Numerous fixes from [Snuffy2](https://github.com/Snuffy2)
  - Fixed deprecated ATTR_COLOR_TEMP
  - Verifies that a light is selected during configuration
  - Updates schema to filter on LIGHT platform
  - Fix random range selection
  - More compatibility with nearby color feature

## 2.0.1

### Fixed

- Upgrade to config flow will fail if you do not have scenes defined in configuration.yaml
- Clicking 'Configure' on Animated Scenes leads to error
- Sometimes logged error on startup

## 2.0.0

### Changes

- [Snuffy2](https://github.com/Snuffy2) has created a config flow for Animated Scenes. This will import the existing YAML configurations and create devices in the UI, as well as provides a new way to add new animations through the UI. The README has been updated accordingly.

### Breaking Changes

- When migrating to the new config flow, the existing activity sensor must be removed through the UI, and then re-added. The readme has been updated with instructions on doing this. This is probably for the best, as the original was misnamed by accident and was too generic.

## 1.2.2

### Fixed

- Fix submitted by @Snuffy2 to replace deprecated async_forward_entry_setup to maintain compatibility with future versions of Home Assistant

## 1.2.1

### Fixed

- If a float is specified for transition time, use random.uniform instead of randrange()
- I haven't been updating the manifest file with versions. Oops.

## 1.2.0

### Added

- Added a new service: remove_lights
- Added a new service: add_lights_to_animation
- Added documentation for new services

### Fixed

- Added some catches so a single light messing up shouldn't stop the animation.
- Fixed issue where you could start two animations with the same name. If you do this now, it will first end the previous animation.
- Fixed issue with change_frequency. This should be optional, allowing you to randomly set a scene without having to animate. If you set no change_frequency, the animation will set all of the lights and then immediately end.
- Changed lighting to use asyncio.gather which should theoretically speed up transitions. Note that you can set really low transition times, and the integration will try to honor that, but you can absolutely crash ZHA or Zigbee2MQTT if you go too crazy.

## 1.1.2

### Fixed

- Issue restoring lights added in the last update.

## 1.1.1

### Fixed

- When restoring state, explicitly restore color mode. Theoretically, this should resolve [#27](https://github.com/chazzu/hass-animated-scenes/issues/27)

## 1.1.0

### Added

- Added this CHANGELOG
- Integration now includes a sensor, requested in [#22](https://github.com/chazzu/hass-animated-scenes/issues/22)
- Added event, animated_scenes_change, which will fire on start and stop of an animation.

### Fixed

- Fixed issue where lights may get overloaded because integration forgot to wait for an update.
- Fixed animation switches starting in an unknown state, they will now all start in 'off' state.
- Changed main loop to look for task done to theoretically resolve an issue where an animation would go rogue and keep running when it shouldn't.
