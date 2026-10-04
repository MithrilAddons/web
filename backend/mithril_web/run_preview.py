"""Render the retained 300-score snapshot to PNG in memory for link previews."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

COLORS = {
    "NORMAL": "#936c4e",
    "RARE": "#bf9954",
    "ENTRANCE": "#4d9067",
    "BLOOD": "#af515e",
    "FAIRY": "#cc82b2",
    "CHAMPION": "#d6aa57",
    "PUZZLE": "#9b7bbb",
    "TRAP": "#c5824b",
}
DOORS = {"WITHER": "#d6b4e8", "BLOOD": "#f07b87"}
INK = "#f0f3f7"
MUTED = "#a4afc1"


def run_time(ticks):
    ms = ticks * 50
    return f"{ms // 60000}:{ms // 1000 % 60:02}.{ms % 1000:03}"


def count(value):
    return "?" if value is None else str(value)


def coordinate(tile):
    return 704 + tile % 6 * 70, 110 + tile // 6 * 70


def draw_room(draw, room):
    color = COLORS.get(room["type"], "#68717a")
    tiles = set(room["tiles"])
    for tile in tiles:
        x, y = coordinate(tile)
        draw.rectangle((x, y, x + 56, y + 56), fill=color)
        if tile % 6 < 5 and tile + 1 in tiles:
            draw.rectangle((x + 56, y, x + 70, y + 56), fill=color)
        if tile + 6 in tiles:
            draw.rectangle((x, y + 56, x + 56, y + 70), fill=color)
        if tile % 6 < 5 and {tile + 1, tile + 6, tile + 7} <= tiles:
            draw.rectangle((x + 56, y + 56, x + 70, y + 70), fill=color)
    x, y = coordinate(room["tiles"][0])
    # Match the web map: final counts and clear status on the room's first tile.
    draw.rounded_rectangle((x + 2, y + 29, x + 54, y + 54), radius=4, fill="#202530")
    draw.text(
        (x + 28, y + 42),
        f"{count(room['secrets_found'])}/{count(room['secrets_total'])}",
        font=ImageFont.load_default(size=14),
        fill=INK,
        anchor="mm",
    )
    state = room["state"]
    if state == "COMPLETE":
        draw.line([(x + 20, y + 13), (x + 26, y + 19), (x + 37, y + 7)], fill=INK, width=3)
    elif state == "CLEARED":
        draw.ellipse((x + 25, y + 10, x + 31, y + 16), fill=INK)
    elif state == "FAILED":
        draw.line((x + 23, y + 8, x + 33, y + 18), fill=INK, width=3)
        draw.line((x + 33, y + 8, x + 23, y + 18), fill=INK, width=3)


def render_preview(run):
    image = Image.new("RGB", (1200, 630), "#10151e")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, 1176, 606), radius=24, outline="#30394a", width=2)
    draw.rounded_rectangle((676, 76, 1146, 554), radius=18, fill="#191f2b")

    def text(x, y, value, size, color=INK):
        draw.text((x, y), value, font=ImageFont.load_default(size=size), fill=color)

    record, snapshot = run["record"], run["map"]
    text(64, 64, "MITHRIL", 24, "#a6adff")
    text(64, 144, f"{record['floor']} SOLO CLEAR", 30, MUTED)
    text(58, 196, run_time(record["ticks"]), 82)
    name = record["name"] or record["uuid"]
    text(64, 300, name, 30 if len(name) <= 16 else 22)
    stats = snapshot.get("stats")
    if stats:
        text(
            64, 382, f"Secrets  {count(stats['secrets_found'])}/{count(stats['secrets_total'])}", 26
        )
        text(64, 426, f"Crypts  {count(stats['crypts'])}", 26)
    text(64, 526, "Map at 300 score", 22, MUTED)
    text(64, 558, "mithril.foo", 20, MUTED)
    for door in snapshot["doors"]:
        ax, ay = coordinate(door["a"])
        bx, by = coordinate(door["b"])
        draw.line(
            (ax + 28, ay + 28, bx + 28, by + 28), fill=DOORS.get(door["type"], MUTED), width=10
        )
    for room in snapshot["rooms"]:
        draw_room(draw, room)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
