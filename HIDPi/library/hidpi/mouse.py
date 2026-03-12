"""
The Mouse class provides methods to control a HID mouse device.
It supports absolute positioning (0-32767 range) for Windows compatibility,
relative movement, and mouse button clicks with scroll wheel support.
"""

import struct
import time
from .mouse_buttons import *

MOUSE_DEVICE = "/dev/hidg1"

# Absolute coordinate range (0 to 32767)
MAX_ABS = 32767

class Mouse:
    """
    A class for controlling a HID-compliant mouse device using absolute coordinates.
    
    Coordinates use a 0-32767 range for both X and Y axes, where:
    - (0, 0) is the top-left corner of the screen
    - (32767, 32767) is the bottom-right corner of the screen
    """

    @staticmethod
    def move(x, y, wheel=0):
        """
        Moves the mouse cursor to an absolute position on the screen.
        
        :param x: Absolute X position (0 = left edge, 32767 = right edge).
        :type x: int
        :param y: Absolute Y position (0 = top edge, 32767 = bottom edge).
        :type y: int
        :param wheel: Scroll wheel movement (-127 to 127). Defaults to 0.
        :type wheel: int, optional
        """
        x = max(0, min(MAX_ABS, int(x)))
        y = max(0, min(MAX_ABS, int(y)))
        wheel = max(-127, min(127, int(wheel)))

        # 6-byte report: [buttons, x_low, x_high, y_low, y_high, wheel]
        report = struct.pack('<BHHb', 0, x, y, wheel)
        Mouse._send_report(report)

    @staticmethod
    def move_percent(x_pct, y_pct, wheel=0):
        """
        Moves the mouse cursor using screen percentages (0.0 to 100.0).
        
        :param x_pct: X position as percentage (0.0 = left, 100.0 = right).
        :type x_pct: float
        :param y_pct: Y position as percentage (0.0 = top, 100.0 = bottom).
        :type y_pct: float
        :param wheel: Scroll wheel movement (-127 to 127). Defaults to 0.
        :type wheel: int, optional
        """
        x = int((x_pct / 100.0) * MAX_ABS)
        y = int((y_pct / 100.0) * MAX_ABS)
        Mouse.move(x, y, wheel)

    @staticmethod
    def click(button, x=None, y=None, hold=0):
        """
        Simulates a mouse button click, optionally at a specific position.
        
        :param button: The button to click (LEFT, RIGHT, MIDDLE, or BOTH).
        :type button: int
        :param x: Optional absolute X position to click at (0-32767).
        :type x: int, optional
        :param y: Optional absolute Y position to click at (0-32767).
        :type y: int, optional
        :param hold: Time in seconds to hold the button before releasing.
        :type hold: float, optional
        """
        if x is not None and y is not None:
            x = max(0, min(MAX_ABS, int(x)))
            y = max(0, min(MAX_ABS, int(y)))
        else:
            # Click at current position (send 0,0 with button — 
            # for absolute mode, you should ideally track last position)
            x = 0
            y = 0

        # Press
        report = struct.pack('<BHHb', button, x, y, 0)
        Mouse._send_report(report)
        if hold:
            time.sleep(hold)
        # Release
        report = struct.pack('<BHHb', 0, x, y, 0)
        Mouse._send_report(report)

    @staticmethod
    def scroll(amount):
        """
        Scrolls the mouse wheel.
        
        :param amount: Scroll amount (-127 to 127, positive = up, negative = down).
        :type amount: int
        """
        amount = max(-127, min(127, int(amount)))
        report = struct.pack('<BHHb', 0, 0, 0, amount)
        Mouse._send_report(report)

    @staticmethod
    def _send_report(report):
        """
        Sends a raw HID report to the mouse device.
        
        :param report: The raw HID report data.
        :type report: bytes
        """
        with open(MOUSE_DEVICE, "rb+") as fd:
            fd.write(report)