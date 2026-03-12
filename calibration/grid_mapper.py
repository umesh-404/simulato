"""
Grid mapper.

Manages the screen coordinate grid used for mapping
logical positions (A, B, C, D, NEXT, SCROLL) to pixel coordinates.

The grid map is generated during calibration and saved to grid_map.json.
It is loaded at runtime for deterministic coordinate conversion.
"""

import json
from pathlib import Path
from typing import Optional

from controller.config import GRID_MAP_PATH, CONFIG_DIR
from controller.utils.logger import get_logger

logger = get_logger("grid_mapper")


class GridMap:
    """
    Maps logical screen positions to pixel coordinates.

    Grid structure:
        resolution: (width, height) of the screen
        grid_size: (cols, rows) — e.g. 20x20
        positions: dict of name -> (grid_col, grid_row)
    """

    def __init__(self) -> None:
        self.resolution: tuple[int, int] = (1920, 1080)
        self.grid_size: tuple[int, int] = (20, 20)
        self.positions: dict[str, tuple[int, int]] = {}

    @property
    def cell_width(self) -> float:
        return self.resolution[0] / self.grid_size[0]

    @property
    def cell_height(self) -> float:
        return self.resolution[1] / self.grid_size[1]

    def grid_to_pixel(self, grid_col: int, grid_row: int) -> tuple[int, int]:
        """Convert grid coordinates to pixel coordinates (center of cell)."""
        px = int((grid_col + 0.5) * self.cell_width)
        py = int((grid_row + 0.5) * self.cell_height)
        return (px, py)

    def get_pixel_for(self, position_name: str) -> Optional[tuple[int, int]]:
        """Get pixel coordinates for a named position (e.g. 'A', 'NEXT')."""
        grid_pos = self.positions.get(position_name)
        if grid_pos is None:
            return None
        return self.grid_to_pixel(grid_pos[0], grid_pos[1])

    def save(self, path: Optional[Path] = None) -> None:
        path = path or GRID_MAP_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "resolution": list(self.resolution),
            "grid_size": list(self.grid_size),
            "positions": {k: list(v) for k, v in self.positions.items()},
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Grid map saved to %s", path)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "GridMap":
        path = path or GRID_MAP_PATH
        if not path.exists():
            raise FileNotFoundError(f"Grid map not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        gm = cls()
        gm.resolution = tuple(data["resolution"])
        gm.grid_size = tuple(data["grid_size"])
        gm.positions = {k: tuple(v) for k, v in data["positions"].items()}
        logger.info(
            "Grid map loaded: %dx%d, %d positions",
            gm.resolution[0], gm.resolution[1], len(gm.positions),
        )
        return gm

    @classmethod
    def create_default(cls) -> "GridMap":
        """Create a default grid map with standard exam layout positions."""
        gm = cls()
        gm.resolution = (1920, 1080)
        gm.grid_size = (20, 20)
        gm.positions = {
            "A": (15, 8),
            "B": (15, 10),
            "C": (15, 12),
            "D": (15, 14),
            "NEXT": (18, 19),
            "SCROLL_LEFT": (0, 10),
            "SCROLL_RIGHT": (19, 10),
        }
        return gm
