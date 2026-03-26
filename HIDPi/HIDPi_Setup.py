#!/bin/python3

import os
import shutil
import subprocess
import time
import sys

if os.geteuid() != 0:
    print("This script must be run as root.")
    sys.exit(1)

SERIAL_NUMBER = "1234567890"
MANUFACTURER = "Rikka"
PRODUCT = "HIDPi"

INSTALL_PATH = "/usr/local/bin/HIDPi.py"
PYTHON_LOCATION = "/usr/bin/python3"
SERVICE_NAME = "HIDPi"
SERVICE_PATH = f"/etc/systemd/system/{SERVICE_NAME}.service"

# manually change if this doesn't work for you for whatever reason
FIRMWARE_CONFIG_FILE = (
    "/boot/firmware/config.txt" if os.path.exists("/boot/firmware/config.txt")
    else "/boot/config.txt"
)

LINES_TO_ADD = [
    "dtoverlay=dwc2",
    "modules-load=dwc2,g_hid"
]

# internal use only
paths = []

def run_command(command):
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = process.communicate()
    if process.returncode != 0:
        print(f"Error: {err.strip()}")
    else:
        print(out.strip())

def run_commands(commands):
    for command in commands:
        run_command(command)


# --- INSTALL ---
def install_self():
    if os.path.abspath(__file__) != INSTALL_PATH:
        print("Copying script to " + INSTALL_PATH + "...")
        shutil.copy(__file__, INSTALL_PATH)
        os.chmod(INSTALL_PATH, 0o755)

    service_content = f"""[Unit]
Description=HIDPi Initialization
After=network.target multi-user.target
Wants=multi-user.target

[Service]
Type=oneshot
ExecStart={PYTHON_LOCATION} {INSTALL_PATH}
RemainAfterExit=yes
User=root

[Install]
WantedBy=multi-user.target
"""
    print("Creating systemd service...")
    with open(SERVICE_PATH, "w") as f:
        f.write(service_content)

    run_commands([
        "systemctl daemon-reload",
        f"systemctl enable {SERVICE_NAME}.service"
    ])
    print(f"{SERVICE_NAME} service installed. It will run on next boot")

def check_config():
    try:
        with open(FIRMWARE_CONFIG_FILE, 'r') as file:
            config_content = file.read()
            return all(line in config_content for line in LINES_TO_ADD)
    except FileNotFoundError:
        print(f"Firmware config file {FIRMWARE_CONFIG_FILE} not found!")
        return False

def modify_config_txt():
    if check_config():
        print("Config already modified")
    else:
        print("Modifying " + FIRMWARE_CONFIG_FILE + "...")
        with open(FIRMWARE_CONFIG_FILE, "a") as f:
            f.write("\n" + "\n".join(LINES_TO_ADD) + "\n")

        print("Config updated. Please reboot to apply changes. Once booted, the HIDPi service will finish the setup")
        sys.exit(0)

def wait_for_udc(timeout=10):
    udc_path = "/sys/class/udc"
    elapsed = 0
    while elapsed < timeout:
        try:
            devices = os.listdir(udc_path)
            if devices:
                print(f"Found UDC device: {devices[0]}")
                return devices[0]
        except Exception:
            pass
        time.sleep(1)
        elapsed += 1
    print("Timeout waiting for UDC device")
    return None

def create_device(path, protocol, subclass, report_length, report_desc_bytes):
    fullPath = os.path.join("/sys/kernel/config/usb_gadget/hid_gadget/functions", path)
    os.makedirs(fullPath, exist_ok=True)

    for name, value in [("protocol", protocol), ("subclass", subclass), ("report_length", report_length)]:
        with open(f"{fullPath}/{name}", "w") as f:
            f.write(str(value))

    with open(f"{fullPath}/report_desc", "wb") as f:
        f.write(report_desc_bytes)

    paths.append(fullPath)

