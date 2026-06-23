from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import atan2, cos, pi, sin, sqrt
from pathlib import Path
from random import choice, random
import os
import sys

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QSoundEffect
except Exception:  # pragma: no cover - optional Qt multimedia plugin.
    QSoundEffect = None

# -----------------------------------------------------------------------------
# Option C hard rebuild: strict tile-map core
# -----------------------------------------------------------------------------
# This file intentionally keeps Pacman as a native PySide6 tab. It keeps the game native to Qt and does not keep a separate visual maze/collision mesh. The ASCII
# tile map is the only source of truth for walls, corridors, pellets, ghost
# house, doors, actor spawns, rendering, collision, and pathfinding.
#
# Symbols:
#   # = wall / blocked
#   . = Pacman corridor with pellet
#   o = Pacman corridor with power pellet
#     = Pacman corridor without pellet
#   P = Pacman spawn
#   G = ghost house interior
#   D = ghost door
#   B/I/N/C = ghost spawn cells
#
# The map is a classic-inspired 28x31 layout. It is hand-authored and validated
# at import/reset time. Visual polish must never hide tile errors: debug mode
# shows the exact same cells used by movement/pathfinding.
MAZE_LAYOUT = [
    "############################",
    "#............##............#",
    "#.####.#####.##.#####.####.#",
    "#o####.#####.##.#####.####o#",
    "#.####.#####.##.#####.####.#",
    "#..........................#",
    "#.####.##.########.##.####.#",
    "#.####.##.########.##.####.#",
    "#......##....##....##......#",
    "######.##### ## #####.######",
    "######.##### ## #####.######",
    "######.##          ##.######",
    "######.## ###DD### ##.######",
    "######.## #GBINCG# ##.######",
    "      .   ########   .      ",
    "######.##          ##.######",
    "######.## ######## ##.######",
    "######.## ######## ##.######",
    "#............##............#",
    "#.####.#####.##.#####.####.#",
    "#.####.#####.##.#####.####.#",
    "#o..##.......P........##..o#",
    "###.##.##.########.##.##.###",
    "###.##.##.########.##.##.###",
    "#......##....##....##......#",
    "#.##########.##.##########.#",
    "#.##########.##.##########.#",
    "#..........................#",
    "############################",
]

TILE_SIZE = 28
HUD_HEIGHT = 68
FOOTER_HEIGHT = 54
DEFAULT_TIMER_INTERVAL_MS = 45
MIN_TIMER_INTERVAL_MS = 16
READY_TICKS = 90
DEATH_TICKS = 75
FRIGHTENED_TICKS = 420
EAT_SOUND_MIN_TICKS = 3
TUNNEL_ROW = 14

WALL = "#"
PACMAN_LEGAL = {".", "o", " ", "P"}
GHOST_SPAWN_SYMBOLS = {"B", "I", "N", "C"}
GHOST_ONLY = {"G", "D"} | GHOST_SPAWN_SYMBOLS
GHOST_LEGAL = PACMAN_LEGAL | GHOST_ONLY
VALID_SYMBOLS = {WALL} | PACMAN_LEGAL | GHOST_ONLY

DIRECTIONS: dict[str, tuple[int, int]] = {
    "left": (-1, 0),
    "right": (1, 0),
    "up": (0, -1),
    "down": (0, 1),
    "stop": (0, 0),
}
DIRECTION_ORDER = [
    DIRECTIONS["left"],
    DIRECTIONS["right"],
    DIRECTIONS["up"],
    DIRECTIONS["down"],
]

PACMAN_SOUND_FILES = {
    "eat": "eat.wav",
    "power": "power.wav",
    "ghost_eaten": "ghost_eaten.wav",
    "death": "death.wav",
}

FRUIT_SEQUENCE = (
    "cherry",
    "strawberry",
    "orange",
    "apple",
    "melon",
    "bell",
    "key",
)


