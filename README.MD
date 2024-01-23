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

## Installation
- Clone this repository: `git clone https://github.com/chazzu/hass-animated-scenes.git`
- If you have not already done so, create a 'custom_components' folder inside the 'config' folder in your Home Assistant installation.
- Create an 'animated_scenes' folder inside your custom_components folder.
- Copy the repository files into the animated_scenes folder.
- In Home Assistant, go to Settings -> Devices & Services. Click Add Integration
- Select the Animated Scenes integration.

## Configuration 

There are three ways to configure an animation.

- Configuring automations which call the 'start_animation' and 'stop_animation' services.
- Using a blueprint to configure the automation quickly.
- By configuring a switch in your configuration.yaml.

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


### Switch Configuration

To add scene switches you want to set up through config.yaml:

```yaml
switch:
- platform: animated_scenes
  name: Red Lights # name of scene
  restore: False # don't restore lights to previous state after scene, defaults to True
  restore_power: True # restore each light's on/off state after scene, defaults to False
  ignore_off: False # if a light in the list is off, turn it on. Defaults to True, meaning lights will be ignored if they are off.
  transition: [1, 2] # take between 1 and 2 seconds to transition; can also just be a number
  change_frequency: [2, 5] # change lights every 2 to 5 seconds; can also just be a number
  change_amount: all # change all lights every time; can also just be a number under 65,535 and under the number of lights in the scene
  change_sequence: True # instead of choosing a color randomly, choose in sequence
  animate_brightness: True # defaults to true to change brightness level
  animate_color: True # defaults to true to change color

  lights: # list of light entities to modify
  - light.hue_color_lamp_1
  
  colors: # See color configuration section for more details
  - color_type: rgb # use rgb colors
    color: [255, 0, 0]
    brightness: 255 # maximum brightness
    weight: 2 # optional; higher number makes a given color more likely to appear. Default is 10, so you can choose lower numbers to be less frequent
    one_change_per_tick: False # optional; defaults to false; only change color OR brightness on each tick, don't do both
```

### Color Configuration

```yaml
  weight: 10 # The higher the number, the more likely a color is to appear in the animation.
  brightness: [0, 255] # Sets a minimum and maximum brightness for this color group; can also just be a single number
  one_change_per_tick: true # If set to true, only the brightness OR color will change at one time
  nearby_colors: 0 # If set to a number between 1 and 100, we won't pick this color but will instead pick a 'nearby' color. This is useful for selecting, for example, a red and getting a series of lights of various shades of red. The number represents how 'far' from the original we might pick a color. This will only work for RGB, RGBW, and RGBWW
```

*For RGB lights*
```yaml
- color_type: rgb_color
  color:
    - 255 # Red value
    - 0 # Green value
    - 0 # Blue value
``` 

*For RGBW lights*
```yaml
- color_type: rgbw_color
  color:
    - 255 # Red value
    - 0 # Green value
    - 0 # Blue value
    - 0 # Cold white
``` 

*For RGBWW lights*
```yaml
- color_type: rgbww_color
  color:
    - 255 # Red value
    - 0 # Green value
    - 0 # Blue value
    - 0 # Cold white
    - 0 # Warm white
``` 

*For XY lights*
```yaml
- color_type: xy_color
  color:
    - 0.3127 # X value
    - 0.3291 # Y value
``` 

*For HS lights*
```yaml
- color_type: hs_color
  color:
    - 200.0 # Hue value
    - 75.0 # Saturation value
``` 

*For Color Temp lights*
```yaml
- color_type: color_temp
  color:
    - 450 # Color temperature in mireds
``` 

*For Color Temp in Kelvin lights*
```yaml
- color_type: color_temp_kelvin
  color:
    - 450 # Color temperature in mireds
``` 

### Sample Configurations
I did this initially to create an animation that mimics the Haunted House animation for Philips Hue but give me greater control. Here is the setting I settled on:

```yaml
switch:
- platform: animated_scenes
  name: Spooky Scene
  lights:
  - be sure to list your light entities here

  colors:
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
    
  transition: [1, 4]
  change_frequency: 5
  change_amount: 6
```

## Usage Tips

### Checking running animations

The Activity sensor is set to the number of currently running animations. The attributes are:

- active: A list of currently running animations.
- active_lights: A list of lights currently in use by animations.

Note that the sensor does not update immediately, so there may be a few seconds from when an animation is stopped til it is reflected on the sensor.

Here is a simple example script which would stop all currently running animations.

```yaml
alias: Stop All Animations
sequence:
  - variables:
      animations: "{{ state_attr('sensor.activity', 'active')|list }}"
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
      kelvin: 2800
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
