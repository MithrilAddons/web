import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RunMap } from "./RunMap";
import { App } from "./App";
import replay from "../../contracts/run-replay-room-secrets-v1.json";
import legacyReplay from "../../contracts/run-replay-v1.json";
import timedMap from "../../contracts/run-map-v2.json";

const id = "a".repeat(43);
const data = {
  version: 1,
  record: {
    id,
    uuid: "a".repeat(32),
    name: "Synthetic",
    floor: "F7",
    ticks: 1801,
    created: 1700000000,
  },
  map: {
    version: 1,
    rooms: [
      {
        tiles: [0, 1, 7],
        name: "Synthetic room",
        type: "NORMAL",
        state: "CLEARED",
        secrets_found: 3,
        secrets_total: 5,
      },
      {
        tiles: [2],
        name: "Puzzle",
        type: "PUZZLE",
        state: "COMPLETE",
        secrets_found: 0,
        secrets_total: 0,
      },
      {
        tiles: [8],
        name: null,
        type: "UNKNOWN",
        state: "UNKNOWN",
        secrets_found: null,
        secrets_total: null,
      },
    ],
    doors: [
      { a: 1, b: 2, type: "WITHER" },
      { a: 2, b: 8, type: "BLOOD" },
    ],
  },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

function mock(value: unknown = data, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(value), { status })),
  );
}

