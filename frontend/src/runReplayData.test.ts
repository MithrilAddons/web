import { expect, it } from "vitest";
import fixture from "../../contracts/run-replay-v1.json";
import {
  decodeReplay,
  decodeRoomSecrets,
  replayRoomSecrets,
  replayCoordinate,
  replayPosition,
  replayTime,
  replayTile,
  replayVisits,
  compactTime,
  replayTrail,
  inferRoomSecrets,
} from "./runReplayData";

import roomFixture from "../../contracts/run-replay-room-secrets-v1.json";

const points = decodeReplay({ ...fixture, version: 1 });

it("infers legacy room progress at pickup observations across tiles and repeat visits", () => {
  const route = [
    { ...points[0]!, ms: 0, secrets: 0 },
    { ...points[0]!, ms: 200, secrets: 1 },
    { ...points[0]!, ms: 400, x: -153, secrets: 3 },
    { ...points[0]!, ms: 600, x: -121, secrets: 3 },
    { ...points[0]!, ms: 800, x: -121, secrets: 4 },
    { ...points[0]!, ms: 1000, secrets: 4 },
    { ...points[0]!, ms: 1200, secrets: 5 },
  ];
  const rooms = inferRoomSecrets(route, [
    { tiles: [0, 1], secrets_found: 4 },
    { tiles: [2], secrets_found: 1 },
  ]);
  expect(replayRoomSecrets(rooms, 0, 0)).toBe(0);
  expect(replayRoomSecrets(rooms, 0, 200)).toBe(1);
  expect(replayRoomSecrets(rooms, 0, 400)).toBe(3);
  expect(replayRoomSecrets(rooms, 2, 600)).toBe(0);
  expect(replayRoomSecrets(rooms, 2, 800)).toBe(1);
  expect(replayRoomSecrets(rooms, 0, 1000)).toBe(3);
  expect(replayRoomSecrets(rooms, 0, 1200)).toBe(4);
  expect(replayRoomSecrets(rooms, 0, 199)).toBe(0);
  expect(rooms.has(1)).toBe(false);
});

it("caps legacy estimates and never moves unlocated or excess pickups to another room", () => {
  const route = [
    { ...points[0]!, ms: 0, secrets: 2 },
    { ...points[0]!, ms: 200, secrets: 4 },
    { ...points[0]!, ms: 400, flags: 3, secrets: 5 },
    { ...points[0]!, ms: 600, x: -168.5, secrets: 6 },
    { ...points[0]!, ms: 800, x: -121, secrets: 7 },
    { ...points[0]!, ms: 1000, x: -153, secrets: 7 },
    { ...points[0]!, ms: 1200, x: -153, secrets: 8 },
    { ...points[0]!, ms: 1400, x: -89, secrets: 9 },
    { ...points[0]!, ms: 1600, x: -57, secrets: 10 },
  ];
  const rooms = inferRoomSecrets(route, [
    { tiles: [0], secrets_found: 1 },
    { tiles: [1], secrets_found: 2 },
    { tiles: [3], secrets_found: null },
    { tiles: [4], secrets_found: 0 },
  ]);
  expect(rooms.get(0)).toEqual([{ ms: 0, found: 1 }]);
  expect(replayRoomSecrets(rooms, 1, 1000)).toBe(0);
  expect(rooms.get(1)).toEqual([{ ms: 1200, found: 1 }]);
  expect(rooms.size).toBe(2);
  expect(inferRoomSecrets([], []).size).toBe(0);
});

it("decodes the mod wire fixture with positions, yaw, counters and exact cutoff", () => {
  expect(points).toHaveLength(7);
  expect(points[1]).toEqual({
    ms: 200,
    x: -184,
    z: -185,
    yaw: 90,
    flags: 0,
    secrets: 1,
  });
  expect(points.at(-1)?.ms).toBe(15000);
});

it("maps room boundaries, door gaps and invalid positions without wrapping rows", () => {
  const point = { ...points[0]!, flags: 0 };
  expect(replayTile(null)).toBeNull();
  expect(replayTile({ ...point, flags: 2 })).toBeNull();
  expect(replayTile({ ...point, x: -200, z: -200 })).toBe(0);
  expect(replayTile({ ...point, x: -169, z: -169 })).toBe(0);
  expect(replayTile({ ...point, x: -168, z: -168 })).toBe(7);
  expect(replayTile({ ...point, x: -168.5 })).toBeNull();
  expect(replayTile({ ...point, z: -168.5 })).toBeNull();
  expect(replayTile({ ...point, x: -200.0625 })).toBeNull();
  expect(replayTile({ ...point, x: -8 })).toBeNull();
  expect(replayTile({ ...point, z: -8 })).toBeNull();
  expect(replayTile({ ...point, x: -9, z: -9 })).toBe(35);
});

