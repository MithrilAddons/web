import { afterEach, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import {
  decodeReplay,
  replayPosition,
  replayTrail,
  type ReplayPoint,
} from "./runReplayData";
import {
  landingRoom,
  replayRoute,
  replayTeleports,
  teleportBlink,
  teleportSummary,
  teleportCount,
} from "./replayTeleports";
import { TeleportOverlay } from "./TeleportOverlay";
import fixture from "../../contracts/run-replay-teleports-v1.json";
import legacy from "../../contracts/run-replay-v1.json";

const points = decodeReplay({ ...fixture, version: 1 });
const events = replayTeleports(points);
function encode(points: ReplayPoint[]) {
  const bytes = new Uint8Array(points.length * 12),
    view = new DataView(bytes.buffer);
  points.forEach((p, i) => {
    const offset = i * 12;
    view.setUint32(offset, p.ms, true);
    view.setInt16(offset + 4, p.x * 16, true);
    view.setInt16(offset + 6, p.z * 16, true);
    view.setUint8(offset + 9, p.flags);
    view.setUint16(offset + 10, p.secrets, true);
  });
  return { version: 1 as const, samples: btoa(String.fromCharCode(...bytes)) };
}
afterEach(cleanup);

it("decodes the shared kinds and chain counts, preserving snap boundaries", () => {
  expect(events.map((e) => [e.kind, e.count, e.inferred])).toEqual([
    [1, 1, false],
    [2, 3, false],
    [3, 1, false],
    [4, 4, false],
  ]);
  expect(replayPosition(points, 399)?.x).toBe(-184);
  expect(replayPosition(points, 400)?.x).toBe(-153);
  expect(replayPosition(points, 1100)?.teleport).toBeNull();
  expect(replayTrail(points, 700).at(-1)?.teleport).toBeNull();
  expect(teleportSummary(events)).toBe(
    "9+ (1 etherwarp, 3 instant transmission, 1 wither impact, 4+ other / mixed)",
  );
  expect(teleportSummary([])).toBe("0");
});

it("infers legacy short breaks only, never new capability-marked zero-event runs", () => {
  const old = decodeReplay({ ...legacy, version: 1 });
  expect(replayTeleports(old).map((e) => [e.ms, e.kind, e.inferred])).toEqual([
    [400, 4, true],
  ]);
  expect(teleportSummary(replayTeleports(old))).toBe(
    "about 1 (about 1 other / mixed)",
  );
  const marked = old.map((p) => ({ ...p }));
  marked[0]!.flags |= 128;
  expect(replayTeleports(decodeReplay(encode(marked)))).toHaveLength(0);
  marked[0]!.flags = 1;
  marked[2]!.flags = 5;
  marked[3]!.flags = 1;
  marked[3]!.x = -120;
  expect(replayTeleports(decodeReplay(encode(marked)))).toHaveLength(1);
});

it("does not infer walking, tiny corrections, huge jumps, long gaps or missing endpoints", () => {
  const origin = { ...points[0]!, flags: 1 };
  for (const change of [
    { flags: 0, x: -170 },
    { x: -183 },
    { x: -120 },
    { ms: 401, x: -170 },
    { flags: 3, x: 0 },
  ]) {
    expect(
      replayTeleports(
        decodeReplay(encode([origin, { ...points[1]!, ...change }])),
      ),
    ).toHaveLength(0);
  }
  expect(
    replayTeleports(
      decodeReplay(
        encode([
          { ...origin, flags: 3 },
          { ...points[1]!, flags: 1, x: -170 },
        ]),
      ),
    ),
  ).toHaveLength(0);
  for (const x of [-182, -125])
    expect(
      replayTeleports(
        decodeReplay(encode([origin, { ...points[1]!, flags: 1, x }])),
      ),
    ).toHaveLength(1);
});

it("splits routes by kind without bridging gaps and attributes counts to landing tiles", () => {
  const paths = replayRoute(points);
  expect(paths.map((p) => (p.match(/M /g) ?? []).length)).toEqual([
    2, 1, 1, 1, 1,
  ]);
  expect(replayRoute(decodeReplay({ ...legacy, version: 1 }))[0]).not.toContain(
    "0 0",
  );
  expect(replayRoute([{ ...points[0]!, flags: 3 }, points[1]!])).toEqual([
    "",
    "",
    "",
    "",
    "",
  ]);
  const tiles = new Map([
    [1, 0],
    [2, 0],
  ]);
  expect(events.map((e) => landingRoom(e, tiles))).toEqual([0, 0, 0, 0]);
  expect(landingRoom(events[0]!, new Map())).toBeUndefined();
  expect(
    landingRoom({ ...events[0]!, to: { ...points[0]!, flags: 3 } }, tiles),
  ).toBeUndefined();
  expect(teleportCount([{ ...events[0]!, inferred: true, count: 4 }])).toBe(
    "about 4+",
  );
});

it("keeps blinks visible for 400 wall-clock milliseconds at every playback speed", () => {
  for (const speed of [1, 2, 4, 8]) {
    expect(teleportBlink([events[0]!], 400 + 399 * speed, speed)).toHaveLength(
      1,
    );
    expect(teleportBlink([events[0]!], 400 + 400 * speed, speed)).toHaveLength(
      0,
    );
  }
  expect(teleportBlink(events, 399, 8)).toHaveLength(0);
});

it("renders route, dashed trails, saturated chain labels and reduced-motion alternatives", () => {
  const props = {
    events,
    paths: replayRoute(points),
    ms: 1100,
    speed: 2,
    showRoute: true,
  };
  const { rerender } = render(
    <svg>
      <TeleportOverlay {...props} />
    </svg>,
  );
  expect(document.querySelectorAll(".replay-route path")).toHaveLength(5);
  expect(document.querySelectorAll(".replay-teleport-blink")).toHaveLength(4);
  expect(document.querySelectorAll(".teleport-static")).toHaveLength(4);
  expect(document.querySelectorAll(".teleport-motion")).toHaveLength(8);
  expect(
    document.querySelector(".replay-teleport-blink:last-child")?.textContent,
  ).toBe("×4+");
  rerender(
    <svg>
      <TeleportOverlay {...props} showRoute={false} ms={5000} />
    </svg>,
  );
  expect(document.querySelector(".replay-route")).toBeNull();
  expect(document.querySelector(".replay-teleport-blink")).toBeNull();
  rerender(
    <svg>
      <TeleportOverlay
        {...props}
        events={[{ ...events[0]!, from: { ...points[0]!, flags: 3 } }]}
        ms={450}
      />
    </svg>,
  );
  expect(document.querySelector(".replay-teleport-path")).toBeTruthy();
  expect(document.querySelectorAll(".teleport-motion")).toHaveLength(1);
});
