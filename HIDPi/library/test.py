import time
import math

from hidpi import Keyboard, Mouse
from hidpi.keyboard_keys import *
from hidpi.mouse_buttons import *

def test_keyboard():
    print("Testing keyboard...")
    time.sleep(1)
    Keyboard.send_text("Hello, HIDPi!", delay=0.25)
    time.sleep(1)
    Keyboard.send_key(0, KEY_A, hold=1)
    time.sleep(1)
    Keyboard.hold_key(0, KEY_B)
    time.sleep(1)
    Keyboard.release_keys()
    time.sleep(1)

def test_mouse():
    print("Testing mouse (absolute mode)...")
    time.sleep(1)
    
    # Move to center of screen
    Mouse.move_percent(50, 50)
    time.sleep(1)
    
    # Draw a circle around the center using absolute coordinates
    center_x = 16384  # ~50% of 32767
    center_y = 16384
    radius = 3000     # radius in absolute units
    
    for angle in range(0, 360, 2):
        x = int(center_x + radius * math.cos(math.radians(angle)))
        y = int(center_y + radius * math.sin(math.radians(angle)))
        Mouse.move(x, y)
        time.sleep(0.01)
    
    time.sleep(0.5)
    
    # Test left click at center
    Mouse.click(LEFT, center_x, center_y)
    print("Clicked at center")
    
    # Test scroll
    time.sleep(0.5)
    Mouse.scroll(5)
    print("Scrolled up")

if __name__ == "__main__":
    test_keyboard()
    test_mouse()
    print("Tested")