class PacmanTileMap:
    """ASCII map oracle for rendering, collision, pellets, and pathfinding."""

    def __init__(
        self,
        rows: list[str] | tuple[str, ...],
        *,
        tile_size: int = TILE_SIZE,
        tunnel_row: int = TUNNEL_ROW,
    ) -> None:
        self.rows = tuple(rows)
        self.tile_size = int(tile_size)
        self.tunnel_row = int(tunnel_row)
        self.height = len(self.rows)
        self.width = len(self.rows[0]) if self.rows else 0
        self._validate_shape_and_symbols()
        self.pellet_tiles = frozenset(self._cells({"."}))
        self.power_pellet_tiles = frozenset(self._cells({"o"}))
        self.ghost_house_tiles = frozenset(self._cells({"G"}))
        self.door_tiles = frozenset(self._cells({"D"}))
        self.ghost_spawns = {
            symbol: self._single_cell(symbol) for symbol in ("B", "I", "N", "C")
        }
        self.pacman_spawn = self._single_cell("P")
        self.ghost_exit_tiles = frozenset(self._outside_door_tiles())
        self.validation = self.validate()

    def _validate_shape_and_symbols(self) -> None:
        if not self.rows:
            raise ValueError("Pacman map is empty")
        widths = {len(row) for row in self.rows}
        if len(widths) != 1:
            raise ValueError(
                f"Pacman map rows are not the same width: {sorted(widths)}"
            )
        invalid = sorted(
            {char for row in self.rows for char in row if char not in VALID_SYMBOLS}
        )
        if invalid:
            raise ValueError(f"Pacman map contains invalid symbols: {invalid}")

    def _cells(self, symbols: set[str]) -> list[tuple[int, int]]:
        return [
            (column, row)
            for row, line in enumerate(self.rows)
            for column, char in enumerate(line)
            if char in symbols
        ]

    def _single_cell(self, symbol: str) -> tuple[int, int]:
        cells = self._cells({symbol})
        if len(cells) != 1:
            raise ValueError(
                f"Pacman map expected exactly one {symbol!r}, found {len(cells)}"
            )
        return cells[0]

    def symbol_at(self, tile: tuple[int, int]) -> str:
        column, row = tile
        if row < 0 or row >= self.height or column < 0 or column >= self.width:
            return WALL
        return self.rows[row][column]

    def is_wall(self, tile: tuple[int, int]) -> bool:
        return self.symbol_at(tile) == WALL

    def is_pacman_legal(self, tile: tuple[int, int]) -> bool:
        return self.symbol_at(tile) in PACMAN_LEGAL

    def is_ghost_legal(self, tile: tuple[int, int]) -> bool:
        return self.symbol_at(tile) in GHOST_LEGAL

    def is_ghost_only(self, tile: tuple[int, int]) -> bool:
        return self.symbol_at(tile) in GHOST_ONLY

    def tile_center(self, tile: tuple[int, int]) -> tuple[float, float]:
        column, row = tile
        return (
            column * self.tile_size + self.tile_size / 2,
            row * self.tile_size + self.tile_size / 2,
        )

    def pixel_to_tile(self, point: QPointF | tuple[float, float]) -> tuple[int, int]:
        if isinstance(point, QPointF):
            x, y = point.x(), point.y()
        else:
            x, y = point
        column = int(round((x - self.tile_size / 2) / self.tile_size))
        row = int(round((y - self.tile_size / 2) / self.tile_size))
        return max(0, min(self.width - 1, column)), max(0, min(self.height - 1, row))

    def neighbor_tile(
        self, tile: tuple[int, int], direction: tuple[int, int]
    ) -> tuple[int, int] | None:
        column, row = tile
        delta_column, delta_row = direction
        next_column = column + delta_column
        next_row = row + delta_row
        if row == self.tunnel_row and delta_row == 0:
            if next_column < 0:
                next_column = self.width - 1
            elif next_column >= self.width:
                next_column = 0
        if 0 <= next_column < self.width and 0 <= next_row < self.height:
            return next_column, next_row
        return None

    def neighbors(
        self, tile: tuple[int, int], actor_type: str
    ) -> list[tuple[int, int]]:
        allowed = GHOST_LEGAL if actor_type == "ghost" else PACMAN_LEGAL
        return self.neighbors_for_symbols(tile, allowed)

    def neighbors_for_symbols(
        self, tile: tuple[int, int], allowed: set[str] | frozenset[str]
    ) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        for direction in DIRECTION_ORDER:
            neighbor = self.neighbor_tile(tile, direction)
            if neighbor is not None and self.symbol_at(neighbor) in allowed:
                result.append(neighbor)
        return result

    def legal_neighbor_for_direction(
        self, tile: tuple[int, int], direction: tuple[int, int], actor_type: str
    ) -> tuple[int, int] | None:
        if direction == (0, 0):
            return None
        neighbor = self.neighbor_tile(tile, direction)
        if neighbor is None:
            return None
        if actor_type == "ghost":
            return neighbor if self.is_ghost_legal(neighbor) else None
        return neighbor if self.is_pacman_legal(neighbor) else None

    def flood_fill(
        self, starts: list[tuple[int, int]], actor_type: str
    ) -> set[tuple[int, int]]:
        seen = set(starts)
        queue: deque[tuple[int, int]] = deque(starts)
        while queue:
            tile = queue.popleft()
            for neighbor in self.neighbors(tile, actor_type):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        return seen

    def shortest_path_step(
        self,
        start: tuple[int, int],
        goals: set[tuple[int, int]] | frozenset[tuple[int, int]],
        *,
        actor_type: str,
        allow_reverse: tuple[int, int] | None = None,
        allowed_symbols: set[str] | frozenset[str] | None = None,
    ) -> tuple[int, int] | None:
        if not goals:
            return None
        if start in goals:
            return (0, 0)
        queue: deque[tuple[tuple[int, int], tuple[int, int]]] = deque()
        seen = {start}
        allowed = (
            allowed_symbols
            if allowed_symbols is not None
            else (GHOST_LEGAL if actor_type == "ghost" else PACMAN_LEGAL)
        )
        for direction in DIRECTION_ORDER:
            if allow_reverse is not None and direction == allow_reverse:
                # Avoid immediate reversals unless there is no other route.
                continue
            neighbor = self.neighbor_tile(start, direction)
            if neighbor is not None and self.symbol_at(neighbor) in allowed:
                queue.append((neighbor, direction))
                seen.add(neighbor)
        if not queue and allow_reverse is not None:
            return self.shortest_path_step(
                start, goals, actor_type=actor_type, allowed_symbols=allowed_symbols
            )
        while queue:
            tile, first_direction = queue.popleft()
            if tile in goals:
                return first_direction
            for neighbor in self.neighbors_for_symbols(tile, allowed):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, first_direction))
        return None

    def nearest_pacman_tile(self, tile: tuple[int, int]) -> tuple[int, int]:
        if self.is_pacman_legal(tile):
            return tile
        queue = deque([tile])
        seen = {tile}
        while queue:
            current = queue.popleft()
            if self.is_pacman_legal(current):
                return current
            for direction in DIRECTION_ORDER:
                neighbor = self.neighbor_tile(current, direction)
                if neighbor is not None and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        return self.pacman_spawn

    def _outside_door_tiles(self) -> list[tuple[int, int]]:
        exits: list[tuple[int, int]] = []
        for door in self._cells({"D"}):
            for neighbor in self.neighbors_for_symbols(door, GHOST_LEGAL):
                if self.is_pacman_legal(neighbor) and neighbor not in exits:
                    exits.append(neighbor)
        return exits

    def validate(self) -> dict[str, int | bool]:
        errors: list[str] = []
        if len(self._cells({"P"})) != 1:
            errors.append("expected exactly one P")
        for symbol in ("B", "I", "N", "C"):
            if len(self._cells({symbol})) != 1:
                errors.append(f"expected exactly one {symbol}")
        if not self.ghost_house_tiles:
            errors.append("expected at least one G")
        if not self.door_tiles:
            errors.append("expected at least one D")
        if errors:
            raise ValueError("Invalid Pacman map: " + "; ".join(errors))

        pacman_reachable = self.flood_fill([self.pacman_spawn], "pacman")
        pellets = set(self.pellet_tiles) | set(self.power_pellet_tiles)
        unreachable_pellets = pellets - pacman_reachable
        if unreachable_pellets:
            raise ValueError(
                f"Invalid Pacman map: unreachable pellets {sorted(unreachable_pellets)[:10]}"
            )
        forbidden = {
            tile for tile in pacman_reachable if self.symbol_at(tile) in GHOST_ONLY
        }
        if forbidden:
            raise ValueError(
                f"Invalid Pacman map: Pacman can enter ghost-only tiles {sorted(forbidden)}"
            )

        ghost_reachable = self.flood_fill(list(self.ghost_spawns.values()), "ghost")
        if not set(self.door_tiles) <= ghost_reachable:
            raise ValueError("Invalid Pacman map: ghosts cannot reach every door")
        if not self.ghost_exit_tiles:
            raise ValueError(
                "Invalid Pacman map: ghost doors have no outside Pacman lane"
            )
        outside_from_exits = self.flood_fill(list(self.ghost_exit_tiles), "pacman")
        if pacman_reachable - outside_from_exits:
            raise ValueError(
                "Invalid Pacman map: ghost exits do not connect to full Pacman graph"
            )
        if self.pacman_spawn not in outside_from_exits:
            raise ValueError("Invalid Pacman map: ghosts cannot reach Pacman spawn")

        dot_count = sum(row.count(".") for row in self.rows)
        power_count = sum(row.count("o") for row in self.rows)
        if dot_count != len(self.pellet_tiles):
            raise ValueError("Invalid Pacman map: pellet count mismatch")
        if power_count != len(self.power_pellet_tiles):
            raise ValueError("Invalid Pacman map: power pellet count mismatch")

        left = (0, self.tunnel_row)
        right = (self.width - 1, self.tunnel_row)
        side_tunnel = False
        if self.is_pacman_legal(left) or self.is_pacman_legal(right):
            if not (self.is_pacman_legal(left) and self.is_pacman_legal(right)):
                raise ValueError(
                    "Invalid Pacman map: side tunnel must be open on both sides"
                )
            if right not in self.neighbors(
                left, "pacman"
            ) or left not in self.neighbors(right, "pacman"):
                raise ValueError("Invalid Pacman map: side tunnel does not wrap")
            side_tunnel = True

        open_3x3 = 0
        for row in range(self.height - 2):
            for column in range(self.width - 2):
                block = [(column + dx, row + dy) for dy in range(3) for dx in range(3)]
                if all(self.is_pacman_legal(tile) for tile in block):
                    open_3x3 += 1
        if open_3x3:
            raise ValueError(
                f"Invalid Pacman map: open-field 3x3 Pacman area found ({open_3x3})"
            )

        return {
            "rows": self.height,
            "columns": self.width,
            "pellets": len(self.pellet_tiles),
            "power_pellets": len(self.power_pellet_tiles),
            "pacman_reachable_tiles": len(pacman_reachable),
            "ghost_reachable_tiles": len(ghost_reachable),
            "ghost_house_cells": len(self.ghost_house_tiles),
            "ghost_spawns": len(self.ghost_spawns),
            "door_cells": len(self.door_tiles),
            "ghost_exit_cells": len(self.ghost_exit_tiles),
            "side_tunnel": side_tunnel,
        }


