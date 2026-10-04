import { expect, it } from "vitest";
import fixture from "../../contracts/run-replay-v1.json";
import {
  decodeReplay,
  decodeRoomSecrets,
  replayRoomSecrets,
  replayCoordinate,
  replayPosition,
  replayTime,
} from "./runReplayData";

import roomFixture from "../../contracts/run-replay-room-secrets-v1.json";

const points = decodeReplay({ ...fixture, version: 1 });

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
