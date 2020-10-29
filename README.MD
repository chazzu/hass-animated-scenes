# Animated Scenes
A custom component for [Home Assistant](https://www.home-assistant.io/) to create neat animated light scenes. These aren't really "scenes" in the sense of Home Assistant scenes, but rather switches to turn on/off to start and end an animation.

Features include:
- Remember the state of the lights before animation started, and restore lights to prior state after animation is turned off.
- Automatically disable other scenes when activating another scene.
- Add additional switches to turn off (such as a Flux or Circadian Light switch) when an animation starts.
- Scene switches work as expected with Google Assistant.
- If you turn a light off during an animation, it won't turn it back on. If you turn one on, it will add it to the animation automatically.

### Disclaimer
I have only tested this with my own system as of now. I do plan on fixing any bugs identified by others, and would like to hear feedback though.

### Installation
- Clone this repository: `git clone https://github.com/chazzu/hass-animated-scenes.git`
- If you have not already done so, create a 'custom_components' folder inside the 'config' folder in your Home Assistant installation.
- Create an 'animated_scenes' folder inside your custom_components folder.
- Copy the repository files into the animated_scenes folder.
- Update your configuration.yaml as documented below and then restart your Home Assistant.
- Be sure to look for the new switch entities and add them to your Lovelace dashboard.

### Configuration 

```yaml
switch
- platform: animated_scenes
  name: Red Lights # name of scene
  restore: False # don't restore lights to previous state after scene, defaults to True
  ignore_off: False # if a light in the list is off, turn it on. Defaults to True, meaning lights will be ignored if they are off.
  lights: # list of light entities to modify
  - light.hue_color_lamp_1
  - colors:
    color_type: rgb # use rgb colors
    color: [255, 0, 0]
    brightness: 255 # maximum brightness
    weight: 2 # optional; higher number makes a given color more likely to appear. Default is 10, so you can choose some numbers to be less frequent
    one_change_per_tick: False # optional; defaults to false; only change color OR brightness on each tick, don't do both
  - colors:
    color_type: ct # color temperature colors
    color: 500 # number in mireds
  transition: 2 # take 2 seconds to transition
  change_frequency: 15 # change lights every 15 seconds
  change_amount: all # change all lights every time
  animate_brightness: True # defaults to true to change brightness level
  animate_color: True # defaults to true to change color
```


### Sample Configurations
I did this initially to create an animation that mimics the Haunted House animation for Philips Hue but give me greater control. Here is the setting I settled on:

```yaml
switch:
  - platform: animated_scenes
    name: Spooky Scene
    lights:
      - be sure to list your light entities here
    brightness: [100, 255]
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