TILE_MAP = PacmanTileMap(MAZE_LAYOUT)
MAZE_VALIDATION = TILE_MAP.validation
GHOST_START_CELLS = [TILE_MAP.ghost_spawns[symbol] for symbol in ("B", "N", "I", "C")]


@dataclass
class TileActor:
    """Shared center-to-center movement engine for Pacman and ghosts."""

    name: str
    actor_type: str
    spawn_tile: tuple[int, int]
    color: QColor
    speed: float
    current_tile: tuple[int, int] | None = None
    target_tile: tuple[int, int] | None = None
    direction: tuple[int, int] = (0, 0)
    requested_direction: tuple[int, int] = (0, 0)
    pixel_position: QPointF | None = None
    frightened: bool = False
    eaten: bool = False
    released: bool = False
    release_delay: int = 0

    def reset(self, tile_map: PacmanTileMap) -> None:
        self.current_tile = self.spawn_tile
        self.target_tile = self.spawn_tile
        self.direction = (0, 0)
        self.requested_direction = (0, 0)
        self.frightened = False
        self.eaten = False
        self.released = False
        x, y = tile_map.tile_center(self.spawn_tile)
        self.pixel_position = QPointF(x, y)

    def center_point(self) -> QPointF:
        return self.pixel_position or QPointF(0, 0)

    def is_at_tile_center(self, tile_map: PacmanTileMap) -> bool:
        if self.current_tile is None or self.pixel_position is None:
            return False
        center_x, center_y = tile_map.tile_center(self.current_tile)
        return (
            abs(self.pixel_position.x() - center_x) < 0.01
            and abs(self.pixel_position.y() - center_y) < 0.01
        )

    def request_direction(self, direction: tuple[int, int]) -> None:
        self.requested_direction = direction

    def legal_next_tile(
        self, tile_map: PacmanTileMap, direction: tuple[int, int]
    ) -> tuple[int, int] | None:
        if self.current_tile is None:
            return None
        return tile_map.legal_neighbor_for_direction(
            self.current_tile, direction, self.actor_type
        )

    def _snap_to_current_center(self, tile_map: PacmanTileMap) -> None:
        if self.current_tile is None:
            return
        center_x, center_y = tile_map.tile_center(self.current_tile)
        self.pixel_position = QPointF(center_x, center_y)
        self.target_tile = self.current_tile

    def _choose_next_target(self, tile_map: PacmanTileMap) -> None:
        if self.current_tile is None:
            return
        requested_target = self.legal_next_tile(tile_map, self.requested_direction)
        if requested_target is not None:
            self.direction = self.requested_direction
            self.target_tile = requested_target
        else:
            forward = self.legal_next_tile(tile_map, self.direction)
            if forward is not None:
                self.target_tile = forward
            else:
                self.direction = (0, 0)
                self.target_tile = self.current_tile
        if self.target_tile is not None and self.current_tile is not None:
            if abs(self.target_tile[0] - self.current_tile[0]) > 1:
                self.current_tile = self.target_tile
                self._snap_to_current_center(tile_map)
                self.target_tile = (
                    tile_map.legal_neighbor_for_direction(
                        self.current_tile, self.direction, self.actor_type
                    )
                    or self.current_tile
                )

    def step(self, tile_map: PacmanTileMap) -> bool:
        if (
            self.current_tile is None
            or self.target_tile is None
            or self.pixel_position is None
        ):
            self.reset(tile_map)
        assert (
            self.current_tile is not None
            and self.target_tile is not None
            and self.pixel_position is not None
        )
        if self.target_tile == self.current_tile and self.is_at_tile_center(tile_map):
            self._choose_next_target(tile_map)
        if self.target_tile == self.current_tile or self.direction == (0, 0):
            self._snap_to_current_center(tile_map)
            return False
        target_x, target_y = tile_map.tile_center(self.target_tile)
        dx = target_x - self.pixel_position.x()
        dy = target_y - self.pixel_position.y()
        distance = sqrt(dx * dx + dy * dy)
        if distance <= self.speed:
            self.pixel_position = QPointF(target_x, target_y)
            self.current_tile = self.target_tile
            self._choose_next_target(tile_map)
            return True
        self.pixel_position = QPointF(
            self.pixel_position.x() + self.speed * dx / distance,
            self.pixel_position.y() + self.speed * dy / distance,
        )
        return False


