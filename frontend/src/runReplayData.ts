export type ReplayData = { version: 1; samples: string; room_secrets?: string };
type RoomSecret = { ms: number; found: number };

export function decodeRoomSecrets(
  data?: ReplayData,
): Map<number, RoomSecret[]> | null {
  if (data?.room_secrets === undefined) return null;
  const bytes = Uint8Array.from(atob(data.room_secrets), (value) =>
    value.codePointAt(0)!,
  );
  const view = new DataView(bytes.buffer);
  const rooms = new Map<number, RoomSecret[]>();
  for (let offset = 0; offset < bytes.length; offset += 6) {
    const tile = view.getUint8(offset + 4);
    const events = rooms.get(tile) ?? [];
    events.push({
      ms: view.getUint32(offset, true),
      found: view.getUint8(offset + 5),
    });
    rooms.set(tile, events);
  }
  return rooms;
}

export function replayRoomSecrets(
  rooms: Map<number, RoomSecret[]>,
  tile: number,
  ms: number,
): number {
  const events = rooms.get(tile) ?? [];
  return events[replayIndex(events, ms)]?.found ?? 0;
}
export type ReplayPoint = {
  ms: number;
  x: number;
  z: number;
  yaw: number;
  flags: number;
  secrets: number;
};

export function decodeReplay(data: ReplayData): ReplayPoint[] {
  const bytes = Uint8Array.from(atob(data.samples), (value) =>
    value.codePointAt(0)!,
  );
  const view = new DataView(bytes.buffer);
  const points: ReplayPoint[] = [];
  for (let offset = 0; offset < bytes.length; offset += 12) {
    points.push({
      ms: view.getUint32(offset, true),
      x: view.getInt16(offset + 4, true) / 16,
      z: view.getInt16(offset + 6, true) / 16,
      yaw: (view.getUint8(offset + 8) * 360) / 256,
      flags: view.getUint8(offset + 9),
      secrets: view.getUint16(offset + 10, true),
    });
  }
  return points;
}

export function replayIndex(
  points: readonly { ms: number }[],
  ms: number,
): number {
  let low = 0,
    high = points.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (points[middle]!.ms <= ms) low = middle + 1;
    else high = middle;
  }
  return low - 1;
}

export function replayPosition(
  points: readonly ReplayPoint[],
  ms: number,
): ReplayPoint | null {
  const index = replayIndex(points, ms);
  const point = points[index];
  if (!point || point.flags & 2) return null;
  const next = points[index + 1];
  if (!next || next.flags & 3) return point;
  const fraction = (ms - point.ms) / (next.ms - point.ms);
  const rotation = ((next.yaw - point.yaw + 540) % 360) - 180;
  return {
    ...point,
    x: point.x + (next.x - point.x) * fraction,
    z: point.z + (next.z - point.z) * fraction,
    yaw: point.yaw + rotation * fraction,
  };
}

/** Match the map's room rectangles and enlarged door gaps. */
export function replayCoordinate(world: number): number {
  const position = world + 200;
  const tile = Math.floor(position / 32),
    offset = position - tile * 32;
  return (
    10 +
    tile * 60 +
    (offset <= 31 ? (offset * 48) / 31 : 48 + (offset - 31) * 12)
  );
}

export function replayTime(ms: number): string {
  ms = Math.floor(ms);
  return `${Math.floor(ms / 60000)}:${(Math.floor(ms / 1000) % 60).toString().padStart(2, "0")}.${(ms % 1000).toString().padStart(3, "0")}`;
}

/** A sample in a door gap or outside the six-by-six map has no room. */
export function replayTile(point: ReplayPoint | null): number | null {
  if (!point || point.flags & 2) return null;
  const x = point.x + 200,
    z = point.z + 200;
  const col = Math.floor(x / 32),
    row = Math.floor(z / 32);
  if (
    col < 0 ||
    col >= 6 ||
    row < 0 ||
    row >= 6 ||
    x - col * 32 > 31 ||
    z - row * 32 > 31
  )
    return null;
  return row * 6 + col;
}

export type RoomVisit = { room: number; start: number; end: number };
export function replayVisits(
  points: readonly ReplayPoint[],
  tiles: ReadonlyMap<number, number>,
): RoomVisit[] {
  const visits: RoomVisit[] = [];
  let current: RoomVisit | undefined;
  for (const [index, point] of points.entries()) {
    const tile = replayTile(point);
    const room = tile === null ? undefined : tiles.get(tile);
    if (room === undefined) {
      current = undefined;
      continue;
    }
    const end = points[index + 1]?.ms ?? point.ms;
    if (current?.room === room) current.end = end;
    else {
      current = { room, start: point.ms, end };
      visits.push(current);
    }
  }
  return visits;
}

export function compactTime(ms: number): string {
  const seconds = Number(((ms % 60000) / 1000).toFixed(3));
  if (ms < 60000) return `${seconds} s`;
  return `${Math.floor(ms / 60000)}:${seconds < 10 ? "0" : ""}${seconds}`;
}

export function replayTrail(
  points: readonly ReplayPoint[],
  ms: number,
): ReplayPoint[] {
  const start = Math.max(0, ms - 3000);
  const trail = points.slice(
    replayIndex(points, start) + 1,
    replayIndex(points, ms) + 1,
  );
  const first = replayPosition(points, start),
    last = replayPosition(points, ms);
  if (first) trail.unshift({ ...first, ms: start, flags: 0 });
  if (last && trail.at(-1)?.ms !== ms) trail.push({ ...last, ms, flags: 0 });
  return trail;
}
