"""
Raspberry Pi device configuration.

Configuration for the HID injector running on the Pi.
"""

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 9000

HID_MOUSE_DEVICE = "/dev/hidg1"      # HIDPi registers mouse as hidg1
HID_KEYBOARD_DEVICE = "/dev/hidg0"   # HIDPi registers keyboard as hidg0