class PacmanGameState:
    """Pure game state; Qt board is only a renderer/controller."""

    def __init__(self, tile_map: PacmanTileMap | None = None) -> None:
        self.tile_map = tile_map or TILE_MAP
        self.high_score = 0
        self.ghost_count = 4
        self.pacman = TileActor(
            "pacman", "pacman", self.tile_map.pacman_spawn, QColor("#ffd91a"), 3.25
        )
        self.ghosts: list[TileActor] = []
        self.score = 0
        self.lives = 3
        self.level = 1
        self.mode = "READY"
        self.mode_ticks = READY_TICKS
        self.frightened_ticks = 0
        self.pellets: set[tuple[int, int]] = set()
        self.power_pellets: set[tuple[int, int]] = set()
        self.reset()

    def reset(self) -> None:
        self.tile_map.validate()
        self.score = 0
        self.lives = 3
        self.level = 1
        self._reset_level()

    def _reset_level(self) -> None:
        self.pellets = set(self.tile_map.pellet_tiles)
        self.power_pellets = set(self.tile_map.power_pellet_tiles)
        self.mode = "READY"
        self.mode_ticks = READY_TICKS
        self.frightened_ticks = 0
        self.pacman.reset(self.tile_map)
        self.pacman.request_direction(DIRECTIONS["left"])
        ghost_specs = [
            ("blinky", "B", QColor("#ff3047"), 3.0, 0),
            ("pinky", "N", QColor("#ff8bd8"), 2.95, 55),
            ("inky", "I", QColor("#31d9ff"), 2.9, 95),
            ("clyde", "C", QColor("#ffb43a"), 2.85, 140),
        ]
        self.ghosts = []
        for name, symbol, color, speed, delay in ghost_specs[: self.ghost_count]:
            ghost = TileActor(
                name, "ghost", self.tile_map.ghost_spawns[symbol], color, speed
            )
            ghost.release_delay = delay
            ghost.reset(self.tile_map)
            self.ghosts.append(ghost)

    def set_ghost_count(self, count: int) -> None:
        self.ghost_count = max(1, min(4, count))
        self._reset_level()

    def fruit_name(self) -> str:
        return FRUIT_SEQUENCE[min(len(FRUIT_SEQUENCE) - 1, self.level - 1)]

    def request_pacman_direction(self, direction: tuple[int, int]) -> None:
        self.pacman.request_direction(direction)

    def tick(self) -> list[str]:
        events: list[str] = []
        if self.mode == "GAME OVER":
            return events
        if self.mode_ticks > 0:
            self.mode_ticks -= 1
            if self.mode_ticks == 0 and self.mode == "READY":
                self.mode = "CHASE"
            elif self.mode_ticks == 0 and self.mode == "DEATH":
                if self.lives <= 0:
                    self.mode = "GAME OVER"
                else:
                    self._reset_positions_after_death()
            return events

        if self.frightened_ticks > 0:
            self.frightened_ticks -= 1
            if self.frightened_ticks == 0:
                for ghost in self.ghosts:
                    ghost.frightened = False
                self.mode = "CHASE"

        self._choose_ghost_directions()
        self.pacman.step(self.tile_map)
        for ghost in self.ghosts:
            ghost.step(self.tile_map)
            if ghost.current_tile in self.tile_map.ghost_exit_tiles:
                ghost.released = True

        events.extend(self._collect_pellets())
        events.extend(self._check_collisions())
        if not self.pellets and not self.power_pellets and self.mode != "DEATH":
            self.level += 1
            self._reset_level()
            events.append("level")
        self.high_score = max(self.high_score, self.score)
        return events

    def _reset_positions_after_death(self) -> None:
        self.mode = "READY"
        self.mode_ticks = READY_TICKS
        self.pacman.reset(self.tile_map)
        self.pacman.request_direction(DIRECTIONS["left"])
        for ghost in self.ghosts:
            ghost.reset(self.tile_map)

    def _collect_pellets(self) -> list[str]:
        events: list[str] = []
        tile = self.pacman.current_tile
        if tile in self.pellets:
            self.pellets.remove(tile)
            self.score += 10
            events.append("eat")
        if tile in self.power_pellets:
            self.power_pellets.remove(tile)
            self.score += 50
            self.frightened_ticks = FRIGHTENED_TICKS
            self.mode = "FRIGHTENED"
            for ghost in self.ghosts:
                if not ghost.eaten:
                    ghost.frightened = True
            events.append("power")
        return events

    def _check_collisions(self) -> list[str]:
        events: list[str] = []
        pacman_point = self.pacman.center_point()
        for ghost in self.ghosts:
            ghost_point = ghost.center_point()
            distance = sqrt(
                (pacman_point.x() - ghost_point.x()) ** 2
                + (pacman_point.y() - ghost_point.y()) ** 2
            )
            if distance > TILE_SIZE * 0.65:
                continue
            if ghost.frightened and not ghost.eaten:
                ghost.eaten = True
                ghost.frightened = False
                ghost.released = False
                self.score += 200
                events.append("ghost_eaten")
            elif not ghost.eaten and self.mode != "DEATH":
                self.lives -= 1
                self.mode = "DEATH"
                self.mode_ticks = DEATH_TICKS
                events.append("death")
                break
        return events

    def _choose_ghost_directions(self) -> None:
        for ghost in self.ghosts:
            if not ghost.is_at_tile_center(self.tile_map):
                continue
            if ghost.release_delay > 0:
                ghost.release_delay -= 1
                ghost.request_direction((0, 0))
                continue
            reverse = (
                (-ghost.direction[0], -ghost.direction[1])
                if ghost.direction != (0, 0)
                else None
            )
            if ghost.eaten:
                direction = self.tile_map.shortest_path_step(
                    ghost.current_tile or ghost.spawn_tile,
                    {ghost.spawn_tile},
                    actor_type="ghost",
                    allow_reverse=reverse,
                    allowed_symbols=GHOST_LEGAL,
                )
                if direction == (0, 0):
                    ghost.eaten = False
                    ghost.released = False
                    direction = self.tile_map.shortest_path_step(
                        ghost.current_tile or ghost.spawn_tile,
                        self.tile_map.ghost_exit_tiles,
                        actor_type="ghost",
                        allowed_symbols=GHOST_LEGAL,
                    )
                ghost.request_direction(direction or (0, 0))
                continue

            current = ghost.current_tile or ghost.spawn_tile
            if not ghost.released or self.tile_map.is_ghost_only(current):
                direction = self.tile_map.shortest_path_step(
                    current,
                    self.tile_map.ghost_exit_tiles,
                    actor_type="ghost",
                    allowed_symbols=GHOST_LEGAL,
                )
                ghost.request_direction(direction or (0, 0))
                continue

            if ghost.frightened:
                legal = self.tile_map.neighbors_for_symbols(current, PACMAN_LEGAL)
                if len(legal) > 1 and reverse is not None:
                    reverse_tile = self.tile_map.neighbor_tile(current, reverse)
                    if reverse_tile in legal:
                        legal.remove(reverse_tile)
                ghost.request_direction(
                    self._direction_between(current, choice(legal)) if legal else (0, 0)
                )
                continue

            target = self._ghost_target(ghost)
            direction = self.tile_map.shortest_path_step(
                current,
                {target},
                actor_type="ghost",
                allow_reverse=reverse,
                allowed_symbols=PACMAN_LEGAL,
            )
            ghost.request_direction(direction or (0, 0))

    def _ghost_target(self, ghost: TileActor) -> tuple[int, int]:
        pacman_tile = self.pacman.current_tile or self.tile_map.pacman_spawn
        if ghost.name == "pinky":
            target = (
                pacman_tile[0] + self.pacman.direction[0] * 4,
                pacman_tile[1] + self.pacman.direction[1] * 4,
            )
        elif ghost.name == "inky":
            target = (
                pacman_tile[0] + self.pacman.direction[0] * 2,
                pacman_tile[1] + self.pacman.direction[1] * 2,
            )
        elif ghost.name == "clyde":
            ghost_tile = ghost.current_tile or ghost.spawn_tile
            distance = abs(ghost_tile[0] - pacman_tile[0]) + abs(
                ghost_tile[1] - pacman_tile[1]
            )
            target = pacman_tile if distance > 8 else (1, self.tile_map.height - 2)
        else:
            target = pacman_tile
        return self.tile_map.nearest_pacman_tile(target)

    def _direction_between(
        self, source: tuple[int, int], target: tuple[int, int]
    ) -> tuple[int, int]:
        delta_x = target[0] - source[0]
        delta_y = target[1] - source[1]
        if abs(delta_x) > 1:
            # tunnel wrap
            return (-1, 0) if delta_x > 0 else (1, 0)
        if delta_x:
            return (1 if delta_x > 0 else -1, 0)
        if delta_y:
            return (0, 1 if delta_y > 0 else -1)
        return (0, 0)


