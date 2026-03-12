# HIDPi — Full Project Architecture Analysis

## What is This Project?

**HIDPi** turns your Raspberry Pi (4B or 5) into a **USB HID device** — meaning when you plug the Pi into another computer via USB-C, that computer sees it as an actual **keyboard and mouse**, not a storage drive or serial port. You can then run Python scripts on the Pi to type text, press keys, move the mouse, and click buttons — all on the connected host computer.

> [!IMPORTANT]
> This uses the Pi's **USB-C port as a Device port** (not a host port). You MUST use a data-capable USB-A to USB-C (or USB-C to USB-C) cable between the Pi and the host computer. The regular USB-A ports on the Pi cannot be used for this.

---

## The Big Picture — How Does It Work?

```
         Raspberry Pi 5
┌─────────────────────────────────────┐
│                                     │        USB Cable
│  Python Script                      │       (data capable)
│  (your automation code)             │◄──────────────────────► Host Computer
│       │                             │                         (Mac/Win/Linux)
│       ▼                             │
│  hidpi library                      │
│   ├── Keyboard class                │
│   └── Mouse class                   │
│       │                             │
│       ▼                             │
│  writes to /dev/hidg0 (keyboard)    │
│  writes to /dev/hidg1 (mouse)       │
│       │                             │
│       ▼                             │
│  Linux USB Gadget (ConfigFS)        │
│  (kernel presents Pi as USB HID)    │
└─────────────────────────────────────┘
```

The Pi runs Linux. Linux has a **USB Gadget framework** in its kernel — this lets you configure the Pi's USB-C port to *emulate* a USB device (like a keyboard/mouse) instead of just charging. The HIDPi project wires all of this up automatically.

---

## Project File Structure

```
HIDPi/
├── HIDPi_Setup.py          ← Main setup/install script (run once as root)
├── assets/
│   ├── sendkey.png         ← Reference image
│   └── hut1_12v2.pdf       ← Official USB HID Usage Tables spec (PDF)
└── library/
    ├── setup.py            ← pip install config for the hidpi package
    ├── test.py             ← Demo script (keyboard typing + mouse circle)
    └── hidpi/              ← The actual Python library you import
        ├── __init__.py     ← Exports Keyboard and Mouse classes
        ├── keyboard.py     ← Keyboard class implementation
        ├── keyboard_keys.py← HID keycodes + modifier constants
        ├── mouse.py        ← Mouse class implementation
        └── mouse_buttons.py← Mouse button constants
```

---

## Phase 1 — The Setup Script ([HIDPi_Setup.py](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/HIDPi_Setup.py))

This script is the **one-time installer**, run as root on the Pi. It has two phases:

### Phase 1a — Firmware Config (requires reboot)

The script edits `/boot/firmware/config.txt` and adds:
```
dtoverlay=dwc2
modules-load=dwc2,g_hid
```

- **`dtoverlay=dwc2`** — Enables the **DWC2 USB Dual-Role Controller** overlay. This tells the Pi's hardware that its USB-C port can act as a *device* (slave), not just a host (master).
- **`modules-load=dwc2,g_hid`** — Automatically loads the kernel modules `dwc2` (USB controller driver) and `g_hid` (USB HID Gadget driver) at boot.

After writing these lines, the script exits and requires a **reboot**. On next boot a `systemd` service runs the same script again (the second phase).

### Phase 1b — systemd Service Creation

Before rebooting, the script also installs itself as a systemd service:
```
/etc/systemd/system/HIDPi.service
```
This service runs [HIDPi_Setup.py](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/HIDPi_Setup.py) after every boot with `Type=oneshot`. On first boot after reboot, it runs Phase 2.

---

## Phase 2 — USB Gadget Initialization ([setup_hid_gadget()](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/HIDPi_Setup.py#129-184))

This is where the magic happens. Linux exposes a virtual filesystem at `/sys/kernel/config/usb_gadget/` called **ConfigFS**. By writing files into this directory, you configure what USB device the Pi pretends to be.

### Step-by-step Gadget Setup

