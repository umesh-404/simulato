"""
Alarm sound player.

Plays an audible alert when the system encounters an anomaly
requiring operator intervention (Canonical Law 6, 12).

Uses platform-appropriate sound playback.
"""

import sys
import subprocess
from pathlib import Path
from typing import Optional

from controller.utils.logger import get_logger

logger = get_logger("sound_player")

_ALARM_SOUND_PATH: Optional[Path] = None


def set_alarm_sound(path: Path) -> None:
    """Set the path to the alarm sound file."""
    global _ALARM_SOUND_PATH
    _ALARM_SOUND_PATH = path
    logger.info("Alarm sound set: %s", path)


def play_alarm() -> None:
    """
    Play the alarm sound.
    Falls back to system beep if no sound file is configured.
    """
    if _ALARM_SOUND_PATH and _ALARM_SOUND_PATH.exists():
        _play_file(_ALARM_SOUND_PATH)
    else:
        _system_beep()


def _play_file(path: Path) -> None:
    try:
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        elif sys.platform == "darwin":
            subprocess.Popen(["afplay", str(path)])
        else:
            subprocess.Popen(["aplay", str(path)])
        logger.info("Playing alarm sound: %s", path)
    except Exception as e:
        logger.error("Failed to play sound file %s: %s", path, e)
        _system_beep()


def _system_beep() -> None:
    try:
        if sys.platform == "win32":
            import winsound
            for _ in range(3):
                winsound.Beep(1000, 500)
        else:
            for _ in range(3):
                print("\a", end="", flush=True)
        logger.info("System beep alarm triggered")
    except Exception as e:
        logger.error("System beep failed: %s", e)
