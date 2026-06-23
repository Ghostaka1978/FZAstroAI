from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fzastro_ai" / "ui" / "pacman_game.py"
PACMAN_TILES = {".", "o", " ", "P"}
GHOST_SPAWNS = {"B", "I", "N", "C"}
GHOST_ONLY = {"G", "D"} | GHOST_SPAWNS
GHOST_TILES = PACMAN_TILES | GHOST_ONLY
VALID = {"#"} | PACMAN_TILES | GHOST_ONLY
TUNNEL_ROW = 14


def _source_text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def _load_maze() -> list[str]:
    tree = ast.parse(_source_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "MAZE_LAYOUT"
                for target in node.targets
            ):
                return ast.literal_eval(node.value)
    raise AssertionError("MAZE_LAYOUT not found")


def _cells(maze: list[str], chars: set[str]) -> list[tuple[int, int]]:
    return [
        (column, row)
        for row, line in enumerate(maze)
        for column, char in enumerate(line)
        if char in chars
    ]


def _neighbors(
    maze: list[str], tile: tuple[int, int], allowed: set[str]
) -> list[tuple[int, int]]:
    width = len(maze[0])
    height = len(maze)
    column, row = tile
    out: list[tuple[int, int]] = []
    for delta_column, delta_row in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        next_column = column + delta_column
        next_row = row + delta_row
        if row == TUNNEL_ROW and delta_row == 0:
            if next_column < 0:
                next_column = width - 1
            elif next_column >= width:
                next_column = 0
        if (
            0 <= next_column < width
            and 0 <= next_row < height
            and maze[next_row][next_column] in allowed
        ):
            out.append((next_column, next_row))
    return out


def _flood(
    maze: list[str], starts: list[tuple[int, int]], allowed: set[str]
) -> set[tuple[int, int]]:
    seen = set(starts)
    queue = deque(starts)
    while queue:
        tile = queue.popleft()
        for neighbor in _neighbors(maze, tile, allowed):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def test_pacman_module_uses_native_tile_core():
    text = _source_text()
    assert "class PacmanTileMap" in text
    assert "class TileActor" in text
    assert "class PacmanGameState" in text
    assert "class PacmanBoard" in text
    assert "class PacmanGameWidget" in text
    assert "TILE_MAP = PacmanTileMap" in text
    assert "from turtle" not in text
    assert "from freegames" not in text
    assert "pygame" not in text.lower()


def test_tilemap_symbols_and_required_spawns_are_valid():
    maze = _load_maze()
    assert maze
    assert len({len(row) for row in maze}) == 1
    assert set("".join(maze)) <= VALID
    assert len(_cells(maze, {"P"})) == 1
    for symbol in GHOST_SPAWNS:
        assert len(_cells(maze, {symbol})) == 1
    assert _cells(maze, {"G"})
    assert _cells(maze, {"D"})


def test_layout_is_classic_sized_and_not_a_dotted_field():
    maze = _load_maze()
    assert len(maze[0]) == 28
    assert 28 <= len(maze) <= 31
    wall_count = sum(row.count("#") for row in maze)
    walkable_count = sum(1 for row in maze for char in row if char in GHOST_TILES)
    assert wall_count > walkable_count
    assert 180 <= sum(row.count(".") for row in maze) <= 260
    assert sum(row.count("o") for row in maze) == 4
    for row in range(len(maze) - 2):
        for column in range(len(maze[0]) - 2):
            block = [maze[row + dy][column + dx] for dy in range(3) for dx in range(3)]
            assert not all(char in PACMAN_TILES for char in block), (column, row)


def test_all_pellets_and_power_pellets_are_reachable_by_pacman():
    maze = _load_maze()
    reachable = _flood(maze, [_cells(maze, {"P"})[0]], PACMAN_TILES)
    assert set(_cells(maze, {"."})) <= reachable
    assert set(_cells(maze, {"o"})) <= reachable
    assert not reachable & set(_cells(maze, GHOST_ONLY))


def test_ghost_house_exits_to_entire_pacman_graph():
    maze = _load_maze()
    ghost_spawns = _cells(maze, GHOST_SPAWNS)
    doors = set(_cells(maze, {"D"}))
    ghost_reachable = _flood(maze, ghost_spawns, GHOST_TILES)
    assert doors <= ghost_reachable
    exits: list[tuple[int, int]] = []
    for door in doors:
        assert any(
            maze[row][column] in ({"G"} | GHOST_SPAWNS)
            for column, row in _neighbors(maze, door, GHOST_TILES)
        )
        exits.extend(
            [
                tile
                for tile in _neighbors(maze, door, GHOST_TILES)
                if maze[tile[1]][tile[0]] in PACMAN_TILES
            ]
        )
    assert exits
    pacman_reachable = _flood(maze, [_cells(maze, {"P"})[0]], PACMAN_TILES)
    outside_from_exits = _flood(maze, exits, PACMAN_TILES)
    assert pacman_reachable <= outside_from_exits


def test_side_tunnel_wraps_on_tile_graph():
    maze = _load_maze()
    left = (0, TUNNEL_ROW)
    right = (len(maze[0]) - 1, TUNNEL_ROW)
    assert maze[left[1]][left[0]] in PACMAN_TILES
    assert maze[right[1]][right[0]] in PACMAN_TILES
    assert right in _neighbors(maze, left, PACMAN_TILES)
    assert left in _neighbors(maze, right, PACMAN_TILES)


def test_movement_engine_is_tile_centered_and_buffered():
    text = _source_text()
    assert "current_tile" in text
    assert "target_tile" in text
    assert "requested_direction" in text
    assert "is_at_tile_center" in text
    assert "legal_next_tile" in text
    assert "_snap_to_current_center" in text
    assert "legal_neighbor_for_direction" in text


def test_ghost_ai_uses_graph_paths_and_does_not_reenter_house_for_chase():
    text = _source_text()
    assert "shortest_path_step" in text
    assert "allowed_symbols=PACMAN_LEGAL" in text
    assert "ghost_exit_tiles" in text
    assert "released" in text
    assert "nearest_pacman_tile" in text


def test_fruit_and_sound_progression_are_kept():
    text = _source_text()
    assert "PACMAN_SOUND_FILES" in text
    assert "QSoundEffect" in text
    assert "FRUIT_SEQUENCE" in text
    assert "def fruit_name" in text
    assert "cherry" in text
    assert "strawberry" in text
    assert "orange" in text


def test_pellet_counts_match_map_symbols():
    maze = _load_maze()
    assert sum(row.count(".") for row in maze) == len(_cells(maze, {"."}))
    assert sum(row.count("o") for row in maze) == len(_cells(maze, {"o"}))