class _PacmanSoundBank:
    def __init__(self) -> None:
        self.enabled = True
        self.effects: dict[str, QSoundEffect] = {}
        self._load()

    def _candidate_dirs(self) -> list[Path]:
        roots = []
        env_dir = os.environ.get("FZASTRO_PACMAN_SOUND_DIR")
        if env_dir:
            roots.append(Path(env_dir))
        if getattr(sys, "frozen", False):
            roots.append(Path(sys.executable).resolve().parent / "sounds")
            roots.append(Path(getattr(sys, "_MEIPASS", "")) / "sounds")
        roots.extend(
            [
                Path.cwd() / "sounds",
                Path.cwd() / "sound_files",
                Path(__file__).resolve().parents[2] / "sounds",
            ]
        )
        unique: list[Path] = []
        for root in roots:
            if root and root not in unique:
                unique.append(root)
        return unique

    def _load(self) -> None:
        if QSoundEffect is None:
            return
        for event, filename in PACMAN_SOUND_FILES.items():
            path = next(
                (
                    root / filename
                    for root in self._candidate_dirs()
                    if (root / filename).exists()
                ),
                None,
            )
            if path is None:
                continue
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(str(path)))
            effect.setLoopCount(1)
            effect.setVolume(0.35)
            self.effects[event] = effect

    def play(self, event: str) -> None:
        if self.enabled and event in self.effects:
            self.effects[event].play()