it("renders final geometry with no default selection and accessible room controls", async () => {
  mock();
  render(<RunMap recordId={id} />);
  await screen.findByRole("heading", { name: "1:30.050 by Synthetic" });
  expect(fetch).toHaveBeenCalledWith(
    `/api/v1/records/solo/${id}`,
    expect.objectContaining({ cache: "no-store" }),
  );
  expect(screen.getByRole("heading", { name: "Run summary" })).toBeTruthy();
  expect(screen.queryByText("Size")).toBeNull();
  const map = screen.getByRole("group", {
    name: "Dungeon layout at 300 score",
  });
  expect(map.querySelector("line")?.getAttribute("x1")).toBe("118");
  expect(map.querySelector("line")?.getAttribute("x2")).toBe("130");
  const length = history.length;
  const room = screen.getByRole("button", { name: "Puzzle: 0/0 secrets" });
  fireEvent.keyDown(room, { key: " " });
  expect(room.getAttribute("aria-pressed")).toBe("true");
  expect(location.hash).toBe("#room-2");
  expect(history.length).toBe(length);
  expect(screen.getByRole("heading", { name: "Puzzle" })).toBeTruthy();
  expect(room.querySelector("title")?.textContent).toContain("Puzzle");
  fireEvent.keyDown(
    screen.getByRole("button", { name: "Unknown room: ?/? secrets" }),
    { key: "Enter" },
  );
  expect(
    screen.getByText("Part of this room’s secret counter was not captured."),
  ).toBeTruthy();
});
it("routes map URLs and explains retired or missing maps", async () => {
  mock({ ...data, map: null });
  history.replaceState(null, "", `/runs/${id}`);
  render(<App />);
  expect(
    await screen.findByRole("heading", { name: "Map unavailable" }),
  ).toBeTruthy();
  expect(screen.getByText(/Maps are kept only/)).toBeTruthy();
  expect(document.querySelector("main")?.className).toBe("run-page-main");
});
it.each([
  [404, "This run is unavailable."],
  [503, "Could not load this run. Try again shortly."],
])("handles HTTP %s", async (status, message) => {
  mock({}, status as number);
  render(<RunMap recordId={id} />);
  expect((await screen.findByRole("alert")).textContent).toBe(message);
});
it("rejects unsupported maps and escapes room labels", async () => {
  mock({ ...data, map: { ...data.map, version: 3 } });
  render(<RunMap recordId={id} />);
  expect((await screen.findByRole("alert")).textContent).toContain(
    "unsupported map format",
  );
  cleanup();
  const changed = structuredClone(data);
  changed.map.rooms[0]!.name = "<script>bad()</script>";
  mock(changed);
  render(<RunMap recordId={id} />);
  fireEvent.click(
    await screen.findByRole("button", {
      name: "<script>bad()</script>: 3/5 secrets",
    }),
  );
  expect(
    screen.getByRole("heading", { name: "<script>bad()</script>" }),
  ).toBeTruthy();
  expect(document.querySelector("script")).toBeNull();
});
it("shows compact totals, proportional timing bars and sortable room times", async () => {
  mock({ ...data, record: { ...data.record, ticks: 300 }, map: timedMap });
  render(<RunMap recordId={id} />);
  await screen.findByRole("heading", { name: "0:15.000 by Synthetic" });
  const totals = screen.getByLabelText("Dungeon totals at 300 score");
  expect(totals.textContent).toContain("Secrets3 / 5");
  expect(totals.textContent).toContain("Crypts killed5");
  expect(totals.textContent).toContain("Rooms 14 sTransit 1 s");
  expect(screen.getByRole("progressbar").getAttribute("value")).toBe("3");
  fireEvent.change(screen.getByRole("combobox", { name: "Sort by" }), {
    target: { value: "time" },
  });
  expect(document.querySelector(".run-room-row button")?.textContent).toContain(
    "Puzzle",
  );
  fireEvent.click(screen.getByRole("button", { name: "Room: 3/5 secrets" }));
  expect(screen.getByText("Time in room").nextElementSibling?.textContent).toBe(
    "6 s",
  );
  expect(screen.getByText("Share of run").nextElementSibling?.textContent).toBe(
    "40.0%",
  );
  expect(
    screen.getByText("Secrets per minute").nextElementSibling?.textContent,
  ).toBe("30.0");
  expect(screen.getByText("Entered at").nextElementSibling?.textContent).toBe(
    "Not recorded",
  );
  expect(
    screen.getByText(/include repeat visits/).closest("details")?.open,
  ).toBe(false);
});
it("distinguishes missing counters from measured zeros", async () => {
  mock({
    ...data,
    map: {
      ...timedMap,
      stats: {
        ...timedMap.stats,
        secrets_found: null,
        secrets_total: null,
        crypts: null,
      },
    },
  });
  render(<RunMap recordId={id} />);
  expect(await screen.findAllByText("Not captured")).toHaveLength(2);
  cleanup();
  mock({
    ...data,
    map: {
      ...timedMap,
      stats: {
        ...timedMap.stats,
        secrets_found: 0,
        secrets_total: 0,
        crypts: 0,
      },
    },
  });
  render(<RunMap recordId={id} />);
  await screen.findByLabelText("Dungeon totals at 300 score");
  expect(screen.queryByText("Not captured")).toBeNull();
});
it("handles network failures", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new DOMException("aborted", "AbortError")),
  );
  render(<RunMap recordId={id} />);
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Try again shortly",
  );
});
it("fills the center of a two by two room", async () => {
  const changed = structuredClone(data);
  changed.map.rooms[0]!.tiles = [0, 1, 6, 7];
  mock(changed);
  render(<RunMap recordId={id} />);
  await screen.findByRole("heading", { name: "Run summary" });
  expect(
    document.querySelector('rect[width="108"][height="108"]'),
  ).toBeTruthy();
});
it("opens with final counters, follows seeks and hides unreached rooms and markers", async () => {
  mock({ ...data, map: { ...timedMap, replay } });
  render(<RunMap recordId={id} />);
  const slider = await screen.findByRole("slider");
  expect(slider.getAttribute("value")).toBe("15000");
  expect(screen.getByRole("heading", { name: "Run summary" })).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Room: 3/5 secrets" }),
  ).toBeTruthy();
  fireEvent.change(slider, { target: { value: "0" } });
  expect(
    screen
      .getByRole("button", { name: "Room: 0/5 secrets" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  const puzzle = screen.getByRole("button", { name: "Puzzle: not reached" });
  expect(puzzle.querySelector(".map-room-label")).toBeNull();
  expect(
    screen
      .getByRole("button", { name: "Room: 0/5 secrets" })
      .querySelector(".map-marker"),
  ).toBeNull();
  fireEvent.change(slider, { target: { value: "600" } });
  expect(
    screen.getByRole("button", { name: "Room: 2/5 secrets" }),
  ).toBeTruthy();
  expect(
    screen.getByText("Secrets", { selector: ".run-room-details dt" })
      .nextElementSibling?.textContent,
  ).toBe("2/5");
  expect(location.hash).toBe("#t=0.6");
  fireEvent.change(slider, { target: { value: "15000" } });
  expect(
    screen.getByRole("button", { name: "Room: 3/5 secrets" }),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Puzzle: 0/0 secrets" })
      .querySelector(".map-marker"),
  ).toBeTruthy();
  fireEvent.change(slider, { target: { value: "200" } });
  expect(
    screen.getByRole("button", { name: "Room: 1/5 secrets" }),
  ).toBeTruthy();
});
it("pins a map selection without seeking; list selection pauses and seeks first entry", async () => {
  mock({ ...data, map: { ...timedMap, replay } });
  render(<RunMap recordId={id} />);
  const slider = await screen.findByRole("slider");
  fireEvent.click(screen.getByRole("button", { name: "Room: 3/5 secrets" }));
  expect(slider.getAttribute("value")).toBe("15000");
  expect(screen.getByText("Visits").nextElementSibling?.textContent).toBe("2");
  fireEvent.click(
    screen.getByRole("button", { name: "Room, 6 s, 3/5 secrets, Cleared" }),
  );
  expect(slider.getAttribute("value")).toBe("0");
  expect(screen.getByRole("button", { name: "Play replay" })).toBeTruthy();
  expect(location.hash).toBe("#room-0");
  expect(document.querySelector(".run-inline-details")).toBeTruthy();
  fireEvent.change(slider, { target: { value: "900" } });
  expect(screen.getByText("Transit / unmapped position")).toBeTruthy();
  expect(document.querySelector(".run-inline-details")).toBeNull();
});
it.each([
  ["#room-7", "Puzzle", "15000"],
  ["#t=0.6", "Room", "600"],
  ["#room-99", "Run summary", "15000"],
  ["#t=9999", "Room", "15000"],
])("loads deep link %s", async (hash, heading, position) => {
  history.replaceState(null, "", `/runs/${id}${hash}`);
  mock({ ...data, map: { ...timedMap, replay } });
  render(<RunMap recordId={id} />);
  expect(await screen.findByRole("heading", { name: heading })).toBeTruthy();
  expect(screen.getByRole("slider").getAttribute("value")).toBe(position);
});
it("keeps legacy replay counters static without prematurely showing final markers", async () => {
  mock({ ...data, map: { ...timedMap, replay: legacyReplay } });
  render(<RunMap recordId={id} />);
  const slider = await screen.findByRole("slider");
  fireEvent.change(slider, { target: { value: "600" } });
  const room = screen.getByRole("button", { name: "Room: 3/5 secrets" });
  expect(room).toBeTruthy();
  expect(room.querySelector(".map-marker")).toBeNull();
  expect(screen.getByText(/no room-counter timeline/)).toBeTruthy();
});
it("keeps a manually picked room pinned during playback and resumes following on Play", async () => {
  const frames = vi.fn<(callback: FrameRequestCallback) => number>(() => 1);
  vi.stubGlobal("requestAnimationFrame", frames);
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.spyOn(performance, "now").mockReturnValue(0);
  mock({ ...data, map: { ...timedMap, replay } });
  render(<RunMap recordId={id} />);
  await screen.findByRole("slider");
  fireEvent.click(screen.getByRole("button", { name: "Play replay" }));
  fireEvent.click(screen.getByRole("button", { name: "Puzzle: not reached" }));
  act(() => frames.mock.calls.at(-1)![0](300));
  expect(
    screen
      .getByRole("button", { name: "Puzzle: not reached" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "Pause replay" }));
  fireEvent.click(screen.getByRole("button", { name: "Play replay" }));
  expect(
    screen
      .getByRole("button", { name: "Room: 2/5 secrets" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
});
it("seeks from room details without moving mobile details to the list", async () => {
  mock({ ...data, map: { ...timedMap, replay } });
  render(<RunMap recordId={id} />);
  const slider = await screen.findByRole("slider");
  fireEvent.click(screen.getByRole("button", { name: "Room: 3/5 secrets" }));
  fireEvent.click(screen.getByRole("button", { name: "0:00.000" }));
  expect(slider.getAttribute("value")).toBe("0");
  expect(document.querySelector(".run-inline-details")).toBeNull();
  expect(
    screen
      .getByRole("button", { name: "Room: 0/5 secrets" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
});
