"""The location game's guessing map: the approved island maps combined on one grid.

Most islands already share Hypixel's coordinates. The ones that live in separate worlds are
shifted into place by OFFSETS. Every CELL×CELL patch of ground belongs to one island: each map's
connected patches go to the map whose middle they are nearest (relative to its size), so a
neighbour's scenery seen from another island counts as that neighbour. A pin in the void counts
as the nearest island.
"""

import hashlib
import io
import math
from collections import deque
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter

# Islands in separate worlds, moved to sit beside their neighbours (owner-approved 2026-10-11).
OFFSETS = {
    "mining_2": (-8, -575),  # Deep Caverns, matched to its rock on the Crimson Isle render
    "fishing_1": (287, 4),  # Backwater Bayou, east of the Hub, level with its middle
    "lotus_atoll": (291, 221),  # Lotus Atoll, below the Bayou
    "safari": (-928, 179),  # The Safari, beside Torrhus's blimps
}
CELL = 4
MAX_POINTS = 5000
PERFECT = 3.0


@dataclass(frozen=True)
class Island:
    key: str
    name: str
    index: int
    box: tuple[int, int, int, int]  # x0, z0, x1, z1 in world blocks, end exclusive

    @property
    def size(self):
        return math.hypot(self.box[2] - self.box[0], self.box[3] - self.box[1])


@dataclass
class _Map:
    island: str
    name: str
    image: Image.Image
    x: int  # world position of the map's top-left block
    z: int
    cx: int = 0  # top-left cell of the coverage grid
    cz: int = 0
    cols: int = 0
    rows: int = 0
    cover: bytes = b""

    def covers(self, col, row):
        col, row = col - self.cx, row - self.cz
        return 0 <= col < self.cols and 0 <= row < self.rows and self.cover[row * self.cols + col]