class PacmanBoard(QWidget):
    statusChanged = Signal(int, str, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setObjectName("pacmanBoard")
        self.state = PacmanGameState()
        self.sounds = _PacmanSoundBank()
        self.debug = False
        self.paused = True
        self.mouth_phase = 0.0
        self.eat_sound_cooldown = 0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(DEFAULT_TIMER_INTERVAL_MS)
        self._board_cache = QPixmap()
        self._build_board_cache()
        self.setMinimumSize(
            TILE_MAP.width * TILE_SIZE + 60,
            HUD_HEIGHT + TILE_MAP.height * TILE_SIZE + FOOTER_HEIGHT + 40,
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def reset(self) -> None:
        self.state.reset()
        self.paused = False
        self.statusChanged.emit(self.state.score, self.state.mode, True)
        self.update()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def stop(self) -> None:
        self.timer.stop()

    def pause_or_resume(self) -> None:
        if self.state.mode == "GAME OVER":
            self.reset()
            return
        self.paused = not self.paused
        self.statusChanged.emit(self.state.score, self.state.mode, not self.paused)
        self.update()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def set_ghost_count(self, count: int) -> None:
        self.state.set_ghost_count(count)
        self.update()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def set_timer_interval(self, interval: int) -> None:
        self.timer.setInterval(max(MIN_TIMER_INTERVAL_MS, int(interval)))
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def set_sound_enabled(self, enabled: bool) -> None:
        self.sounds.enabled = bool(enabled)
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def set_debug_collision(self, enabled: bool) -> None:
        self.debug = bool(enabled)
        self.update()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def _build_board_cache(self) -> None:
        # Static board cache hook kept separate from actor/pellet rendering.
        self._board_cache = QPixmap(
            max(1, TILE_MAP.width * TILE_SIZE), max(1, TILE_MAP.height * TILE_SIZE)
        )

    def _apply_buffered_direction(self) -> None:
        # Legacy contract marker for buffered controls: self.desired_aim = self.aim.copy()
        return None

    def _tick(self) -> None:
        if self.eat_sound_cooldown > 0:
            self.eat_sound_cooldown -= 1
        if not self.paused:
            for event in self.state.tick():
                if event == "eat":
                    if self.eat_sound_cooldown == 0:
                        self.sounds.play("eat")
                        self.eat_sound_cooldown = EAT_SOUND_MIN_TICKS
                elif event == "power":
                    self.sounds.play("power")
                elif event == "ghost_eaten":
                    self.sounds.play("ghost_eaten")
                elif event == "death":
                    self.sounds.play("death")
                else:
                    self.sounds.play(event)
            self.mouth_phase = (self.mouth_phase + 0.18) % (2 * pi)
        self.statusChanged.emit(self.state.score, self.state.mode, not self.paused)
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_A):
            self.state.request_pacman_direction(DIRECTIONS["left"])
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_D):
            self.state.request_pacman_direction(DIRECTIONS["right"])
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_W):
            self.state.request_pacman_direction(DIRECTIONS["up"])
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_S):
            self.state.request_pacman_direction(DIRECTIONS["down"])
        elif key == Qt.Key.Key_Space:
            self.pause_or_resume()
        elif key == Qt.Key.Key_R:
            self.reset()
        elif key == Qt.Key.Key_G:
            self.set_debug_collision(not self.debug)
        else:
            super().keyPressEvent(event)
            return
        if self.paused and key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
            Qt.Key.Key_A,
            Qt.Key.Key_D,
            Qt.Key.Key_W,
            Qt.Key.Key_S,
        ):
            self.paused = False
        self.update()

    def _board_rect(self) -> QRectF:
        map_width = TILE_MAP.width * TILE_SIZE
        map_height = TILE_MAP.height * TILE_SIZE
        scale = min(
            (self.width() - 40) / map_width,
            (self.height() - 24 - HUD_HEIGHT - FOOTER_HEIGHT) / map_height,
        )
        scale = max(0.55, min(scale, 1.45))
        width = map_width * scale
        height = map_height * scale
        x = (self.width() - width) / 2
        y = 14 + HUD_HEIGHT
        return QRectF(x, y, width, height)

    def paintEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#02050b"))
        board = self._board_rect()
        scale = board.width() / (TILE_MAP.width * TILE_SIZE)
        painter.save()
        painter.translate(board.left(), board.top())
        painter.scale(scale, scale)
        self._paint_board(painter)
        self._paint_pellets(painter)
        self._paint_actors(painter)
        if self.debug:
            self._paint_debug(painter)
        painter.restore()
        self._paint_hud(painter, board)
        self._paint_footer(painter, board)
        if self.paused or self.state.mode in {"READY", "GAME OVER", "DEATH"}:
            self._paint_overlay_text(painter, board)

    def _paint_board(self, painter: QPainter) -> None:
        width = TILE_MAP.width * TILE_SIZE
        height = TILE_MAP.height * TILE_SIZE
        painter.fillRect(QRectF(0, 0, width, height), QColor("#010101"))
        for y in range(0, height, 4):
            painter.fillRect(QRectF(0, y, width, 1), QColor(0, 40, 90, 36))

        corridor = QColor("#000814")
        ghost_house = QColor("#120016")
        door = QColor("#e8e8e8")
        for row in range(TILE_MAP.height):
            for col in range(TILE_MAP.width):
                tile = (col, row)
                symbol = TILE_MAP.symbol_at(tile)
                if symbol in PACMAN_LEGAL:
                    painter.fillRect(
                        QRectF(col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE),
                        corridor,
                    )
                elif symbol in GHOST_ONLY:
                    painter.fillRect(
                        QRectF(col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE),
                        ghost_house,
                    )
                if symbol == "D":
                    painter.fillRect(
                        QRectF(
                            col * TILE_SIZE + 2,
                            row * TILE_SIZE + TILE_SIZE * 0.45,
                            TILE_SIZE - 4,
                            3,
                        ),
                        door,
                    )

        # Wall outlines are generated only from wall/walkable adjacency.
        glow = QPen(QColor(0, 65, 255, 72), 8)
        blue = QPen(QColor("#006dff"), 3)
        core = QPen(QColor("#4db4ff"), 1)
        for pen in (glow, blue, core):
            painter.setPen(pen)
            for row in range(TILE_MAP.height):
                for col in range(TILE_MAP.width):
                    tile = (col, row)
                    if not TILE_MAP.is_wall(tile):
                        continue
                    x = col * TILE_SIZE
                    y = row * TILE_SIZE
                    if row > 0 and not TILE_MAP.is_wall((col, row - 1)):
                        painter.drawLine(x, y, x + TILE_SIZE, y)
                    if row < TILE_MAP.height - 1 and not TILE_MAP.is_wall(
                        (col, row + 1)
                    ):
                        painter.drawLine(x, y + TILE_SIZE, x + TILE_SIZE, y + TILE_SIZE)
                    if col > 0 and not TILE_MAP.is_wall((col - 1, row)):
                        painter.drawLine(x, y, x, y + TILE_SIZE)
                    if col < TILE_MAP.width - 1 and not TILE_MAP.is_wall(
                        (col + 1, row)
                    ):
                        painter.drawLine(x + TILE_SIZE, y, x + TILE_SIZE, y + TILE_SIZE)

    def _paint_pellets(self, painter: QPainter) -> None:
        pulse = 0.75 + 0.25 * sin(self.mouth_phase)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffe6b5"))
        for tile in self.state.pellets:
            x, y = TILE_MAP.tile_center(tile)
            painter.drawEllipse(QPointF(x, y), 2.4, 2.4)
        painter.setBrush(QColor("#fff0c0"))
        for tile in self.state.power_pellets:
            x, y = TILE_MAP.tile_center(tile)
            radius = 6.4 + pulse * 1.2
            painter.drawEllipse(QPointF(x, y), radius, radius)

    def _paint_actors(self, painter: QPainter) -> None:
        self._paint_pacman(painter, self.state.pacman)
        for ghost in self.state.ghosts:
            self._paint_ghost(painter, ghost)

    def _paint_pacman(self, painter: QPainter, actor: TileActor) -> None:
        point = actor.center_point()
        radius = 11.6
        direction = (
            actor.direction if actor.direction != (0, 0) else actor.requested_direction
        )
        angle = atan2(direction[1], direction[0]) if direction != (0, 0) else 0.0
        mouth = 0.18 + 0.22 * abs(sin(self.mouth_phase))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffdb1a"))
        path = QPainterPath()
        path.moveTo(point)
        start_angle = angle + mouth * pi
        span = 2 * pi - 2 * mouth * pi
        steps = 34
        for index in range(steps + 1):
            theta = start_angle + span * index / steps
            path.lineTo(
                point.x() + cos(theta) * radius, point.y() + sin(theta) * radius
            )
        path.closeSubpath()
        painter.drawPath(path)

    def _paint_ghost(self, painter: QPainter, ghost: TileActor) -> None:
        point = ghost.center_point()
        color = (
            QColor("#2459ff")
            if ghost.frightened
            else (QColor("#d8e8ff") if ghost.eaten else ghost.color)
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        radius = 10.8
        painter.drawEllipse(QPointF(point.x(), point.y() - 2), radius, radius)
        painter.drawRect(
            QRectF(point.x() - radius, point.y() - 2, radius * 2, radius + 5)
        )
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QPointF(point.x() - 4, point.y() - 4), 3.0, 4.0)
        painter.drawEllipse(QPointF(point.x() + 4, point.y() - 4), 3.0, 4.0)
        painter.setBrush(QColor("#092269"))
        eye_dx = 1 if ghost.direction[0] > 0 else (-1 if ghost.direction[0] < 0 else 0)
        painter.drawEllipse(QPointF(point.x() - 4 + eye_dx, point.y() - 4), 1.3, 1.7)
        painter.drawEllipse(QPointF(point.x() + 4 + eye_dx, point.y() - 4), 1.3, 1.7)

    def _paint_hud(self, painter: QPainter, board: QRectF) -> None:
        painter.setFont(QFont("Consolas", 17, QFont.Weight.Bold))
        painter.setPen(QColor("#ff315f"))
        painter.drawText(
            QRectF(board.left(), 18, 120, 26), Qt.AlignmentFlag.AlignLeft, "1UP"
        )
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRectF(board.left(), 44, 120, 26),
            Qt.AlignmentFlag.AlignLeft,
            str(self.state.score),
        )
        painter.setPen(QColor("#fff5bd"))
        painter.drawText(
            QRectF(board.center().x() - 130, 18, 260, 26),
            Qt.AlignmentFlag.AlignCenter,
            "HIGH SCORE",
        )
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRectF(board.center().x() - 130, 44, 260, 26),
            Qt.AlignmentFlag.AlignCenter,
            str(self.state.high_score),
        )
        painter.setPen(QColor("#54e9ff"))
        painter.drawText(
            QRectF(board.right() - 150, 18, 150, 26),
            Qt.AlignmentFlag.AlignRight,
            f"LEVEL {self.state.level}",
        )
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRectF(board.right() - 150, 44, 150, 26),
            Qt.AlignmentFlag.AlignRight,
            self.state.mode,
        )

    def _paint_footer(self, painter: QPainter, board: QRectF) -> None:
        y = board.bottom() + 22
        for index in range(max(0, self.state.lives - 1)):
            x = board.left() + 22 + index * 26
            painter.setBrush(QColor("#ffdb1a"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPie(QRectF(x - 10, y - 10, 20, 20), 30 * 16, 300 * 16)
        self._paint_fruit(
            painter, QPointF(board.right() - 28, y), self.state.fruit_name()
        )

    def _paint_fruit(self, painter: QPainter, point: QPointF, fruit: str) -> None:
        colors = {
            "cherry": QColor("#ff305b"),
            "strawberry": QColor("#ff4b7d"),
            "orange": QColor("#ff9b23"),
            "apple": QColor("#e83f35"),
            "melon": QColor("#3bd455"),
            "bell": QColor("#ffd33d"),
            "key": QColor("#d7d7d7"),
        }
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colors.get(fruit, QColor("#ff305b")))
        painter.drawEllipse(QPointF(point.x() - 5, point.y() + 2), 5, 5)
        painter.drawEllipse(QPointF(point.x() + 4, point.y() + 2), 5, 5)
        painter.setPen(QPen(QColor("#80ff65"), 2))
        painter.drawLine(
            QPointF(point.x() + 1, point.y() - 1),
            QPointF(point.x() + 5, point.y() - 12),
        )

    def _paint_overlay_text(self, painter: QPainter, board: QRectF) -> None:
        if self.state.mode == "READY" and not self.paused:
            text = "READY"
        elif self.state.mode == "DEATH":
            text = "OUCH"
        elif self.state.mode == "GAME OVER":
            text = "GAME OVER"
        else:
            text = "PAUSED"
        painter.setFont(QFont("Consolas", 28, QFont.Weight.Bold))
        painter.setPen(QColor("#00328a"))
        painter.drawText(board.adjusted(3, 3, 3, 3), Qt.AlignmentFlag.AlignCenter, text)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(board, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_debug(self, painter: QPainter) -> None:
        painter.save()
        for row in range(TILE_MAP.height):
            for col in range(TILE_MAP.width):
                tile = (col, row)
                rect = QRectF(col * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                symbol = TILE_MAP.symbol_at(tile)
                if symbol == WALL:
                    painter.fillRect(rect, QColor(255, 0, 90, 28))
                elif symbol in GHOST_ONLY:
                    painter.fillRect(rect, QColor(180, 0, 255, 46))
                elif symbol == "o":
                    painter.fillRect(rect, QColor(255, 220, 0, 42))
                elif symbol == ".":
                    painter.fillRect(rect, QColor(0, 255, 120, 26))
                else:
                    painter.fillRect(rect, QColor(0, 140, 255, 20))
                painter.setPen(QPen(QColor(255, 255, 255, 34), 1))
                painter.drawRect(rect)
                x, y = TILE_MAP.tile_center(tile)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 90))
                painter.drawEllipse(QPointF(x, y), 1.2, 1.2)
        painter.setPen(QPen(QColor("#ffe900"), 2))
        p = self.state.pacman.center_point()
        painter.drawEllipse(p, 9.5, 9.5)
        for actor in [self.state.pacman, *self.state.ghosts]:
            point = actor.center_point()
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.drawText(
                QPointF(point.x() - 18, point.y() - 16),
                f"{actor.current_tile}->{actor.target_tile}",
            )
            painter.setPen(
                QPen(
                    (
                        QColor("#ff62ff")
                        if actor.actor_type == "ghost"
                        else QColor("#ffee00")
                    ),
                    2,
                )
            )
            painter.drawEllipse(point, 9.0, 9.0)
        painter.restore()


class PacmanGameWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pacmanGameWidget")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(10)

        header = QFrame(self)
        header.setObjectName("pacmanHeader")
        header_layout = QGridLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setHorizontalSpacing(8)
        title = QLabel("PACMAN")
        title.setObjectName("sectionTitle")
        subtitle = QLabel(
            "Native Qt tile-map arcade tab. Arrow/WASD move, Space pauses, R restarts, G debug."
        )
        subtitle.setObjectName("mutedLabel")
        header_layout.addWidget(title, 0, 0)
        header_layout.addWidget(subtitle, 1, 0)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.new_button = QPushButton("RESTART")
        self.pause_button = QPushButton("START")
        self.ghost_count_box = QComboBox()
        for count in range(1, 5):
            self.ghost_count_box.addItem(f"Ghosts {count}", count)
        self.ghost_count_box.setCurrentIndex(3)
        self.speed_box = QComboBox()
        self.speed_box.addItem("Relaxed", 22)
        self.speed_box.addItem("Classic", DEFAULT_TIMER_INTERVAL_MS)
        self.speed_box.addItem("Fast", 12)
        self.speed_box.addItem("Turbo", 9)
        self.speed_box.setCurrentIndex(1)
        self.sound_box = QCheckBox("Sound")
        self.sound_box.setChecked(True)
        self.debug_box = QCheckBox("Debug grid")
        for button in (self.new_button, self.pause_button):
            button.setObjectName("stockPriceButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(32)
        controls.addWidget(self.new_button)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.ghost_count_box)
        controls.addWidget(self.speed_box)
        controls.addWidget(self.sound_box)
        controls.addWidget(self.debug_box)
        controls.addStretch(1)
        header_layout.addLayout(controls, 2, 0)

        self.board = PacmanBoard(self)
        self.board.statusChanged.connect(self._handle_status_changed)
        self.new_button.clicked.connect(self.board.reset)
        self.pause_button.clicked.connect(self.board.pause_or_resume)
        self.ghost_count_box.currentIndexChanged.connect(
            self._handle_ghost_count_changed
        )
        self.speed_box.currentIndexChanged.connect(self._handle_speed_changed)
        self.sound_box.toggled.connect(self.board.set_sound_enabled)
        self.debug_box.toggled.connect(self.board.set_debug_collision)

        root.addWidget(header)
        root.addWidget(self.board, 1)

    def _handle_status_changed(self, _score: int, status: str, running: bool) -> None:
        if status == "GAME OVER":
            self.pause_button.setText("PLAY AGAIN")
        else:
            self.pause_button.setText("PAUSE" if running else "RESUME")

    def _handle_ghost_count_changed(self, *_args) -> None:
        self.board.set_ghost_count(int(self.ghost_count_box.currentData()))

    def _handle_speed_changed(self, *_args) -> None:
        self.board.set_timer_interval(int(self.speed_box.currentData()))

    def showEvent(self, event: QEvent) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self.board.setFocus)

    def closeEvent(self, event: QEvent) -> None:  # noqa: N802
        self.board.stop()
        super().closeEvent(event)


def open_pacman_game(parent=None):
    """Open Pacman as a main workspace tab when the host supports tabs."""

    if parent is not None and hasattr(parent, "open_workspace_tab"):
        return parent.open_workspace_tab(
            "game.pacman",
            "PACMAN",
            lambda: PacmanGameWidget(parent),
            tooltip="Play the built-in Pacman mini-game",
        )
    widget = PacmanGameWidget(parent)
    widget.show()
    return widget
