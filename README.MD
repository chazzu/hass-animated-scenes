# Animated Scenes

[![Integration Usage][integration-usage-shield]][integration-usage]

[![GitHub Downloads][downloads-shield]][releases]
[![GitHub Latest Downloads][downloads-latest-shield]][releases]
[![GitHub Release][releases-shield]][releases]
[![GitHub Release Date][release-date-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![Coverage][coverage-shield]][coverage]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

Animated Scenes is a custom Home Assistant integration for creating light animations that you can turn on and off like switches.

Each animated scene can:

- Save the current light state before the animation starts.
- Restore lights when the animation stops.
- Add or remove lights while an animation is running.
- Let higher-priority animations take control when multiple animations include the same light.

Animated scenes are not Home Assistant scene entities. They are switch entities that start and stop an animation.

## HACS Installation

1. In HACS, add this custom repository:

   ```text
   https://github.com/chazzu/hass-animated-scenes
   ```

1. Download Animated Scenes from HACS.
1. Restart Home Assistant.
1. Go to **Settings > Devices & Services**.
1. Select **Add Integration**.
1. Search for **Animated Scenes**.

## Create An Animated Scene

1. Go to **Settings > Devices & Services**.
1. Open **Animated Scenes**.
1. Select **Add Device**.
1. Choose **Create a New Animated Scene**.
1. Fill in the scene options and select the lights to animate.
1. Choose a color selector mode:
   - **RGB UI** for simple RGB color selection in the Home Assistant UI.
   - **YAML** for advanced color types such as RGBW, RGBWW, XY, HS, and color temperature.
1. Submit the color step to create the switch.

The integration creates one switch entity per animated scene. Turning that switch on starts the animation. Turning it off stops the animation.

To edit a scene later, open the scene entry from **Settings > Devices & Services > Animated Scenes** and use **Configure**.

## Scene Options

| Option | What it does |
| --- | --- |
| `name` | The scene name. This is also the animation name used by services. |
| `priority` | Higher-priority animations win when multiple animations want the same light. |
| `transition` | How long each light transition takes, in seconds. |
| `change_frequency` | Use scalar `0` for one initial update followed by immediate release. Repeating values and both range bounds must be `0.1` through `3600` seconds. |
| `change_amount` | How many lights change each tick. Use a number, a range like `[1, 3]`, or `all`. |
| `ignore_off` | When enabled, the animation ignores the current off state and includes those lights. When disabled, lights that are off are skipped. |
| `restore` | Restore previous light state when the animation ends. |
| `restore_power` | Turn lights that were originally off back off when restoring. |
| `change_sequence` | Use colors in the listed order instead of choosing randomly. |
| `brightness` | Brightness for the animation or color group. Use a number or a range like `[70, 255]`. |
| `animate_brightness` | Continue changing brightness while the animation runs. |
| `animate_color` | Continue changing colors while the animation runs. |
| `lights` | The lights included in the animation. |

A scalar `change_frequency: 0` creates a one-shot scene: it performs the initial light update and then releases the animation. Normal release settings still apply. With `restore: true`, prior light attributes are restored; `restore_power` controls whether lights that were originally off are turned back off. Set `restore: false` when the one-shot change should persist.

## Color Configuration

For simple RGB animations, use the RGB UI color selector. You can add multiple colors and set each color's brightness, weight, nearby-color behavior, and one-change-per-tick behavior from the UI.

<details>
<summary><h3>YAML</h3></summary>

Use YAML color configuration when you need a color format other than RGB or want to paste a complete color list.

Each YAML color item supports these optional fields:

```yaml
weight: 10
brightness: [70, 255]
one_change_per_tick: true
nearby_colors: 0
```

| Field | What it does |
| --- | --- |
| `weight` | Higher values make that color more likely to be selected. |
| `brightness` | A brightness value from `0` to `255`, or a range like `[70, 255]`. |
| `one_change_per_tick` | When true, only brightness or color changes on a single update. |
| `nearby_colors` | For RGB colors, choose a nearby color instead of the exact color. Use `0` to disable, or `1` through `10` to increase the variation. |

### RGB

```yaml
- color_type: rgb_color
  color: [255, 0, 0]
  brightness: [70, 255]
  weight: 10
```

### RGBW

```yaml
- color_type: rgbw_color
  color: [255, 0, 0, 0]
```

### RGBWW

```yaml
- color_type: rgbww_color
  color: [255, 0, 0, 0, 0]
```

### XY

```yaml
- color_type: xy_color
  color: [0.3127, 0.3291]
```

### HS

```yaml
- color_type: hs_color
  color: [200.0, 75.0]
```

### Color Temperature

```yaml
- color_type: color_temp_kelvin
  color: 4500
```

### Example Color List

```yaml
- color_type: rgb_color
  color: [247, 95, 28]
  one_change_per_tick: true
- color_type: rgb_color
  color: [255, 154, 0]
  one_change_per_tick: true
  weight: 5
- color_type: rgb_color
  color: [136, 30, 228]
  one_change_per_tick: true
- color_type: rgb_color
  color: [133, 226, 31]
  one_change_per_tick: true
```

</details>

## Use Animated Scenes In Automations

For most dashboards, voice assistants, and automations, use the animated scene switch directly.

Example:

```yaml
alias: Start spooky lights at sunset
mode: single
triggers:
  - trigger: sun
    event: sunset
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.animated_scenes_spooky
```

You can also call Animated Scenes services directly when you want to build an animation dynamically from an automation.

## Services

Animated Scenes provides these services:

- `animated_scenes.start_animation`
- `animated_scenes.stop_animation`
- `animated_scenes.remove_lights`
- `animated_scenes.add_lights_to_animation`

### Start An Animation

```yaml
action: animated_scenes.start_animation
data:
  name: Spooky
  lights:
    - light.living_room_1
    - light.living_room_2
  change_frequency: 1
  change_amount: all
  transition: 1
  colors:
    - color_type: rgb_color
      color: [255, 0, 0]
      brightness: [70, 255]
```

The `name` is the animation ID. Use the same name to stop it later.

### Stop An Animation

```yaml
action: animated_scenes.stop_animation
data:
  name: Spooky
```

### Remove Lights From Animations

Use `remove_lights` when you want to take manual control of lights that are currently animated.

```yaml
action: animated_scenes.remove_lights
data:
  lights:
    - light.living_room_1
    - light.living_room_2
  skip_restore: true
```

If `skip_restore` is true, the integration does not restore those lights to their pre-animation state.

### Add Lights To A Running Animation

Add lights by animation name:

```yaml
action: animated_scenes.add_lights_to_animation
data:
  name: Spooky
  lights:
    - light.living_room_3
```

Or add lights by selecting an Animated Scenes switch:

```yaml
action: animated_scenes.add_lights_to_animation
data:
  animated_scene_switch: switch.animated_scenes_spooky
  lights:
    - light.living_room_3
```

Use either `name` or `animated_scene_switch`, not both.

## Validation Limits

Animated Scenes validates UI configuration and service calls before starting an animation.

| Field | Allowed values |
| --- | --- |
| `transition` | `0` to `6553` seconds, or a two-item range like `[0.5, 2]`. |
| `change_frequency` | Scalar `0` performs one initial update and immediately releases. Repeating values and both bounds of a range such as `[0.1, 1.5]` must be `0.1` through `3600` seconds. |
| `change_amount` | An integer, a two-item range like `[1, 3]`, or `all`. |
| `brightness` | `0` to `255`, or a two-item range like `[70, 255]`. |
| `colors` | At least one color is required. |
| `lights` | At least one light is required. |

When a scene is reloaded, removed, or unloaded, any matching running animation is stopped and its light ownership is released.

## Activity Sensor

You can create an activity sensor from **Settings > Devices & Services > Animated Scenes > Add Device** by choosing **Create the Activity Sensor**.

The sensor state is the number of active animations. It also exposes these attributes:

- `active`: running animation names.
- `active_lights`: lights currently owned by animations.

The sensor updates when animations start, stop, or change light ownership.

Example script to stop all running animations:

```yaml
alias: Stop all Animated Scenes animations
mode: single
sequence:
  - variables:
      animations: "{{ state_attr('sensor.animated_scenes_activity_sensor', 'active') or [] }}"
  - repeat:
      for_each: "{{ animations }}"
      sequence:
        - action: animated_scenes.stop_animation
          data:
            name: "{{ repeat.item }}"
```

## Diagnostics

Animated Scenes supports Home Assistant diagnostics downloads from the integration entry. Diagnostics include redacted config-entry data and runtime counts such as active animations, active lights, and stored light states.

## Development

- Use Python 3.14.
- Install local development dependencies with `./.venv/bin/python -m pip install --group dev -e .`.
- Run tests with `./.venv/bin/pytest`.
- Run linting and formatting checks with `./.venv/bin/prek run -a`.


[integration-usage-shield]: https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json&query=%24.animated_scenes.total&style=for-the-badge
[integration-usage]: https://analytics.home-assistant.io/custom_integrations.json
[commits-shield]: https://img.shields.io/github/last-commit/chazzu/hass-animated-scenes?style=for-the-badge
[commits]: https://github.com/chazzu/hass-animated-scenes/commits/main
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/chazzu/hass-animated-scenes.svg?style=for-the-badge
[downloads-latest-shield]: https://img.shields.io/github/downloads-pre/chazzu/hass-animated-scenes/latest/total?style=for-the-badge
[downloads-shield]: https://img.shields.io/github/downloads/chazzu/hass-animated-scenes/total?style=for-the-badge&label=total%20downloads
[release-date-shield]: https://img.shields.io/github/release-date/chazzu/hass-animated-scenes?display_date=published_at&style=for-the-badge
[releases-shield]: https://img.shields.io/github/v/release/chazzu/hass-animated-scenes?style=for-the-badge
[releases]: https://github.com/chazzu/hass-animated-scenes/releases
[coverage]: https://htmlpreview.github.io/?https://github.com/chazzu/hass-animated-scenes/blob/python-coverage-comment-action-data/htmlcov/index.html
[coverage-shield]: https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/chazzu/hass-animated-scenes/python-coverage-comment-action-data/endpoint.json&style=for-the-badge