class World:
    def __init__(self, revision, x0, z0, cols, rows, owner, nearest, islands, png):
        self.revision, self.x0, self.z0, self.cols, self.rows = revision, x0, z0, cols, rows
        self.owner, self.nearest, self.png = owner, nearest, png
        self.islands = islands
        self._by_index = {island.index: island for island in islands.values()}

    @property
    def width(self):
        return self.cols * CELL

    @property
    def height(self):
        return self.rows * CELL

    def spot(self, island, x, z):
        """A captured position in world blocks."""
        dx, dz = OFFSETS.get(island, (0, 0))
        return x + dx, z + dz

    def island_at(self, x, z):
        col = min(max(int((x - self.x0) // CELL), 0), self.cols - 1)
        row = min(max(int((z - self.z0) // CELL), 0), self.rows - 1)
        index = self.owner[row * self.cols + col] or self.nearest[row * self.cols + col]
        island = self._by_index.get(index)
        return island.key if island else None

    def score(self, island, spot_x, spot_z, x, z):
        """Points, distance in blocks (None on the wrong island) and the island guessed."""
        guessed = self.island_at(x, z)
        if guessed != island:
            return 0, None, guessed
        distance = math.hypot(x - spot_x, z - spot_z)
        if distance <= PERFECT:
            return MAX_POINTS, distance, guessed
        # A bell curve: 20 blocks off on the Hub costs about 600 points, a miss across
        # most of an island nearly all of them.
        scale = self.islands[island].size / 11
        return round(MAX_POINTS * math.exp(-((distance / scale) ** 2))), distance, guessed

    def describe(self):
        return {
            "revision": self.revision,
            "x": self.x0,
            "z": self.z0,
            "width": self.width,
            "height": self.height,
            "islands": [
                {"key": island.key, "name": island.name, "box": list(island.box)}
                for island in sorted(self.islands.values(), key=lambda item: item.index)
            ],
        }


def _neighbours(cell, cols, rows):
    row, col = divmod(cell, cols)
    if row:
        yield cell - cols
    if row < rows - 1:
        yield cell + cols
    if col:
        yield cell - 1
    if col < cols - 1:
        yield cell + 1


def _flood(start, joined, seen, cols, rows):
    """Every cell joined to `start`, marking them seen."""
    seen[start] = 1
    queue, found = deque([start]), [start]
    while queue:
        for other in _neighbours(queue.popleft(), cols, rows):
            if joined[other] and not seen[other]:
                seen[other] = 1
                queue.append(other)
                found.append(other)
    return found


def _labels(cover, cols, rows):
    """Connected patches of covered cells, joining patches one cell apart."""
    joined = cover
    if cols >= 3 and rows >= 3:
        joined = Image.frombytes("L", (cols, rows), cover).filter(ImageFilter.MaxFilter(3))
        joined = joined.tobytes()
    seen = bytearray(cols * rows)
    patches = []
    for start in range(cols * rows):
        if joined[start] and not seen[start]:
            cells = [cell for cell in _flood(start, joined, seen, cols, rows) if cover[cell]]
            if cells:
                patches.append(cells)
    return patches


@dataclass(frozen=True)
class _Grid:
    x0: int
    z0: int
    cols: int
    rows: int


def _place(maps):
    placed = []
    for entry in maps:
        dx, dz = OFFSETS.get(entry["island"], (0, 0))
        placed.append(
            _Map(
                entry["island"],
                entry["island_name"],
                entry["image"].convert("RGBA"),
                entry["min_x"] + dx,
                entry["min_z"] + dz,
            )
        )
    x0 = min(item.x for item in placed) // CELL * CELL
    z0 = min(item.z for item in placed) // CELL * CELL
    cols = -(-(max(item.x + item.image.width for item in placed) - x0) // CELL)
    rows = -(-(max(item.z + item.image.height for item in placed) - z0) // CELL)
    grid = _Grid(x0, z0, cols, rows)
    for item in placed:
        _cover(item, grid)
    return placed, grid


def _cover(item, grid):
    """The map's coverage, one byte per cell, aligned to the world grid."""
    left, top = (item.x - grid.x0) % CELL, (item.z - grid.z0) % CELL
    item.cx, item.cz = (item.x - grid.x0) // CELL, (item.z - grid.z0) // CELL
    item.cols = -(-(left + item.image.width) // CELL)
    item.rows = -(-(top + item.image.height) // CELL)
    alpha = Image.new("L", (item.cols * CELL, item.rows * CELL))
    alpha.paste(item.image.getchannel("A"), (left, top))
    item.cover = alpha.reduce(CELL).point(lambda value: 255 if value else 0).tobytes()


def _remoteness(item, x, z):
    """How far a point is from a map's middle, relative to the map's size."""
    width, height = item.image.width, item.image.height
    return math.hypot(x - (item.x + width / 2), z - (item.z + height / 2)) / (
        math.hypot(width, height) / 2
    )


def _keeper(placed, patch, grid):
    """Of the maps showing most of a patch, the one whose middle it is nearest."""
    x = sum(col for _, col in patch) / len(patch) * CELL + grid.x0
    z = sum(row for row, _ in patch) / len(patch) * CELL + grid.z0
    showing = [
        index
        for index, item in enumerate(placed)
        if sum(1 for row, col in patch if item.covers(col, row)) * 2 > len(patch)
    ]
    return min(showing, key=lambda index: _remoteness(placed[index], x, z))


def _owners(placed, grid):
    owner = bytearray(grid.cols * grid.rows)
    for index, item in enumerate(placed):
        for cells in _labels(item.cover, item.cols, item.rows):
            patch = [(item.cz + cell // item.cols, item.cx + cell % item.cols) for cell in cells]
            if _keeper(placed, patch, grid) == index:
                for row, col in patch:
                    owner[row * grid.cols + col] = index + 1
    return owner


def _islands(placed, owner, grid):
    islands = {}
    for index, item in enumerate(placed):
        cells = [cell for cell, value in enumerate(owner) if value == index + 1]
        if not cells or item.island in islands:
            continue
        rows_of = [cell // grid.cols for cell in cells]
        cols_of = [cell % grid.cols for cell in cells]
        islands[item.island] = Island(
            item.island,
            item.name,
            index + 1,
            (
                grid.x0 + min(cols_of) * CELL,
                grid.z0 + min(rows_of) * CELL,
                grid.x0 + (max(cols_of) + 1) * CELL,
                grid.z0 + (max(rows_of) + 1) * CELL,
            ),
        )
    return islands


def _nearest(owner, grid):
    """The void belongs to the nearest island."""
    nearest = bytearray(owner)
    queue = deque(cell for cell, value in enumerate(owner) if value)
    while queue:
        cell = queue.popleft()
        for other in _neighbours(cell, grid.cols, grid.rows):
            if not nearest[other]:
                nearest[other] = nearest[cell]
                queue.append(other)
    return nearest


def _draw(placed, owner, grid):
    """Everything first, then each island's own ground over its neighbours' views of it."""
    canvas = Image.new("RGBA", (grid.cols * CELL, grid.rows * CELL))
    for item in placed:
        canvas.alpha_composite(item.image, (item.x - grid.x0, item.z - grid.z0))
    cells = Image.frombytes("L", (grid.cols, grid.rows), bytes(owner))
    for index, item in enumerate(placed):
        left, top = item.x - grid.x0, item.z - grid.z0
        mine = cells.point(lambda value, wanted=index + 1: 255 if value == wanted else 0)
        mask = mine.resize(canvas.size, Image.Resampling.NEAREST).crop(
            (left, top, left + item.image.width, top + item.image.height)
        )
        canvas.paste(item.image, (left, top), ImageChops.multiply(mask, item.image.getchannel("A")))
    output = io.BytesIO()
    canvas.save(output, "PNG")
    return output.getvalue()


def build(maps):
    """maps: dicts with island, island_name, image (RGBA), min_x and min_z. None when empty."""
    if not maps:
        return None
    placed, grid = _place(maps)
    owner = _owners(placed, grid)
    png = _draw(placed, owner, grid)
    return World(
        hashlib.sha256(png).hexdigest()[:16],
        grid.x0,
        grid.z0,
        grid.cols,
        grid.rows,
        bytes(owner),
        bytes(_nearest(owner, grid)),
        _islands(placed, owner, grid),
        png,
    )