def setup_hid_gadget():
    print("Setting up HID gadget...")
    run_commands([
        "modprobe dwc2",
        "modprobe libcomposite"
    ])

    # CREATE HID GADGET
    run_commands([
        "mkdir -p /sys/kernel/config/usb_gadget/hid_gadget",
        "mkdir -p /sys/kernel/config/usb_gadget/hid_gadget/strings/0x409",
        "mkdir -p /sys/kernel/config/usb_gadget/hid_gadget/configs/c.1/strings/0x409"
    ])

    for name, value in [
        ("idVendor", "0x1f00"),
        ("idProduct", "0x2012"),
        ("strings/0x409/serialnumber", SERIAL_NUMBER),
        ("strings/0x409/manufacturer", MANUFACTURER),
        ("strings/0x409/product", PRODUCT),
        ("configs/c.1/strings/0x409/configuration", "Default"),
        ("configs/c.1/MaxPower", "250")
    ]:
        with open(f"/sys/kernel/config/usb_gadget/hid_gadget/{name}", "w") as f:
            f.write(str(value))

    # KEYBOARD
    create_device("hid.usb0", 1, 1, 8, (
        b"\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01"
        b"\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x01\x95\x05\x75\x01"
        b"\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x01\x95\x06"
        b"\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0"
    ))

    # MOUSE (absolute coordinates + scroll wheel, Windows compatible)
    create_device("hid.usb1", 1, 1, 6, (
            b"\x05\x01\x09\x02\xa1\x01"              # Usage Page (Generic Desktop), Usage (Mouse), Collection (Application)
            b"\x09\x01\xa1\x00"                        # Usage (Pointer), Collection (Physical)
            b"\x05\x09\x19\x01\x29\x03"              # Usage Page (Buttons), Usage Min (1), Usage Max (3)
            b"\x15\x00\x25\x01"                        # Logical Min (0), Logical Max (1)
            b"\x95\x03\x75\x01\x81\x02"              # Report Count (3), Report Size (1 bit), Input (Data, Variable, Absolute) - 3 button bits
            b"\x95\x01\x75\x05\x81\x03"              # Report Count (1), Report Size (5 bits), Input (Constant) - 5 padding bits
            b"\x05\x01\x09\x30\x09\x31"              # Usage Page (Generic Desktop), Usage (X), Usage (Y)
            b"\x15\x00\x26\xff\x7f"                   # Logical Min (0), Logical Max (32767)
            b"\x75\x10\x95\x02\x81\x02"              # Report Size (16 bits), Report Count (2), Input (Data, Variable, Absolute) - X and Y
            b"\x09\x38"                                # Usage (Wheel)
            b"\x15\x81\x25\x7f"                        # Logical Min (-127), Logical Max (127)
            b"\x75\x08\x95\x01\x81\x06"              # Report Size (8 bits), Report Count (1), Input (Data, Variable, Relative) - Wheel
            b"\xc0\xc0"                                # End Collection, End Collection
    ))

    # LiNK FUNCTiONS TO GADGET CONFiG
    for p in paths:
        link_path = f"/sys/kernel/config/usb_gadget/hid_gadget/configs/c.1/{os.path.basename(p)}"
        if not os.path.exists(link_path):
            os.symlink(p, link_path)

    udc_device = wait_for_udc(timeout=15)
    if udc_device:
        with open("/sys/kernel/config/usb_gadget/hid_gadget/UDC", "w") as f:
            f.write(udc_device)
        print(f"Bound gadget to UDC: {udc_device}")
    else:
        print("Failed to bind gadget to UDC device")

def create_udev_rule():
    print("Creating udev rule for hidg...")
    udev_rule = "/etc/udev/rules.d/99-hidg.rules"
    with open(udev_rule, "w") as f:
        f.write('KERNEL=="hidg*", SUBSYSTEM=="hidg", MODE="0666", TAG+="uaccess"\n')

    run_command("udevadm control --reload-rules")
    run_command("chmod 666 /dev/hidg*")
    print("Udev rules reloaded")


