export type ReplayData = { version: 1; samples: string };
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
    value.charCodeAt(0),
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