it("combines multi-tile visits, keeps transit gaps, and records repeat entries", () => {
  const tiles = new Map([
    [0, 0],
    [1, 0],
  ]);
  expect(replayVisits(points, tiles)).toEqual([
    { room: 0, start: 0, end: 800 },
    { room: 0, start: 1000, end: 15000 },
  ]);
  expect(replayVisits([], tiles)).toEqual([]);
  expect(replayVisits(points, new Map())).toEqual([]);
  const route = [
    { ...points[0]!, ms: 0 },
    { ...points[0]!, ms: 200, x: -168.5 },
    { ...points[0]!, ms: 400, x: -153 },
    { ...points[0]!, ms: 600 },
  ];
  expect(
    replayVisits(
      route,
      new Map([
        [0, 0],
        [1, 1],
      ]),
    ),
  ).toEqual([
    { room: 0, start: 0, end: 200 },
    { room: 1, start: 400, end: 600 },
    { room: 0, start: 600, end: 600 },
  ]);
});

it("formats room times compactly without changing headline precision", () => {
  expect(compactTime(0)).toBe("0 s");
  expect(compactTime(6750)).toBe("6.75 s");
  expect(compactTime(62400)).toBe("1:02.4");
  expect(compactTime(60000)).toBe("1:00");
  expect(replayTime(62400)).toBe("1:02.400");
});

it("clips the trail to three seconds and preserves discontinuity flags", () => {
  const trail = replayTrail(points, 600);
  expect(trail.map((p) => p.ms)).toEqual([0, 200, 400, 600]);
  expect(trail[2]?.flags).toBe(1);
  expect(replayTrail(points, 900).at(-1)?.flags).toBe(3);
  expect(replayTrail(points, 5000).map((p) => p.ms)).toEqual([2000, 5000]);
  expect(replayTrail([], 1000)).toEqual([]);
});

it("interpolates movement and wrapped facing without crossing teleports or gaps", () => {
  const between = replayPosition(points, 100)!;
  expect(between.x).toBe(-184.5);
  expect(between.yaw).toBe(45);
  expect(replayPosition(points, 399)?.x).toBe(-184);
  expect(replayPosition(points, 400)?.x).toBe(-153);
  expect(replayPosition(points, 900)).toBeNull();
  expect(replayPosition(points, -1)).toBeNull();
  expect(replayPosition(points, 15000)).toEqual(points.at(-1));
  const wrapped = [
    { ...points[0]!, yaw: 350 },
    { ...points[1]!, yaw: 10 },
  ];
  expect(replayPosition(wrapped, 100)?.yaw).toBe(360);
});

it("aligns world positions to rooms and door gaps and formats elapsed time", () => {
  expect(replayCoordinate(-200)).toBe(10);
  expect(replayCoordinate(-169)).toBe(58);
  expect(replayCoordinate(-168.5)).toBe(64);
  expect(replayCoordinate(-168)).toBe(70);
  expect(replayTime(61123.9)).toBe("1:01.123");
});

it("decodes recorded room counters, including backward seeks and empty timelines", () => {
  const rooms = decodeRoomSecrets({ ...roomFixture, version: 1 })!;
  expect(replayRoomSecrets(rooms, 0, 199)).toBe(0);
  expect(replayRoomSecrets(rooms, 0, 200)).toBe(1);
  expect(replayRoomSecrets(rooms, 0, 999)).toBe(2);
  expect(replayRoomSecrets(rooms, 0, 15000)).toBe(3);
  expect(replayRoomSecrets(rooms, 0, 599)).toBe(1);
  expect(replayRoomSecrets(rooms, 7, 15000)).toBe(0);
  expect(decodeRoomSecrets({ ...fixture, version: 1 })).toBeNull();
  expect(decodeRoomSecrets()).toBeNull();
  expect(
    decodeRoomSecrets({ ...fixture, version: 1, room_secrets: "" })?.size,
  ).toBe(0);
});