**1. Load kernel modules:**
```bash
modprobe dwc2
modprobe libcomposite
```
`libcomposite` is the kernel module that provides the ConfigFS USB gadget framework.

**2. Create gadget directory structure:**
```
/sys/kernel/config/usb_gadget/hid_gadget/
    strings/0x409/          ← English string descriptors
    configs/c.1/            ← Configuration 1
        strings/0x409/
```

**3. Write USB device identity:**

| File | Value | Meaning |
|------|-------|---------|
| `idVendor` | `0x1f00` | USB Vendor ID (fake) |
| `idProduct` | `0x2012` | USB Product ID (fake) |
| `strings/0x409/manufacturer` | `Rikka` | Manufacturer name |
| `strings/0x409/product` | `HIDPi` | Product name |
| `configs/c.1/MaxPower` | `250` | Max 250mA power draw |

**4. Create the two HID function devices** (keyboard + mouse) — covered in detail below.

**5. Link functions to the config:**
```python
os.symlink(function_path, config_path/hid.usb0)
os.symlink(function_path, config_path/hid.usb1)
```
This tells the gadget: "include both keyboard and mouse in the USB configuration."

**6. Bind to the UDC (USB Device Controller):**
```python
with open("/sys/kernel/config/usb_gadget/hid_gadget/UDC", "w") as f:
    f.write(udc_device)   # e.g. "fe980000.usb"
```
This activates the whole gadget. The moment this is written, the host computer detects a new HID device.

**7. Create udev rule:**
```
KERNEL=="hidg*", SUBSYSTEM=="hidg", MODE="0666"
```
This makes `/dev/hidg0` and `/dev/hidg1` readable/writable without root, so your Python scripts can run as a normal user.

---

## The Keyboard — Deep Dive

### HID Report Descriptor (the "contract")

When the Pi plugs in, it sends a **HID Report Descriptor** to the host. This is a binary specification telling the host exactly what format the data will be in. Here's the keyboard descriptor:

```python
b"\x05\x01\x09\x06\xa1\x01"  # Usage Page (Generic Desktop), Usage (Keyboard), Collection (Application)
b"\x05\x07\x19\xe0\x29\xe7"  # Usage Page (Keyboard), Usage Min (0xE0 = Left Ctrl), Usage Max (0xE7 = Right GUI)
b"\x15\x00\x25\x01"          # Logical Min 0, Logical Max 1
b"\x75\x01\x95\x08\x81\x02"  # Report Size 1 bit, Count 8, Input (Data, Variable) → 8 modifier bits
b"\x95\x01\x75\x08\x81\x01"  # Report Count 1, Size 8 bits, Input (Constant) → 1 reserved byte
b"\x95\x05\x75\x01"          # Report Count 5, Size 1 bit
b"\x05\x08\x19\x01\x29\x05"  # Usage Page (LEDs), Min 1, Max 5
b"\x91\x02"                   # Output (Data, Variable) → 5 LED bits (NumLock, CapsLock, etc.)
b"\x95\x01\x75\x03\x91\x01"  # Report Count 1, Size 3 bits, Output (Constant) → 3 padding bits
b"\x95\x06\x75\x08"          # Report Count 6, Size 8 bits
b"\x15\x00\x25\x65"          # Min 0, Max 0x65
b"\x05\x07\x19\x00\x29\x65"  # Usage Page (Keyboard), Min Key 0, Max Key 0x65
b"\x81\x00\xc0"               # Input (Data, Array) → 6 keycodes, End Collection
```

This tells the host: **"each report is 8 bytes: 1 modifier byte + 1 reserved byte + 6 keycode bytes"**

### The 8-Byte Keyboard Report

```
Byte 0:  [Modifier bitmap]   — which modifier keys are held
Byte 1:  [Reserved]          — always 0x00
Byte 2:  [Keycode 1]         — first key pressed
Byte 3:  [Keycode 2]         — second key (for combos)
Byte 4:  [Keycode 3]
Byte 5:  [Keycode 4]
Byte 6:  [Keycode 5]
Byte 7:  [Keycode 6]         — up to 6 simultaneous keys
```

### Modifier Byte Bitmap

