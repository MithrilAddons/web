import {
  replayCoordinate,
  replayIndex,
  replayTile,
  type ReplayPoint,
  type Teleport,
} from "./runReplayData";

export const teleportKinds = [1, 2, 3, 4] as const;
export const teleportNames = {
  1: "Etherwarp",
  2: "Instant transmission",
  3: "Wither impact",
  4: "Other / mixed",
};
export const teleportColors = {
  1: "#bd9bff",
  2: "#74caff",
  3: "#f3c36b",
  4: "#b4bdca",
};
export type TeleportEvent = Teleport & {
  ms: number;
  from: ReplayPoint;
  to: ReplayPoint;
};

export function replayTeleports(
  points: readonly ReplayPoint[],
): TeleportEvent[] {
  return points.flatMap((point, i) =>
    point.teleport && i > 0
      ? [{ ...point.teleport, ms: point.ms, from: points[i - 1]!, to: point }]
      : [],
  );
}

export function segment(from: ReplayPoint, to: ReplayPoint): string {
  const position = (p: ReplayPoint) =>
    `${replayCoordinate(p.x).toFixed(2)} ${replayCoordinate(p.z).toFixed(2)}`;
  return `M ${position(from)} L ${position(to)}`;
}

export function replayRoute(points: readonly ReplayPoint[]): string[] {
  const paths = ["", "", "", "", ""];
  for (let i = 1; i < points.length; i++) {
    const from = points[i - 1]!,
      to = points[i]!;
    if ((from.flags | to.flags) & 2 || (!to.teleport && to.flags & 1)) continue;
    const kind = to.teleport?.kind ?? 0;
    paths[kind] += segment(from, to);
  }
  return paths;
}

export function landingRoom(
  event: TeleportEvent,
  tiles: ReadonlyMap<number, number>,
): number | undefined {
  const tile = replayTile(event.to);
  return tile === null ? undefined : tiles.get(tile);
}

export function teleportCount(events: readonly TeleportEvent[]): string {
  const total = events.reduce((sum, e) => sum + e.count, 0);
  const approximate = events.some((e) => e.inferred) ? "about " : "";
  const saturated = events.some((e) => e.count === 4) ? "+" : "";
  return `${approximate}${total}${saturated}`;
}

export function teleportSummary(events: readonly TeleportEvent[]): string {
  const kinds = teleportKinds.filter((kind) =>
    events.some((e) => e.kind === kind),
  );
  const breakdown = kinds.map(
    (kind) =>
      `${teleportCount(events.filter((e) => e.kind === kind))} ${teleportNames[kind].toLowerCase()}`,
  );
  return (
    teleportCount(events) +
    (breakdown.length ? ` (${breakdown.join(", ")})` : "")
  );
}

export function teleportBlink(
  events: readonly TeleportEvent[],
  ms: number,
  speed: number,
): TeleportEvent[] {
  return teleportWindow(events, ms, 400 * speed);
}

export function teleportWindow(
  events: readonly TeleportEvent[],
  ms: number,
  duration: number,
): TeleportEvent[] {
  return events.slice(
    replayIndex(events, ms - duration) + 1,
    replayIndex(events, ms) + 1,
  );
}
