"""
HID controller for Raspberry Pi — powered by HIDPi.

Wraps the HIDPi library to convert logical commands (CLICK_A, SCROLL_LEFT, etc.)
into USB HID mouse actions on the exam laptop.

HIDPi configures the Pi as a USB HID gadget with:
    - /dev/hidg0 = Keyboard (8-byte reports)
    - /dev/hidg1 = Mouse (6-byte absolute reports: buttons + X:u16 + Y:u16 + wheel:i8)

Coordinates use absolute positioning (0–32767 range).
"""

import time
from typing import Optional

try:
    from hidpi import Mouse
    from hidpi.mouse_buttons import LEFT
    _HIDPI_AVAILABLE = True
except ImportError:
    _HIDPI_AVAILABLE = False

from raspberry_pi.device_config import HID_MOUSE_DEVICE


class HIDController:
    """
    Writes USB HID reports to emulate mouse actions via HIDPi.

    If the HIDPi library is not installed, falls back to raw
    6-byte report writing for backward compatibility.
    """

    def __init__(self, device_path: str = HID_MOUSE_DEVICE) -> None:
        self._device_path = device_path
        self._use_hidpi = _HIDPI_AVAILABLE

    def move_to_absolute(self, x: int, y: int) -> None:
        """
        Move mouse to absolute coordinates (0–32767 range).

        Args:
            x: Absolute X position (0 = left edge, 32767 = right edge).
            y: Absolute Y position (0 = top edge, 32767 = bottom edge).
        """
        if self._use_hidpi:
            Mouse.move(x, y)
        else:
            self._write_6byte_report(0, x, y, 0)

    def click_at(self, x: int, y: int) -> None:
        """Move to position and perform a left click."""
        if self._use_hidpi:
            Mouse.click(LEFT, x=x, y=y)
        else:
            # Move first
            self._write_6byte_report(0, x, y, 0)
            time.sleep(0.05)
            # Press
            self._write_6byte_report(1, x, y, 0)
            time.sleep(0.05)
            # Release
            self._write_6byte_report(0, x, y, 0)

    def scroll(self, amount: int) -> None:
        """Scroll the mouse wheel (positive = up, negative = down)."""
        if self._use_hidpi:
            Mouse.scroll(amount)
        else:
            self._write_6byte_report(0, 0, 0, amount)

    # ------------------------------------------------------------------
    # Fallback: raw 6-byte absolute report (matches HIDPi descriptor)
    # ------------------------------------------------------------------

    def _write_6byte_report(self, buttons: int, x: int, y: int, wheel: int) -> None:
        """
        Write a 6-byte HID absolute mouse report.

        Format (little-endian):
            byte 0:    buttons bitmap (bit0=left, bit1=right, bit2=middle)
            bytes 1-2: X position (uint16, 0-32767)
            bytes 3-4: Y position (uint16, 0-32767)
            byte 5:    wheel (int8, -127 to 127)
        """
        import struct
        x = max(0, min(32767, int(x)))
        y = max(0, min(32767, int(y)))
        wheel = max(-127, min(127, int(wheel)))
        report = struct.pack("<BHHb", buttons, x, y, wheel)
        self._write_report(report)

    def _write_report(self, report: bytes) -> None:
        """Write a HID report to the gadget device."""
        try:
            with open(self._device_path, "wb") as f:
                f.write(report)
        except FileNotFoundError:
            raise RuntimeError(
                f"HID device not found: {self._device_path}. "
                "Ensure HIDPi is installed: sudo python3 HIDPi/HIDPi_Setup.py"
            )
        except PermissionError:
            raise RuntimeError(
                f"Permission denied on {self._device_path}. "
                "Ensure HIDPi udev rules are applied (reboot after setup)."
            )
