# HIDPi → Simulato Integration Guide

## Summary

HIDPi is a third-party library that converts a Raspberry Pi 4B/5 into a USB HID keyboard + mouse via Linux's ConfigFS USB Gadget framework. Simulato already has a custom HID subsystem (`raspberry_pi/`), but the two implementations have **critical differences** that must be reconciled before HIDPi can replace the existing code.

---

## Architecture Comparison

| Aspect | Simulato (Current) | HIDPi Library |
|--------|-------------------|---------------|
| **Mouse Device** | `/dev/hidg0` | `/dev/hidg1` |
| **Keyboard Device** | `/dev/hidg1` | `/dev/hidg0` |
| **Mouse Report Size** | 5 bytes (`<BHH`) | 6 bytes (`<BHHb`) |
| **Mouse Type** | Absolute (0-32767) | Absolute (0-32767) ✅ |
| **Scroll Support** | ❌ Missing | ✅ Byte 6 = wheel |
| **USB Gadget Setup** | `scripts/setup_pi_hid.sh` | `HIDPi_Setup.py` (systemd service) |
| **Click API** | `hid.click_at(x, y)` | `Mouse.click(LEFT, x, y)` |
| **Keyboard** | Not used | Full keyboard emulation available |
| **udev Rules** | None (requires `sudo`) | Auto-creates `99-hidg.rules` (`MODE=0666`) |

---

## Critical Differences (What Must Change)

### 1. Device Path Swap ⚠️

HIDPi registers keyboard as `hidg0` and mouse as `hidg1`. Simulato currently assumes the **opposite**.

**Change required in `raspberry_pi/device_config.py`:**
```diff
-HID_MOUSE_DEVICE = "/dev/hidg0"
-HID_KEYBOARD_DEVICE = "/dev/hidg1"
+HID_MOUSE_DEVICE = "/dev/hidg1"
+HID_KEYBOARD_DEVICE = "/dev/hidg0"
```

### 2. Mouse Report Format Mismatch ⚠️

Simulato sends a **5-byte** report but HIDPi's descriptor declares a **6-byte** report (includes scroll wheel). This will cause silent failures on the host.

**Change required in `raspberry_pi/hid_controller.py`:**
```diff
-# 5-byte report: buttons + X(16-bit) + Y(16-bit)
-report = struct.pack("<BHH", 0, x, y)
+# 6-byte report: buttons + X(16-bit) + Y(16-bit) + wheel(8-bit)
+report = struct.pack("<BHHb", 0, x, y, 0)
```

All three report writes in `hid_controller.py` (move, press, release) must be updated to 6 bytes.

### 3. Replace Gadget Setup with HIDPi 

Simulato's `start_pi.sh` currently calls `scripts/setup_pi_hid.sh` (a custom gadget setup). HIDPi's `HIDPi_Setup.py` is **more robust** (systemd auto-start, udev rules, proper uninstall, reboot handling).

**Change required:**
- Delete `scripts/setup_pi_hid.sh` (it is replaced by `HIDPi_Setup.py`).
- Update `start_pi.sh` to run `HIDPi_Setup.py` instead.

### 4. Option A: Use HIDPi Library Directly (Recommended)

Instead of maintaining our own `hid_controller.py`, we can **import HIDPi directly**:

```python
# NEW raspberry_pi/hid_controller.py
from hidpi import Mouse
from hidpi.mouse_buttons import LEFT

class HIDController:
    def click_at(self, x: int, y: int) -> None:
        Mouse.click(LEFT, x=x, y=y)
    
    def move_to_absolute(self, x: int, y: int) -> None:
        Mouse.move(x, y)
```

This eliminates our custom report packing and guarantees format compatibility with HIDPi's descriptor.

### 5. Option B: Keep Custom Controller (Simpler)

If you prefer to keep the custom `hid_controller.py`, just apply changes #1 and #2 above. The custom controller will write correct 6-byte reports to the correct device path.

---

## Setup Steps for a Fresh Pi

### First-Time Setup (Run Once)
```bash
# 1. Clone the repo onto the Pi
git clone <repo-url> simulato
cd simulato

# 2. Install HIDPi (one-time, as root)
sudo python3 HIDPi/HIDPi_Setup.py
# → It will modify /boot/firmware/config.txt and ask you to reboot

# 3. Reboot
sudo reboot

# 4. After reboot, HIDPi systemd service auto-configures the gadget
#    Verify devices exist:
ls -la /dev/hidg*
# You should see /dev/hidg0 (keyboard) and /dev/hidg1 (mouse)
```

### Install the HIDPi Python Library
```bash
cd simulato/HIDPi/library
pip install .
```

### Start the Simulato Listener
```bash
cd simulato
python3 -m raspberry_pi.command_listener
```

---

## Files to Modify

| File | Action | Details |
|------|--------|---------|
| `raspberry_pi/device_config.py` | **MODIFY** | Swap `hidg0` ↔ `hidg1` |
| `raspberry_pi/hid_controller.py` | **MODIFY** | Fix report format to 6 bytes, OR replace with HIDPi imports |
| `start_pi.sh` | **MODIFY** | Use `HIDPi_Setup.py` instead of `setup_pi_hid.sh` |
| `scripts/setup_pi_hid.sh` | **DELETE** | Replaced by HIDPi |
| `docs/DEPLOYMENT_CHECKLIST.md` | **MODIFY** | Update Pi setup steps |
| `README.md` | **MODIFY** | Update Pi setup section |

---

## Recommendation

**Use Option A (import HIDPi directly).** This gives us:
- Guaranteed report format compatibility
- Access to keyboard emulation for future features
- `move_percent()` for resolution-independent clicking
- Maintained by the HIDPi community (bug fixes, OS updates)
- Clean uninstall via `HIDPi_Setup.py uninstall`
