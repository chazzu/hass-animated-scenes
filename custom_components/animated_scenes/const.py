"""Constants for the Animated Scenes integration."""

INTEGRATION_NAME = "Animated Scenes"
DOMAIN = "animated_scenes"
VERSION = "2.0.1"
COMPONENT_COLOR_CONFIG_URL = "https://github.com/chazzu/hass-animated-scenes#color-configuration"

ATTR_COLOR_TEMP = "color_temp"  # Deprecated by HASS, will auto-convert to ATTR_COLOR_TEMP_KELVIN

CONF_EXTERNAL_SWITCHES = "external_switches"

CONF_ANIMATE_BRIGHTNESS = "animate_brightness"
CONF_ANIMATE_COLOR = "animate_color"
CONF_CHANGE_AMOUNT = "change_amount"
CONF_CHANGE_FREQUENCY = "change_frequency"
CONF_CHANGE_SEQUENCE = "change_sequence"
CONF_COLORS = "colors"
CONF_COLOR = "color"
CONF_COLOR_TYPE = "color_type"
CONF_IGNORE_OFF = "ignore_off"
CONF_PLATFORM = "platform"
CONF_PRIORITY = "priority"
CONF_RESTORE = "restore"
CONF_RESTORE_POWER = "restore_power"
CONF_SKIP_RESTORE = "skip_restore"
CONF_TRANSITION = "transition"
CONF_ENTITY_TYPE = "entity_type"

CONF_COLOR_RGB_DICT = "color_rgb_dict"
CONF_COLOR_RGB = "rgb_color"
CONF_COLOR_NEARBY_COLORS = "nearby_colors"
CONF_COLOR_ONE_CHANGE_PER_TICK = "one_change_per_tick"
CONF_COLOR_WEIGHT = "weight"
CONF_COLOR_ADD_COLOR = "color_add_color"
CONF_COLOR_DELETE_COLOR = "color_delete_color"

CONF_COLOR_SELECTOR_MODE = "color_selector_mode"
COLOR_SELECTOR_YAML = "color_selector_yaml"
COLOR_SELECTOR_RGB_UI = "color_selector_rgb_ui"

CONF_ANIMATED_SCENE_SWITCH = "animated_scene_switch"

ENTITY_SCENE = "scene"
ENTITY_ACTIVITY_SENSOR = "activty_sensor"

DEFAULT_ACTIVITY_SENSOR_ICON = "mdi:pound-box"
DEFAULT_ICON = "mdi:lightbulb-multiple-outline"
DEFAULT_TRANSITION = 1
DEFAULT_PRIORITY = 0
DEFAULT_CHANGE_AMOUNT = "all"
DEFAULT_CHANGE_FREQUENCY = 1
DEFAULT_CHANGE_SEQUENCE = False
DEFAULT_ANIMATE_BRIGHTNESS = True
DEFAULT_ANIMATE_COLOR = True
DEFAULT_IGNORE_OFF = True
DEFAULT_RESTORE = True
DEFAULT_RESTORE_POWER = False
DEFAULT_BRIGHTNESS = 255

DEFAULT_COLOR_NEARBY_COLORS = 0
DEFAULT_COLOR_ONE_CHANGE_PER_TICK = False
DEFAULT_COLOR_WEIGHT = 10
DEFAULT_COLOR_ADD_COLOR = False
DEFAULT_COLOR_DELETE_COLOR = False

DEFAULT_MIN_BRIGHT = 70
DEFAULT_MAX_BRIGHT = 100

CHANGE_FREQUENCY_MIN = 0
CHANGE_FREQUENCY_MAX = 60
TRANSITION_MIN = 0
TRANSITION_MAX = 6553
CHANGE_AMOUNT_MIN = 0
CHANGE_AMOUNT_MAX = 65535
BRIGHTNESS_MIN = 0
BRIGHTNESS_MAX = 255

ERROR_CHANGE_AMOUNT_NOT_INT_OR_ALL = "change_amount_not_int_or_all"
ERROR_CHANGE_FREQUENCY_NOT_INT_OR_RANGE = "change_frequency_not_int_or_range"
ERROR_TRANSITION_NOT_INT_OR_RANGE = "transition_not_int_or_range"
ERROR_COLORS_IS_BLANK = "colors_is_blank"
ERROR_COLORS_MALFORMED = "colors_malformed"
ERROR_BRIGHTNESS_NOT_INT_OR_RANGE = "brightness_not_int_or_range"
ABORT_ACTIVITY_SENSOR_NO_OPTIONS = "activity_sensor_no_options"
ABORT_INTEGRATION_NO_OPTIONS = "integration_no_options"

EVENT_NAME_CHANGE = "animated_scenes_change"
EVENT_STATE_STARTED = "started"
EVENT_STATE_STOPPED = "stopped"