Each bit in Byte 0 represents a modifier key:

| Bit | Value | Key |
|-----|-------|-----|
| 0 | `0x01` | Left Ctrl |
| 1 | `0x02` | Left Shift |
| 2 | `0x04` | Left Alt |
| 3 | `0x08` | Left GUI (Win/Cmd) |
| 4 | `0x10` | Right Ctrl |
| 5 | `0x20` | Right Shift |
| 6 | `0x40` | Right Alt |
| 7 | `0x80` | Right GUI |

You can combine modifiers with bitwise OR: `KEY_LEFT_CTRL | KEY_LEFT_SHIFT` = `0x03`

### How [keyboard.py](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/keyboard.py) Works

**[send_key(modifiers, *keys, hold=0)](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/keyboard.py#28-50)**
```python
report = [0] * 8          # 8 zero bytes
report[0] = modifiers     # set modifier byte
report[2] = keys[0]       # set first keycode at byte 2
# ...up to 6 keys at bytes 2-7
Keyboard._send_report(bytes(report))   # write to /dev/hidg0
time.sleep(hold)
Keyboard.release_keys()   # send all-zeros report to "lift" the keys
```

**[send_text("Hello")](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/keyboard.py#77-98)**
1. Iterates each character
2. Looks up character in `KEY_MAPPINGS` dict → gets HID keycode
3. If uppercase: sets `KEY_LEFT_SHIFT` in modifiers
4. Calls [send_key()](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/keyboard.py#28-50) for each character

**[hold_key()](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/keyboard.py#51-68)** — same as [send_key()](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/keyboard.py#28-50) but never sends the release report, so the key stays pressed until [release_keys()](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/keyboard.py#69-76) is called.

**[_send_report(report)](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/mouse.py#44-59)** — opens `/dev/hidg0` and writes 8 bytes. That's it. The kernel sends these bytes over USB to the host computer, which interprets them as keyboard events.

### Key Codes ([keyboard_keys.py](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/keyboard_keys.py))

These are standard **USB HID Usage IDs** from the official USB HID spec (the PDF in `assets/`):
- Letters: `KEY_A = 0x04` through `KEY_Z = 0x1D`
- Numbers: `KEY_1 = 0x1E` through `KEY_0 = 0x27`
- Special: `KEY_ENTER = 0x28`, `KEY_ESC = 0x29`, `KEY_SPACE = 0x2C`
- F-keys: `KEY_F1 = 0x3A` through `KEY_F20 = 0x6F`
- Arrows, Page Up/Down, Home/End, etc.

---

## The Mouse — Deep Dive

### HID Report Descriptor

```python
b"\x05\x01\x09\x02\xa1\x01"  # Usage Page (Generic Desktop), Usage (Mouse), Collection (Application)
b"\x09\x01\xa1\x00"           # Usage (Pointer), Collection (Physical)
b"\x05\x09\x19\x01\x29\x03"  # Usage Page (Buttons), Button 1 to Button 3
b"\x15\x00\x25\x01"           # Logical Min 0, Max 1
b"\x95\x03\x75\x01\x81\x02"  # Report Count 3, Size 1 bit, Input → 3 button bits
b"\x95\x01\x75\x05\x81\x03"  # Report Count 1, Size 5 bits, Input (Constant) → 5 padding bits
b"\x05\x01\x09\x30\x09\x31"  # Usage Page (Generic Desktop), Usage X, Usage Y
b"\x15\x81\x25\x7f"           # Logical Min -127, Max 127
b"\x75\x08\x95\x02\x81\x06"  # Size 8 bits, Count 2, Input (Relative) → X and Y movement
b"\xc0\xc0"                    # End Collection, End Collection
```

This tells the host: **"each report is 4 bytes: 1 button byte + 1 X byte + 1 Y byte + 1 wheel byte"** (report_length=4)

### The 4-Byte Mouse Report

```
Byte 0:  [Button bitmap]    — bit 0=Left, bit 1=Right, bit 2=Middle
Byte 1:  [X movement]       — signed, -127 to +127 (relative)
Byte 2:  [Y movement]       — signed, -127 to +127 (relative)
Byte 3:  [Wheel]            — scroll wheel movement
```

The mouse uses **relative movement** — each report moves the cursor *by* X and Y pixels, not to an absolute position.

### How [mouse.py](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/mouse.py) Works

**[move(x, y, wheel=0)](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/mouse.py#16-30)**
```python
report = bytes([0, x & 0xFF, y & 0xFF, wheel & 0xFF])
Mouse._send_report(report)
```
Writes 4 bytes to `/dev/hidg1`. The `& 0xFF` mask handles signed negative values (e.g., -10 becomes `0xF6`).

**[click(button, hold=0)](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/mouse.py#31-43)**
```python
Mouse._send_report(bytes([button, 0, 0, 0]), hold)  # press
Mouse._send_report(bytes([0, 0, 0, 0]), hold)        # release
```

**Mouse button constants** ([mouse_buttons.py](file:///c:/Users/jumes/Downloads/HIDPi/HIDPi/library/hidpi/mouse_buttons.py)):
```python
LEFT   = 1   # 0b00000001
RIGHT  = 2   # 0b00000010
BOTH   = 3   # 0b00000011
MIDDLE = 4   # 0b00000100
```

---

## Data Flow Summary

```
Your Python Code
      │
      │  Keyboard.send_text("Hello")
      ▼
keyboard.py: builds 8-byte HID report
      │
      │  write to /dev/hidg0
      ▼
Linux Kernel USB Gadget (ConfigFS + g_hid)
      │
      │  USB HID interrupt transfer
      ▼
Host Computer USB HID Driver
      │
      │  Keyboard event "H" (with Shift modifier)
      ▼
Active application on the Host Computer
```

---

## Key Technical Concepts Explained Simply

| Concept | What It Is | Why It Matters |
|---------|-----------|----------------|
| **USB HID** | Human Interface Device standard | The universal protocol keyboards/mice use |
| **USB Gadget Mode** | Pi's USB-C acts as a device, not a host | Lets the Pi pretend to be a keyboard/mouse |
| **ConfigFS** | Linux virtual filesystem in `/sys/kernel/config` | How you configure USB gadgets without compiling code |
| **DWC2 driver** | DesignWare USB 2.0 controller driver | The hardware driver for the Pi's USB-C port |
| **HID Report Descriptor** | Binary schema sent at USB connect time | Tells the host what format to expect data in |
| **HID Report** | 4 or 8 bytes written to `/dev/hidg*` | The actual keyboard/mouse data |
| **`/dev/hidg0`** | Keyboard device file | Writing here = typing on the host |
| **`/dev/hidg1`** | Mouse device file | Writing here = moving/clicking on the host |
| **Relative mouse** | X,Y are *offsets*, not coordinates | Each move is delta from current position |
| **N-Key Rollover** | Up to 6 keys simultaneously | Byte 2–7 of keyboard report |

---

## Limitations & Notes from the Author

- **Mouse doesn't work properly on Windows** — the relative mouse HID descriptor may need to be adjusted for Windows. Manual raw commands can still be used.
- **Pi Zero / Pico vs Pi 4/5** — Most tutorials only showed the Zero working as HID. This project specifically proves the Pi 4B and 5 work too.
- **F21–F24 keys are commented out** — they apparently don't work and are left as comments.
- **Mouse movement is relative** — there's no way to jump to an absolute screen position without knowing the current cursor position first.
- **USB-C port only** — the regular USB-A ports on the Pi simply cannot do gadget mode.

---

## How You'd Use It (After Setup)

```python
from hidpi import Keyboard, Mouse
from hidpi.keyboard_keys import *
from hidpi.mouse_buttons import *

# Type some text on the connected computer
Keyboard.send_text("Hello World", delay=0.1)

# Press Ctrl+C
Keyboard.send_key(KEY_LEFT_CTRL, KEY_C)

# Move mouse in a circle
import math
for angle in range(0, 360, 2):
    x = int(5 * math.cos(math.radians(angle)))
    y = int(5 * math.sin(math.radians(angle)))
    Mouse.move(x, y)

# Left click
Mouse.click(LEFT)
```