# --- UNINSTALL ---
def remove_service():
    if os.path.exists(SERVICE_PATH):
        print("Removing systemd service...")
        run_commands([
            f"systemctl disable {SERVICE_NAME}.service",
            f"rm -f {SERVICE_PATH}"
        ])
        print("Service removed")

def remove_installed_script():
    if os.path.exists(INSTALL_PATH):
        os.remove(INSTALL_PATH)
        print("Removed installed script")

def remove_gadget():
    print("Removing HID gadget...")
    base = "/sys/kernel/config/usb_gadget/hid_gadget"

    def safe_unbind():
        udc_path = os.path.join(base, "UDC")
        if os.path.exists(udc_path):
            with open(udc_path, "w") as f:
                f.write("")
            print("Unbound gadget from UDC")

    def unlink_functions():
        config_path = os.path.join(base, "configs/c.1")
        if not os.path.exists(config_path):
            return
        for item in os.listdir(config_path):
            full_path = os.path.join(config_path, item)
            if os.path.islink(full_path):
                os.unlink(full_path)
                print(f"Unlinked function: {full_path}")

    def remove_functions():
        functions_path = os.path.join(base, "functions")
        if not os.path.exists(functions_path):
            return
        for func in os.listdir(functions_path):
            func_path = os.path.join(functions_path, func)
            for filename in os.listdir(func_path):
                file_path = os.path.join(func_path, filename)
                try:
                    os.remove(file_path)
                except PermissionError as e:
                    raise RuntimeError(f"Cannot remove {file_path}: {e}")
            os.rmdir(func_path)
            print(f"Removed function dir: {func_path}")

    def remove_dirs_in_order():
        ordered_paths = [
            "configs/c.1/strings/0x409",
            "configs/c.1",
            "strings/0x409",
            "webusb",
            "os_desc"
        ]
        for rel_path in ordered_paths:
            abs_path = os.path.join(base, rel_path)
            if os.path.exists(abs_path):
                for item in os.listdir(abs_path):
                    item_path = os.path.join(abs_path, item)
                    try:
                        os.remove(item_path)
                    except Exception as e:
                        raise RuntimeError(f"Failed to remove {item_path}: {e}")
                os.rmdir(abs_path)
                print(f"Removed directory: {abs_path}")

    def remove_root():
        if os.path.exists(base):
            leftover = os.listdir(base)
            if leftover:
                raise RuntimeError(f"Gadget dir not empty: {leftover}")
            os.rmdir(base)
            print(f"Removed gadget root: {base}")

    try:
        safe_unbind()
        unlink_functions()
        remove_functions()
        remove_dirs_in_order()
        remove_root()
    except Exception as e:
        print(f"ERROR: Gadget removal failed - {e}")
        raise

def remove_udev_rule():
    rule_path = "/etc/udev/rules.d/99-hidg.rules"
    if os.path.exists(rule_path):
        os.remove(rule_path)
        print("Udev rule removed")
    else:
        print("Udev rule not found; skipping")

    run_commands([
        "udevadm control --reload-rules",
        "udevadm trigger"
    ])
    print("Udev rules reloaded and trigger applied")



# --- MAIN ---
def install():
    install_self()
    modify_config_txt()
    setup_hid_gadget()
    create_udev_rule()
    print("HIDPi Initialized")

def uninstall():
    print("Uninstalling HIDPi...")
    remove_gadget()
    remove_udev_rule()
    remove_service()
    remove_installed_script()
    print(f"Uninstallation complete. You may need to modify {FIRMWARE_CONFIG_FILE} manually, as I'd rather not risk breaking your system")

if __name__ == "__main__":
    first_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if not first_arg:
        install() # also runs on boot
    elif first_arg in ("uninstall", "remove"):
        uninstall()
    elif first_arg in ("--help", "-h"):
        print("""Usage:
    sudo python3 HIDPi.py                       # install and activate
    sudo python3 HIDPi.py uninstall             # revert all* changes
      """)
    else:
        print(f"Unknown argument: {first_arg}")
        print("Run with --help or -h for usage")
