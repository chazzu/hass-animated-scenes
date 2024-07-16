# Changelog
All notable changes to this project will be documented in this file.

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