# Animated Scenes

A custom component for [Home Assistant](https://www.home-assistant.io/) to create neat animated light scenes. These aren't really "scenes" in the sense of Home Assistant scenes, but rather switches to turn on/off to start and end an animation.

Features include:

- Remember the state of the lights before animation started, and restore lights to prior state after animation is turned off.
- Automatically disable other scenes when activating another scene.
- Add additional switches to turn off (such as a Flux or Circadian Light switch) when an animation starts.
- Scene switches work as expected with Google Assistant.
- If you turn a light off during an animation, it won't turn it back on. If you turn one on, it will add it to the animation automatically.

## Disclaimer

I have only tested this with my own system as of now. I do plan on fixing any bugs identified by others, and would like to hear feedback though.

## HACS Installation

- Add the following custom repository to HACS: `https://github.com/chazzu/hass-animated-scenes.git`
- Reload Home Assistant
- In Home Assistant, go to Settings -> Devices & Services. Click Add Integration
- Select the "Animated Scenes" integration.

## Manual Installation

- Clone this repository: `git clone https://github.com/chazzu/hass-animated-scenes.git`
- If you have not already done so, create a 'custom_components' folder inside the 'config' folder in your Home Assistant installation.
- Create an 'animated_scenes' folder inside your custom_components folder.
- Copy the repository files into the animated_scenes folder.
- In Home Assistant, go to Settings -> Devices & Services. Click Add Integration
- Select the "Animated Scenes" integration.

## Configuration

There are three ways to configure an animation.

- Configure an animation through the config flow in Home Assistant, by going to Settings -> Devices & services -> Animated Scenes -> Add Device
- Configuring automations which call the 'start_animation' and 'stop_animation' services.
- Using a blueprint to configure the automation quickly.

### Adding an animated scene with new config flow

In order to add an animated scene through the UI, you can go to Settings -> Devices & services -> Animated Scenes -> Add Device.

This will start a config flow with guidance on setting up. Note that the color config takes place on a separate screen after you submit the first form.

### Automation Configuration

First, I would recommend setting up a toggle helper.

- Go to Settings -> Devices & Services.
- Click Helpers in the top bar.
- Choose Create Helper at the bottom right.
- Select Toggle as your Helper type.
- Name and configure your Helper.

Now you can set up an automation so that when the toggle is flipped, the animation starts and stops.

- Go to Settings -> Automations & Scenes
- Click Create Automation
- Click Create new Automation
- Add your toggle as a trigger, from Off to On
- Add a Call Service action, with "animated_scene: Start Animation" as the service to call.
- The configuration parameters are pre-filled with descriptions, so configure as you wish.

For configuring colors, you can choose from the following options, see [Color Configuration](#color-configuration)

### Color Configuration

```yaml
  weight: 10 # The higher the number, the more likely a color is to appear in the animation.
  brightness: [0, 255] # Sets a minimum and maximum brightness for this color group; can also just be a single number
  one_change_per_tick: true # If set to true, only the brightness OR color will change at one time
  nearby_colors: 0 # If set to a number between 1 and 100, we won't pick this color but will instead pick a 'nearby' color. This is useful for selecting, for example, a red and getting a series of lights of various shades of red. The number represents how 'far' from the original we might pick a color. This will only work for RGB, RGBW, and RGBWW
```

#### For RGB lights

```yaml
- color_type: rgb_color
  color:
    - 255 # Red value
    - 0 # Green value
    - 0 # Blue value
```

#### For RGBW lights

```yaml
- color_type: rgbw_color
  color:
    - 255 # Red value
    - 0 # Green value
    - 0 # Blue value
    - 0 # Cold white
```

#### For RGBWW lights

```yaml
- color_type: rgbww_color
  color:
    - 255 # Red value
    - 0 # Green value
    - 0 # Blue value
    - 0 # Cold white
    - 0 # Warm white
```

#### For XY lights

```yaml
- color_type: xy_color
  color:
    - 0.3127 # X value
    - 0.3291 # Y value
```

#### For HS lights

```yaml
- color_type: hs_color
  color:
    - 200.0 # Hue value
    - 75.0 # Saturation value
```

#### For Color Temp in Kelvin lights

```yaml
- color_type: color_temp_kelvin
  color:
    - 4500 # Color temperature in Kelvin
```

### Sample Configurations

I did this initially to create an animation that mimics the Haunted House animation for Philips Hue but give me greater control. Here is the setting I settled on:

```yaml
  - color_type: rgb_color
    color: [ 247, 95, 28 ]
    one_change_per_tick: True
  - color_type: rgb_color
    color: [ 255, 154, 0 ]
    one_change_per_tick: True
    weight: 5
  - color_type: rgb_color
    color: [ 136, 30, 228 ]
    one_change_per_tick: True
  - color_type: rgb_color
    color: [ 133, 226, 31 ]
    one_change_per_tick: True
  - color_type: rgb_color
    color: [ 148,0,211 ]
    one_change_per_tick: True
  - color_type: rgb_color
    color: [ 200, 10, 10 ]
    one_change_per_tick: True
  - color_type: rgb_color
    color: [ 135, 169, 107 ]
    one_change_per_tick: True
  - color_type: rgb_color
    color: [ 103, 76, 71 ]
    one_change_per_tick: True
```

## Usage Tips

### Checking running animations

You can add an activity sensor by going to Settings -> Devices & services -> Animated Scenes -> Add Device and choosing 'Create the Activity Sensor.'

The Activity sensor is set to the number of currently running animations. The attributes are:

- active: A list of currently running animations.
- active_lights: A list of lights currently in use by animations.

Note that the sensor does not update immediately, so there may be a few seconds from when an animation is stopped til it is reflected on the sensor.

Here is a simple example script which would stop all currently running animations.

```yaml
alias: Stop All Animations
sequence:
  - variables:
      animations: "{{ state_attr('sensor.animated_scenes_activity_sensor', 'active')|list }}"
  - alias: Repeat for each animation
    repeat:
      for_each: "{{ animations }}"
      sequence:
        - alias: Stop animation
          service: animated_scenes.stop_animation
          data:
            name: "{{ repeat.item }}"
mode: single
```

### Freeing up lights

A common use case that I ran into is wanting to animate the whole house for fun. However, we should be able to easily remove lights from an animation in order to control them manually. You can do this using the `remove_lights` service.

If the animation specifies 'restore_lights' then normally it would set the lights back the state they were in. However, we may not want that to happen. For example, if an animation is running in a room and you hit the light switch to on, you may want the lights to just go to their normal color and brightness and not first get restored back to 'off' first.

```yaml
alias: Remove Living Room Lights
description: When Living Room light switch is clicked, just turn it on even if it's animated.
trigger:
  - platform: state
    entity_id:
      - sensor.living_room_light_switch_action
    to: up_single
sequence:
  - service: animated_scenes.remove_lights
    data:
      lights:
        - light.living_room_1
        - light.living_room_2
      skip_restore: true
  - service: light.turn_on
    target:
      entity_id:
        - light.living_room_1
        - light.living_room_2
    data:
      color_temp_kelvin: 2800
      brightness_pct: 100
```

### Adding lights to an animation

Once an animation is running, you can also add additional lights to it using the `add_lights_to_animation` service.

```yaml
service: animated_scenes.add_lights_to_animation
data:
  lights:
    - light.living_room_1
  name: Animation ID
```

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
