# Changelog
All notable changes to this project will be documented in this file.

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