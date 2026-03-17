"""
Simulato — Pi HID smoke test

Sends deterministic click commands to the Raspberry Pi listener so you can
verify USB HID mouse movement/clicks on a test PC before running the full system.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PiTarget:
    host: str
    port: int


def _send_pi_command(target: PiTarget, command: str, coords: tuple[int, int]) -> dict:
    msg = {"type": "PI_COMMAND", "payload": {"command": command, "coords": [int(coords[0]), int(coords[1])]}}
    raw = (json.dumps(msg) + "\n").encode("utf-8")

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    try:
        s.connect((target.host, target.port))
        s.sendall(raw)
        resp = s.recv(4096).decode("utf-8", errors="replace").strip()
        return json.loads(resp)
    finally:
        try:
            s.close()
        except Exception:
            pass


def _coords_from_normalized(nx: float, ny: float) -> tuple[int, int]:
    nx = max(0.0, min(1.0, float(nx)))
    ny = max(0.0, min(1.0, float(ny)))
    return (int(round(nx * 32767)), int(round(ny * 32767)))


def _pattern_coords(pattern: str, steps: int) -> Iterable[tuple[str, tuple[int, int]]]:
    # We label everything as CLICK_B so Pi uses click_at() consistently.
    cmd = "CLICK_B"

    if pattern == "center":
        yield (cmd, (16384, 16384))
        return

    if pattern == "corners":
        yield (cmd, (0, 0))
        yield (cmd, (32767, 0))
        yield (cmd, (32767, 32767))
        yield (cmd, (0, 32767))
        yield (cmd, (16384, 16384))
        return

    if pattern == "grid":
        s = max(2, int(steps))
        for gy in range(s):
            ny = gy / (s - 1)
            for gx in range(s):
                nx = gx / (s - 1)
                yield (cmd, _coords_from_normalized(nx, ny))
        return

    raise ValueError(f"Unknown pattern: {pattern}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="pi_smoke_test", description="Send deterministic click tests to Pi listener.")
    ap.add_argument("--host", required=True, help="Pi IP address (WiFi IP)")
    ap.add_argument("--port", type=int, default=9000, help="Pi listener port (default: 9000)")
    ap.add_argument("--pattern", choices=["center", "corners", "grid"], default="center")
    ap.add_argument("--steps", type=int, default=5, help="Grid steps per axis (pattern=grid only)")
    ap.add_argument("--delay", type=float, default=0.35, help="Seconds to wait between clicks")
    args = ap.parse_args()

    target = PiTarget(host=args.host, port=args.port)

    print(f"[pi_smoke_test] target={target.host}:{target.port} pattern={args.pattern}")
    try:
        for i, (command, coords) in enumerate(_pattern_coords(args.pattern, args.steps), start=1):
            resp = _send_pi_command(target, command, coords)
            status = resp.get("payload", {}).get("status", "unknown")
            detail = resp.get("payload", {}).get("detail", "")
            print(f"  {i:03d} {command} coords={coords} -> {status} {detail}".rstrip())
            time.sleep(max(0.0, float(args.delay)))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print(f"[pi_smoke_test] ERROR: {e}", file=sys.stderr)
        return 2

    print("[pi_smoke_test] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

